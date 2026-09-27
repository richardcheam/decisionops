"""Controlled offline GLiClass candidate-format and order diagnostic."""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"

from decisionops import CANDIDATES  # noqa: E402
from decisionops.backends import REPOSITORIES, offline_model_path, parse_revision_pins  # noqa: E402
from decisionops.dataset import load_dataset  # noqa: E402
from decisionops.runner import DEFAULT_DATASET, DEFAULT_PINS  # noqa: E402

REPORT_DIR = ROOT / "reports" / "gliclass-format-diagnostic-20260927"
FIXED_CASE_IDS = (
    "core-database_failure-01", "core-database_failure-02",
    "core-authentication_failure-01", "core-authentication_failure-02",
    "core-disk_full-01", "core-disk_full-02",
    "core-healthy-01", "core-healthy-02",
)
ANCHORS = (
    ("anchor-database-timeout", "Database connections time out and requests fail.", "database_failure"),
    ("anchor-healthy", "All health checks pass and the service is operating normally.", "healthy"),
    ("anchor-disk-full", "The disk is full and the service cannot write log files.", "disk_full"),
)
FORMAT_IDS = ("A-flat-short", "B-hierarchical-short", "C-flat-description", "D-hierarchical-description")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def input_candidates(format_id: str, rotation: int) -> tuple[list[str], list[str] | dict[str, list[str]]]:
    ordered = list(CANDIDATES[rotation:]) + list(CANDIDATES[:rotation])
    if format_id.endswith("short"):
        values = [candidate.name for candidate in ordered]
    else:
        values = [f"{candidate.name}: {candidate.description}" for candidate in ordered]
    labels = {"flat": values, "hierarchical": {"incident": values}}["hierarchical" if format_id.startswith(("B-", "D-")) else "flat"]
    return values, labels


def flatten_output(value, prefix: str = "") -> dict[str, float]:
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            full = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, dict):
                result.update(flatten_output(child, full))
            else:
                result[full] = float(child)
    return result


def label_marker_occurrences(token_ids: list[int], marker_ids: list[int]) -> int:
    if not marker_ids or len(marker_ids) > len(token_ids):
        return 0
    return sum(token_ids[index : index + len(marker_ids)] == marker_ids for index in range(len(token_ids) - len(marker_ids) + 1))


def run() -> dict:
    import torch
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer

    torch.set_num_threads(4)
    pins = parse_revision_pins(DEFAULT_PINS)
    repository, revision_key = REPOSITORIES["gliclass"]
    revision = pins[revision_key]
    model_path = offline_model_path(hf_hub_download, repository, revision)
    started_load = time.perf_counter()
    model = GLiClassModel.from_pretrained(model_path, local_files_only=True)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    pipeline = ZeroShotClassificationPipeline(model, tokenizer, classification_type="single-label", device="cpu", progress_bar=False)
    load_seconds = time.perf_counter() - started_load

    config = model.config
    cases_by_id = {case["id"]: case for case in load_dataset(DEFAULT_DATASET)}
    selected_cases = [cases_by_id[case_id] for case_id in FIXED_CASE_IDS]
    if len(selected_cases) != 8:
        raise RuntimeError("preselected diagnostic cases are missing from the checked-in dataset")
    calls = []
    hook_values: list[object] = []

    def capture_output(_module, _inputs, output):
        hook_values.append(output)

    hook = model.register_forward_hook(capture_output)
    marker_ids = tokenizer("<<LABEL>>", add_special_tokens=False)["input_ids"]

    def evaluate(text: str, case_id: str, expected_label: str, format_id: str, rotation: int, group: str) -> dict:
        ordered_values, label_input = input_candidates(format_id, rotation)
        ordered_specs = list(CANDIDATES[rotation:]) + list(CANDIDATES[:rotation])
        flat_labels = pipeline.pipe._process_labels(label_input)
        if not isinstance(flat_labels, list) or len(flat_labels) != len(CANDIDATES):
            raise RuntimeError(f"unexpected flattened labels for {format_id}")
        prepared_text = pipeline.pipe.prepare_input(text, flat_labels)
        encoded_untruncated = tokenizer(prepared_text, truncation=False, add_special_tokens=True)["input_ids"]
        tokenized_inputs = pipeline.pipe.prepare_inputs([text], flat_labels, same_labels=True)
        token_ids = tokenized_inputs["input_ids"][0].detach().cpu().tolist()
        token_count = int(tokenized_inputs["attention_mask"][0].sum().item())
        truncated = len(encoded_untruncated) > pipeline.pipe.max_length

        hook_values.clear()
        started = time.perf_counter()
        returned = pipeline(text, label_input, batch_size=1, classification_type="single-label", return_hierarchical=True)[0]
        elapsed = time.perf_counter() - started
        if not hook_values:
            raise RuntimeError("model forward hook did not capture logits")
        model_output = hook_values[-1]
        logits_tensor = getattr(model_output, "logits", None)
        if logits_tensor is None:
            raise RuntimeError(f"unexpected model output type: {type(model_output)!r}")
        logits = logits_tensor[0, : len(flat_labels)].detach().cpu().to(torch.float64)
        probabilities = torch.softmax(logits, dim=-1)
        model_probabilities = [float(value) for value in probabilities.tolist()]
        id_by_text = {candidate.name: candidate.id for candidate in CANDIDATES}
        id_by_text.update({f"{candidate.name}: {candidate.description}": candidate.id for candidate in CANDIDATES})
        id_by_label = {}
        for label, value in zip(flat_labels, ordered_values, strict=True):
            prefix = "incident." if format_id.startswith(("B-", "D-")) else ""
            expected_flat = f"{prefix}{value}"
            if label != expected_flat:
                raise RuntimeError(f"unexpected flattening: {label!r} != {expected_flat!r}")
            id_by_label[label] = id_by_text[value]
        canonical_scores = {id_by_label[label]: score for label, score in zip(flat_labels, model_probabilities, strict=True)}
        selected = max(canonical_scores, key=canonical_scores.get)
        returned_flat = flatten_output(returned)
        returned_scores = {}
        for label, class_id in id_by_label.items():
            if label not in returned_flat:
                raise RuntimeError(f"pipeline output is missing flattened label {label!r}: {returned_flat!r}")
            returned_scores[class_id] = returned_flat[label]
        max_probability_delta = max(abs(canonical_scores[key] - returned_scores[key]) for key in canonical_scores)
        raw_selected_label = flat_labels[int(torch.argmax(logits).item())]

        return {
            "group": group, "case_id": case_id, "expected_label": expected_label,
            "format_id": format_id, "order_id": f"cyclic-rotation-{rotation}", "rotation": rotation,
            "input_text": text, "ordered_candidates_sent": ordered_values,
            "ordered_candidate_spec": [{"id": candidate.id, "name": candidate.name, "description": candidate.description, "model_text": model_text} for candidate, model_text in zip(ordered_specs, ordered_values, strict=True)],
            "label_input_structure": label_input, "flattened_label_strings": flat_labels,
            "prepared_model_input_text": prepared_text,
            "tokenized_length": token_count, "untruncated_tokenized_length": len(encoded_untruncated),
            "truncated": truncated, "label_marker_literal_count": prepared_text.count("<<LABEL>>"),
            "label_marker_token_count": label_marker_occurrences(token_ids, marker_ids),
            "label_marker_token_ids": marker_ids, "raw_logits_by_flat_label": dict(zip(flat_labels, [float(value) for value in logits.tolist()], strict=True)),
            "softmax_by_flat_label": dict(zip(flat_labels, model_probabilities, strict=True)),
            "canonical_scores": canonical_scores, "canonical_prediction": selected,
            "pipeline_returned_structure": returned, "pipeline_returned_scores_by_canonical_id": returned_scores,
            "raw_argmax_label": raw_selected_label, "raw_argmax_canonical_id": id_by_label[raw_selected_label],
            "maximum_probability_difference_pipeline_vs_logits": max_probability_delta,
            "inference_seconds": elapsed,
        }

    for format_id in FORMAT_IDS:
        for rotation in range(len(CANDIDATES)):
            for case in selected_cases:
                calls.append(evaluate(case["text"], case["id"], case["expected_label"], format_id, rotation, "preselected_core"))
            for case_id, text, expected in ANCHORS:
                calls.append(evaluate(text, case_id, expected, format_id, rotation, "smoke_anchor"))
    hook.remove()

    format_summary = {}
    relevant = [call for call in calls if call["group"] == "preselected_core"]
    anchors = [call for call in calls if call["group"] == "smoke_anchor"]
    for format_id in FORMAT_IDS:
        rows = [row for row in relevant if row["format_id"] == format_id]
        counts = {label: {"correct": 0, "total": 0} for label in (candidate.id for candidate in CANDIDATES)}
        for row in rows:
            counts[row["expected_label"]]["total"] += 1
            counts[row["expected_label"]]["correct"] += row["canonical_prediction"] == row["expected_label"]
        per_case = {}
        for case_id in FIXED_CASE_IDS:
            case_rows = [row for row in rows if row["case_id"] == case_id]
            unique = sorted({row["canonical_prediction"] for row in case_rows})
            per_case[case_id] = {"unique_predictions_across_orders": unique, "order_sensitive": len(unique) > 1}
        format_summary[format_id] = {
            "preselected_core_correct": sum(row["canonical_prediction"] == row["expected_label"] for row in rows),
            "preselected_core_total": len(rows), "correct_by_expected_class": counts,
            "cases_order_sensitive": sum(value["order_sensitive"] for value in per_case.values()), "per_case_order_sensitivity": per_case,
            "mean_probability_delta_from_order_zero": _mean_order_delta(rows),
            "maximum_pipeline_softmax_difference": max(row["maximum_probability_difference_pipeline_vs_logits"] for row in rows),
        }
    anchor_summary = {}
    for case_id, _text, expected in ANCHORS:
        rows = [row for row in anchors if row["case_id"] == case_id]
        anchor_summary[case_id] = {
            "expected_label": expected,
            "correct_by_format_and_order": {row["format_id"]: row["canonical_prediction"] == expected for row in rows if row["rotation"] == 0},
            "predictions_by_format_order": {row["format_id"]: [next(row2["canonical_prediction"] for row2 in rows if row2["format_id"] == row["format_id"] and row2["rotation"] == rotation) for rotation in range(4)] for row in rows if row["rotation"] == 0},
        }

    diagnostic_path = Path(__file__)
    package_versions = {}
    for distribution in ("gliclass", "transformers", "torch", "tokenizers", "huggingface-hub"):
        package_versions[distribution] = importlib.metadata.version(distribution)
    code_files = [
        Path(importlib.import_module("gliclass.pipeline").__file__), Path(importlib.import_module("gliclass.model").__file__),
        Path(importlib.import_module("gliclass.data_processing").__file__), diagnostic_path,
        ROOT / "decisionops" / "backends.py", ROOT / "decisionops" / "__init__.py",
    ]
    weight_path = model_path / "model.safetensors"
    provenance = {
        "git_head": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
        "code_sha256": {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): sha256(path) for path in code_files},
        "dataset_sha256": sha256(DEFAULT_DATASET), "checkpoint_repository": repository,
        "checkpoint_revision": revision, "checkpoint_weight_file": {"path": str(weight_path), "size_bytes": weight_path.stat().st_size},
        "package_versions": package_versions, "python": platform.python_version(),
        "runtime": {"platform": platform.platform(), "device": "cpu", "pytorch_threads": torch.get_num_threads(), "batch_size": 1, "offline": os.environ.get("HF_HUB_OFFLINE")},
        "model_config": {key: getattr(config, key, None) for key in ("model_type", "architecture_type", "prompt_first", "max_labels_alloc", "max_num_classes")},
        "pipeline": {"class": f"{type(pipeline.pipe).__module__}.{type(pipeline.pipe).__name__}", "max_length": pipeline.pipe.max_length, "label_separator": pipeline.label_separator, "example_token": pipeline.pipe.example_token, "label_token": pipeline.pipe.label_token, "sep_token": pipeline.pipe.sep_token},
        "model_load_seconds": load_seconds,
    }
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(), "provenance": provenance,
        "canonical_candidate_spec": [{"id": candidate.id, "name": candidate.name, "description": candidate.description} for candidate in CANDIDATES],
        "preselected_case_ids": list(FIXED_CASE_IDS), "preselected_cases_expected": {case["id"]: case["expected_label"] for case in selected_cases},
        "experiment_design": {"format_ids": list(FORMAT_IDS), "candidate_order_ids": [f"cyclic-rotation-{i}" for i in range(4)], "candidate_count": len(CANDIDATES), "calls": len(calls), "same_checkpoint_loaded_once": True},
        "format_summary": format_summary, "anchor_summary": anchor_summary, "calls": calls,
    }


def _mean_order_delta(rows: list[dict]) -> float:
    by_case = {}
    for row in rows:
        by_case.setdefault(row["case_id"], {})[row["rotation"]] = row["canonical_scores"]
    deltas = []
    for rotations in by_case.values():
        base = rotations[0]
        for rotation, scores in rotations.items():
            if rotation:
                deltas.append(sum(abs(base[label] - scores[label]) for label in base) / len(base))
    return sum(deltas) / len(deltas) if deltas else 0.0


def main() -> int:
    report = run()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "diagnostic.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"report_dir": str(REPORT_DIR), "provenance": report["provenance"], "format_summary": report["format_summary"], "anchor_summary": report["anchor_summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
