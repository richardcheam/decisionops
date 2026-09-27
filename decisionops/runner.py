"""Sequential evaluation, provenance, worker isolation, and reports."""

import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import subprocess
import sys
import tomllib
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import CANDIDATES, LABELS
from .backends import Backend, REPOSITORIES, build_gliclass_candidate_labels, build_laya_question, parse_revision_pins
from .dataset import load_dataset
from .metrics import percentile, summarize_challenge_and_review, summarize_classifications

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "incidents.jsonl"
DEFAULT_PINS = ROOT / "model-revisions.env"
IMPLEMENTATION_FILES = (
    ROOT / "decisionops" / "__init__.py", ROOT / "decisionops" / "backends.py",
    ROOT / "decisionops" / "dataset.py", ROOT / "decisionops" / "metrics.py",
    ROOT / "decisionops" / "rules.py", ROOT / "decisionops" / "runner.py",
    ROOT / "data" / "build_dataset.py",
)


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
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_provenance() -> dict:
    def git(*args: str) -> str | None:
        result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    dirty_lines = (git("status", "--porcelain") or "").splitlines()
    return {"head": git("rev-parse", "HEAD"), "dirty": bool(dirty_lines), "dirty_paths": [line[3:] for line in dirty_lines]}


def _candidate_representation(backend_name: str) -> dict:
    if backend_name == "gliclass":
        return {"format": "hierarchical single-label categories; leaf text is name: description", "input": {"incident": list(build_gliclass_candidate_labels())}}
    if backend_name == "laya":
        return build_laya_question()
    return {"format": "canonical candidate specifications", "ordered_values": [asdict(candidate) for candidate in CANDIDATES]}


def prediction_record(case: dict, backend_name: str, prediction: dict) -> dict:
    """Serialize output and evaluation annotations after inference has completed."""
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


def _clear_worker_artifacts(output_dir: Path) -> None:
    for name in ("predictions.jsonl", "summary.json", "summary.md", "run-status.json"):
        (output_dir / name).unlink(missing_ok=True)


def evaluate_worker(backend_name: str, dataset_path: Path, output_dir: Path, pin_path: Path = DEFAULT_PINS) -> dict:
    os.environ["HF_HUB_OFFLINE"] = "1"
    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_worker_artifacts(output_dir)
    _write_json(output_dir / "run-status.json", {"status": "running", "backend": backend_name, "started_utc": datetime.now(timezone.utc).isoformat()})
    try:
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
        (output_dir / "predictions.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        score_rows = [{"expected_label": row["expected_label"], "selected_class": row["selected_class"]} for row in rows if "unambiguous" in row["tags"]]
        metrics = summarize_classifications(score_rows, LABELS)
        challenge = [{"case_id": row["case_id"], "tags": row["tags"], "expected_label": row["expected_label"], "needs_review": row["needs_review"], "selected_class": row["selected_class"], "rationale": row["rationale"]} for row in rows if "challenge" in row["tags"]]
        challenge_metrics = summarize_challenge_and_review(rows, LABELS)
        pin_values = parse_revision_pins(pin_path)
        model_revision = pin_values[REPOSITORIES[backend_name][1]] if backend_name in REPOSITORIES else None
        implementation_hashes = {str(path.relative_to(ROOT)): _sha256(path) for path in IMPLEMENTATION_FILES}
        summary = {
            "backend": backend_name, "created_utc": datetime.now(timezone.utc).isoformat(),
            "candidate_spec": [asdict(candidate) for candidate in CANDIDATES],
            "candidate_order": list(LABELS), "candidate_representation": _candidate_representation(backend_name),
            "backend_settings": {"device": "cpu" if backend_name != "rules" else None, "classification_mode": "single-label" if backend_name == "gliclass" else ("choice" if backend_name == "laya" else "deterministic"), "pytorch_cpu_threads": 4 if backend_name != "rules" else None, "batch_size": 1},
            "model_repository": REPOSITORIES[backend_name][0] if backend_name in REPOSITORIES else None,
            "model_revision": model_revision, "model_loading_seconds": backend.load_seconds,
            "warmup_calls": 0 if backend_name == "rules" else 1,
            "inference": {"sample_count": len(latencies), "p50_seconds": percentile(latencies, 0.50), "p95_seconds": percentile(latencies, 0.95)},
            "peak_process_rss_bytes": _rss_bytes(), "peak_rss_label": "Linux worker process high-water mark (not model-only memory)",
            "metrics_unambiguous": metrics, "challenge_metrics": challenge_metrics, "challenge_cases": challenge,
            "dataset": {"path": str(dataset_path.resolve()), "sha256": _sha256(dataset_path), "rows": len(cases)},
            "git": _git_provenance(), "implementation_sha256": implementation_hashes,
            "package_versions": _package_versions(),
            "runtime": {"python": platform.python_version(), "platform": platform.platform(), "threads": {"pytorch_cpu_threads": 4 if backend_name != "rules" else None, "batch_size": 1}, "hardware": _hardware()},
            "interpretation": "Small hand-authored development measurements; not a held-out benchmark, production accuracy estimate, or definitive speed/quality comparison.",
            "score_semantics": {
                "gliclass": "Complete single-label softmax score map returned by the pinned pipeline; not calibrated confidence.",
                "laya": "Native class probabilities, confidence, answer_confidence, and action_act_probability are retained separately; the action head is not authorization. Not calibrated validation.",
                "rules": "No probabilities are produced.",
            }[backend_name],
        }
        _write_json(output_dir / "summary.json", summary)
        _write_markdown(output_dir / "summary.md", summary)
        _write_json(output_dir / "run-status.json", {"status": "complete", "backend": backend_name, "finished_utc": datetime.now(timezone.utc).isoformat()})
        return summary
    except Exception as exc:
        _write_json(output_dir / "run-status.json", {"status": "failed", "backend": backend_name, "finished_utc": datetime.now(timezone.utc).isoformat(), "error": f"{type(exc).__name__}: {exc}"})
        raise


def _seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 0.001:
        return f"{value * 1_000_000:.1f} µs"
    return f"{value * 1000:.2f} ms"


def _write_markdown(path: Path, summary: dict) -> None:
    metrics, inf = summary["metrics_unambiguous"], summary["inference"]
    labeled, review = summary["challenge_metrics"]["labeled_challenge"], summary["challenge_metrics"]["review_cases"]
    lines = [
        f"# Development evaluation: {summary['backend']}", "", f"Generated: {summary['created_utc']}", "",
        "> Hand-authored development data only. These measurements are not a held-out benchmark, production accuracy estimate, or definitive speed/quality comparison.", "",
        f"- Cases: {summary['dataset']['rows']} (SHA-256 `{summary['dataset']['sha256']}`)",
        f"- Unambiguous labeled cases: {metrics['correct']}/{metrics['count']} correct; accuracy {metrics['accuracy']:.3f}; coverage {metrics['coverage']:.3f}" if metrics["count"] else "- Unambiguous labeled cases: n/a",
        f"- Labeled challenge cases: {labeled['correct']}/{labeled['count']} correct" if labeled["count"] else "- Labeled challenge cases: n/a",
        f"- Review cases: {review['abstentions']} abstained / {review['count']} total; {review['forced_predictions']} forced predictions",
        f"- Model loading: {_seconds(summary['model_loading_seconds'])}", f"- Inference: N={inf['sample_count']}, p50={_seconds(inf['p50_seconds'])}, p95={_seconds(inf['p95_seconds'])}",
        f"- Peak worker RSS: {summary['peak_process_rss_bytes']} bytes (whole process)", "", "## Confusion matrix", "", "Rows are expected classes; columns are predictions plus abstain.", "",
        "| Expected \\ Predicted | " + " | ".join((*LABELS, "abstain")) + " |", "|---|" + "---:|" * (len(LABELS) + 1),
    ]
    for label, columns in metrics["confusion_matrix"].items():
        lines.append("| " + label + " | " + " | ".join(str(columns[column]) for column in (*LABELS, "abstain")) + " |")
    lines += ["", "## Challenge cases", "", "| ID | Tags | Expected | Review | Predicted | Annotation rationale |", "|---|---|---|---:|---|---|"]
    for row in summary["challenge_cases"]:
        lines.append(f"| {row['case_id']} | {', '.join(row['tags'])} | {row['expected_label'] or '—'} | {row['needs_review']} | {row['selected_class'] or 'abstain'} | {row['rationale']} |")
    lines += ["", "## Provenance", "", f"- Git HEAD: `{summary['git']['head']}`; dirty: `{summary['git']['dirty']}`", f"- Implementation hashes: `{json.dumps(summary['implementation_sha256'], sort_keys=True)}`", f"- Versions: `{json.dumps(summary['package_versions'], sort_keys=True)}`", f"- Model revision: `{summary['model_revision']}`", f"- Candidate representation: `{json.dumps(summary['candidate_representation'], ensure_ascii=False, sort_keys=True)}`", f"- Runtime: `{json.dumps(summary['runtime'], sort_keys=True)}`", f"- Score semantics: {summary['score_semantics']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_all(dataset_path: Path, output_dir: Path, pin_path: Path = DEFAULT_PINS) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "all-summary.json").unlink(missing_ok=True)
    (output_dir / "all-summary.md").unlink(missing_ok=True)
    statuses, summaries = [], []
    for name in ("rules", "gliclass", "laya"):
        child = output_dir / name
        child.mkdir(parents=True, exist_ok=True)
        _clear_worker_artifacts(child)
        _write_json(child / "run-status.json", {"status": "running", "backend": name, "started_utc": datetime.now(timezone.utc).isoformat()})
        command = [sys.executable, "-m", "decisionops", "evaluate", "--backend", name, "--dataset", str(dataset_path.resolve()), "--output-dir", str(child.resolve()), "--revision-file", str(pin_path.resolve()), "--worker"]
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
        status = {"backend": name, "returncode": result.returncode, "output_dir": str(child), "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}
        statuses.append(status)
        if result.returncode == 0 and (child / "summary.json").exists():
            summary = json.loads((child / "summary.json").read_text(encoding="utf-8"))
            summaries.append(summary)
        else:
            _write_json(child / "run-status.json", {"status": "failed", "backend": name, "returncode": result.returncode, "error": result.stderr[-4000:]})
    consistent = len(summaries) == len(statuses)
    if consistent:
        reference = summaries[0]
        for summary in summaries[1:]:
            consistent &= summary["dataset"]["sha256"] == reference["dataset"]["sha256"]
            consistent &= summary["candidate_spec"] == reference["candidate_spec"]
            consistent &= summary["git"]["head"] == reference["git"]["head"]
            consistent &= summary["implementation_sha256"] == reference["implementation_sha256"]
    comparison = []
    disagreements = []
    misses = {}
    if consistent:
        for summary in summaries:
            core = summary["metrics_unambiguous"]
            challenge = summary["challenge_metrics"]["labeled_challenge"]
            review = summary["challenge_metrics"]["review_cases"]
            inf = summary["inference"]
            comparison.append({"backend": summary["backend"], "core_correct": core["correct"], "core_total": core["count"], "core_accuracy": core["accuracy"], "core_coverage": core["coverage"], "labeled_challenge_correct": challenge["correct"], "labeled_challenge_total": challenge["count"], "review_abstained": review["abstentions"], "review_total": review["count"], "inference_n": inf["sample_count"], "inference_p50_seconds": inf["p50_seconds"], "inference_p95_seconds": inf["p95_seconds"], "model_load_seconds": summary["model_loading_seconds"], "peak_rss_bytes": summary["peak_process_rss_bytes"]})
        predictions = {}
        for name in ("rules", "gliclass", "laya"):
            records = [json.loads(line) for line in (output_dir / name / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
            predictions[name] = {record["case_id"]: record for record in records}
            misses[name] = [record["case_id"] for record in records if "unambiguous" in record["tags"] and record["selected_class"] != record["expected_label"]]
        for case_id in predictions["rules"]:
            outputs = {name: predictions[name][case_id]["selected_class"] for name in predictions}
            if len(set(outputs.values())) > 1:
                disagreements.append({"case_id": case_id, "expected_label": predictions["rules"][case_id]["expected_label"], "needs_review": predictions["rules"][case_id]["needs_review"], "predictions": outputs})
    else:
        for status in statuses:
            if status["returncode"] == 0:
                status["returncode"] = 1
                status["stderr"] += "\nworker provenance mismatch"
        statuses = [dict(row) for row in statuses]
    _write_json(output_dir / "all-summary.json", {"sequential": True, "consistent_provenance": consistent, "workers": statuses, "comparison": comparison, "core_misses": misses, "disagreements": disagreements})
    lines = ["# Sequential development evaluation", "", "Workers ran one at a time. These hand-authored examples are development data, not a held-out benchmark.", ""]
    if comparison:
        lines += ["| Backend | Core correct/total | Accuracy | Coverage | Labeled challenge | Review abstained/total | Inference N | p50 | p95 | Model load | Peak RSS |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for row in comparison:
            lines.append(f"| {row['backend']} | {row['core_correct']}/{row['core_total']} | {row['core_accuracy']:.3f} | {row['core_coverage']:.3f} | {row['labeled_challenge_correct']}/{row['labeled_challenge_total']} | {row['review_abstained']}/{row['review_total']} | {row['inference_n']} | {_seconds(row['inference_p50_seconds'])} | {_seconds(row['inference_p95_seconds'])} | {_seconds(row['model_load_seconds'])} | {row['peak_rss_bytes']} bytes |")
    else:
        lines.append("No comparison table is available because at least one worker failed or provenance did not match.")
    lines += ["", "## Worker status", ""]
    for status in statuses:
        lines.append(f"- **{status['backend']}**: {'completed' if status['returncode'] == 0 else 'failed'} (exit {status['returncode']}); `{status['output_dir']}`")
        if status["returncode"]:
            lines.append("  - stderr: " + status["stderr"].replace("\n", " ")[:600])
    if consistent:
        lines += ["", "## Core misses and disagreements", "", "Core misses list labeled development cases where each backend predicted incorrectly or abstained.", "", "| Backend | Missed core case IDs |", "|---|---|"]
        for name, case_ids in misses.items():
            lines.append(f"| {name} | {', '.join(case_ids) if case_ids else 'none'} |")
        lines += ["", "Cases with differing predictions across backends:", ""]
        if disagreements:
            lines += ["| Case | Expected | Review | Rules | GLiClass | Laya |", "|---|---|---:|---|---|---|"]
            for row in disagreements:
                values = row["predictions"]
                lines.append(f"| {row['case_id']} | {row['expected_label'] or '—'} | {row['needs_review']} | {values['rules'] or 'abstain'} | {values['gliclass'] or 'abstain'} | {values['laya'] or 'abstain'} |")
        else:
            lines.append("No disagreements.")
    lines += ["", "## Reading the results", "", "Core accuracy counts abstentions as incorrect; coverage reports the share receiving a class. Labeled challenge rows have explicit labels and are scored separately. Review rows have no target class: only abstentions and forced predictions are counted. p50/p95 use prediction calls after the excluded warm-up. These 48 authored cases are small and do not establish general model quality.", ""]
    (output_dir / "all-summary.md").write_text("\n".join(lines), encoding="utf-8")
    return 0 if consistent and all(item["returncode"] == 0 for item in statuses) else 1
