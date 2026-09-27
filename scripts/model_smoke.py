"""Explicit offline model smoke test: run once per model in its own process."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["HF_HUB_OFFLINE"] = "1"

from decisionops.backends import Backend
from decisionops.runner import DEFAULT_PINS

CASES = [
    ("Database connections time out and requests fail.", "database_failure"),
    ("All health checks pass and the service is operating normally.", "healthy"),
    ("The disk is full and the service cannot write log files.", "disk_full"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a tiny local-only model smoke test")
    parser.add_argument("backend", choices=("gliclass", "laya"))
    parser.add_argument("--revision-file", type=Path, default=DEFAULT_PINS)
    args = parser.parse_args()
    backend = Backend(args.backend, args.revision_file)
    backend.load()
    backend.predict("Warm-up: all health checks pass.")
    results = []
    for text, expected in CASES:
        result = backend.predict(text)
        results.append({"expected": expected, "selected_class": result["selected_class"], "inference_seconds": result["inference_seconds"], "scores": result.get("scores"), "confidence": result.get("confidence"), "answer_confidence": result.get("answer_confidence"), "action_act_probability": result.get("action_act_probability")})
    correct = sum(row["selected_class"] == row["expected"] for row in results)
    print(json.dumps({"backend": args.backend, "api_status": "passed", "model_loading_seconds": backend.load_seconds, "warmup_calls_excluded": 1, "semantic_expectations": {"correct": correct, "total": len(results), "all_correct": correct == len(results)}, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
