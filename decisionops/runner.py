"""Sequential evaluation, worker isolation, metadata, and human-readable reports."""

import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from . import DESCRIPTIONS, LABELS
from .backends import Backend, REPOSITORIES, parse_revision_pins
from .dataset import load_dataset
from .metrics import percentile, summarize_classifications

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "incidents.jsonl"
DEFAULT_PINS = ROOT / "model-revisions.env"


def _package_versions() -> dict[str, str | None]:
    result = {"decisionops": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]}
    for name in ("torch", "transformers", "gliclass", "laya", "huggingface-hub"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def _hardware() -> dict:
    info = {"platform": platform.platform(), "processor": platform.processor(), "cpu_count": os.cpu_count(), "ram_total_bytes": None, "gpu": None}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                info["ram_total_bytes"] = int(line.split()[1]) * 1024
                break
    except OSError:
        pass
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], text=True, capture_output=True, timeout=3, check=False)
        if result.returncode == 0:
            info["gpu"] = result.stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return info


def _rss_bytes() -> int | None:
    if sys.platform != "linux":
        return None
    # Linux ru_maxrss is reported in KiB and measures the entire worker process.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prediction_record(case: dict, backend_name: str, prediction: dict) -> dict:
    """Serialize one case prediction without merging distinct backend score fields."""
    return {
        "case_id": case["id"], "backend": backend_name,
        "selected_class": prediction["selected_class"], "scores": prediction.get("scores"),
        "inference_seconds": prediction["inference_seconds"],
        "confidence": prediction.get("confidence"), "answer_confidence": prediction.get("answer_confidence"),
        "action_act_probability": prediction.get("action_act_probability"),
        "abstention_reason": prediction.get("abstention_reason"),
        "text": case["text"], "tags": case["tags"], "expected_label": case["expected_label"],
        "needs_review": case["needs_review"], "rationale": case["rationale"],
    }


def evaluate_worker(backend_name: str, dataset_path: Path, output_dir: Path, pin_path: Path = DEFAULT_PINS) -> dict:
    os.environ["HF_HUB_OFFLINE"] = "1"
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = load_dataset(dataset_path)
    backend = Backend(backend_name, pin_path)
    backend.load()
    if backend_name != "rules":
        backend.predict("Warm-up: all service checks pass.")
    rows = []
    latencies = []
    for case in cases:
        prediction = backend.predict(case["text"])
        if prediction["inference_seconds"] is not None:
            latencies.append(prediction["inference_seconds"])
        rows.append(prediction_record(case, backend_name, prediction))
    pred_path = output_dir / "predictions.jsonl"
    pred_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    score_rows = [{"expected_label": row["expected_label"], "selected_class": row["selected_class"]} for row in rows if "unambiguous" in row["tags"]]
    metrics = summarize_classifications(score_rows, LABELS)
    challenge = [{"case_id": row["case_id"], "tags": row["tags"], "expected_label": row["expected_label"], "needs_review": row["needs_review"], "selected_class": row["selected_class"], "rationale": row["rationale"]} for row in rows if "challenge" in row["tags"]]
    pin_values = parse_revision_pins(pin_path)
    model_revision = pin_values[REPOSITORIES[backend_name][1]] if backend_name in REPOSITORIES else None
    summary = {
        "backend": backend_name, "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_labels": list(LABELS), "candidate_descriptions": DESCRIPTIONS,
        "backend_settings": {"device": "cpu" if backend_name != "rules" else None, "classification_mode": "single-label" if backend_name == "gliclass" else ("choice" if backend_name == "laya" else "deterministic"), "pytorch_cpu_threads": 4 if backend_name != "rules" else None, "batch_size": 1},
        "model_repository": REPOSITORIES[backend_name][0] if backend_name in REPOSITORIES else None,
        "model_revision": model_revision, "model_loading_seconds": backend.load_seconds,
        "warmup_calls": 0 if backend_name == "rules" else 1,
        "inference": {"sample_count": len(latencies), "p50_seconds": percentile(latencies, 0.50), "p95_seconds": percentile(latencies, 0.95)},
        "peak_process_rss_bytes": _rss_bytes(), "peak_rss_label": "Linux worker process high-water mark (not model-only memory)",
        "metrics_unambiguous": metrics, "challenge_cases": challenge,
        "dataset": {"path": str(dataset_path), "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(), "rows": len(cases)},
        "package_versions": _package_versions(), "threads": {"pytorch_cpu_threads": 4 if backend_name != "rules" else None, "batch_size": 1},
        "hardware": _hardware(),
        "interpretation": "Small hand-authored development measurements; not a held-out benchmark, production accuracy estimate, or definitive speed/quality comparison.",
        "score_semantics": {
            "gliclass": "Complete single-label softmax score map returned by the pinned pipeline's return_hierarchical output; not calibrated confidence.",
            "laya": "Native class probabilities, confidence (1 minus normalized entropy), and answer_confidence are retained separately; action_act_probability is a distinct action-head output, not authorization. Not calibrated validation.",
            "rules": "No probabilities are produced.",
        }[backend_name],
    }
    _write_json(output_dir / "summary.json", summary)
    _write_markdown(output_dir / "summary.md", summary)
    return summary


def _write_markdown(path: Path, summary: dict) -> None:
    metrics = summary["metrics_unambiguous"]
    inf = summary["inference"]
    lines = [
        f"# Development evaluation: {summary['backend']}", "",
        f"Generated: {summary['created_utc']}", "",
        "> Hand-authored development data only. These measurements are not a held-out benchmark, production accuracy estimate, or definitive speed/quality comparison.", "",
        f"- Cases: {summary['dataset']['rows']} (SHA-256 `{summary['dataset']['sha256']}`)",
        f"- Unambiguous labeled cases: {metrics['count']}",
        f"- Accuracy (abstentions count as incorrect): {metrics['accuracy']:.3f}" if metrics["accuracy"] is not None else "- Accuracy: n/a",
        f"- Coverage: {metrics['coverage']:.3f}" if metrics["coverage"] is not None else "- Coverage: n/a",
        f"- Model loading seconds: {summary['model_loading_seconds']:.3f}",
        f"- Warm-up calls excluded: {summary['warmup_calls']}",
        f"- Inference samples: {inf['sample_count']}",
        f"- Inference p50/p95 seconds: {inf['p50_seconds']:.4f} / {inf['p95_seconds']:.4f}" if inf["p50_seconds"] is not None else "- Inference p50/p95 seconds: n/a",
        f"- Peak worker RSS bytes: {summary['peak_process_rss_bytes']} (whole process, not just model)",
        "", "## Confusion matrix", "", "Rows are expected classes; columns are predictions plus abstain.", "",
        "| Expected \\ Predicted | " + " | ".join((*LABELS, "abstain")) + " |",
        "|---|" + "---:|" * (len(LABELS) + 1),
    ]
    for label, columns in metrics["confusion_matrix"].items():
        lines.append("| " + label + " | " + " | ".join(str(columns[column]) for column in (*LABELS, "abstain")) + " |")
    lines += ["", "## Challenge cases", "", "| ID | Tags | Expected | Review | Predicted | Annotation rationale |", "|---|---|---|---:|---|---|"]
    for row in summary["challenge_cases"]:
        lines.append(f"| {row['case_id']} | {', '.join(row['tags'])} | {row['expected_label'] or '—'} | {row['needs_review']} | {row['selected_class'] or 'abstain'} | {row['rationale']} |")
    lines += ["", "## Run metadata", "", f"- Versions: `{json.dumps(summary['package_versions'], sort_keys=True)}`", f"- Model revision: `{summary['model_revision']}`", f"- Candidate order: `{json.dumps(summary['candidate_labels'])}`", f"- Candidate descriptions: `{json.dumps(summary['candidate_descriptions'], sort_keys=True)}`", f"- Backend settings: `{json.dumps(summary['backend_settings'], sort_keys=True)}`", f"- Hardware: `{json.dumps(summary['hardware'], sort_keys=True)}`", f"- Score semantics: {summary['score_semantics']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_all(dataset_path: Path, output_dir: Path, pin_path: Path = DEFAULT_PINS) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    statuses = []
    for backend in ("rules", "gliclass", "laya"):
        child = output_dir / backend
        command = [sys.executable, "-m", "decisionops", "evaluate", "--backend", backend, "--dataset", str(dataset_path), "--output-dir", str(child), "--revision-file", str(pin_path), "--worker"]
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        result = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
        statuses.append({"backend": backend, "returncode": result.returncode, "output_dir": str(child), "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]})
    _write_json(output_dir / "all-summary.json", {"sequential": True, "workers": statuses})
    lines = ["# Sequential development evaluation", "", "Workers ran one at a time. See each subdirectory for raw predictions and metrics.", ""]
    for status in statuses:
        lines.append(f"- **{status['backend']}**: {'completed' if status['returncode'] == 0 else 'failed'} (exit {status['returncode']}); `{status['output_dir']}`")
        if status["returncode"]:
            lines.append("  - stderr: " + status["stderr"].replace("\n", " ")[:600])
    (output_dir / "all-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if any(item["returncode"] for item in statuses) else 0
