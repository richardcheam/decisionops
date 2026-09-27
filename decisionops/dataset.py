"""JSONL loading and validation for the hand-authored development set."""

import json
from pathlib import Path
from typing import Any

from . import LABELS


def validate_dataset(cases: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    for index, case in enumerate(cases, 1):
        required = {"id", "text", "tags", "expected_label", "needs_review", "rationale"}
        if not isinstance(case, dict) or not required <= case.keys():
            raise ValueError(f"case {index}: missing required fields")
        if not isinstance(case["id"], str) or not case["id"].strip() or case["id"] in ids:
            raise ValueError(f"case {index}: ID must be unique and non-empty")
        ids.add(case["id"])
        if not isinstance(case["text"], str) or not case["text"].strip():
            raise ValueError(f"{case['id']}: text must be non-empty")
        if not isinstance(case["tags"], list) or not all(isinstance(tag, str) for tag in case["tags"]):
            raise ValueError(f"{case['id']}: tags must be a list of strings")
        if not isinstance(case["needs_review"], bool) or not isinstance(case["rationale"], str) or not case["rationale"].strip():
            raise ValueError(f"{case['id']}: review flag and rationale are required")
        label = case["expected_label"]
        if case["needs_review"]:
            if label is not None:
                raise ValueError(f"{case['id']}: review cases must not force a label")
        elif label not in LABELS:
            raise ValueError(f"{case['id']}: expected label must be one of {LABELS}")


def load_dataset(path: Path) -> list[dict[str, Any]]:
    cases = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    validate_dataset(cases)
    return cases
