"""Isolated CPU worker for one workflow model family."""

import argparse
from pathlib import Path

from .workflow_eval import _json_write, evaluate_model_family


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-family", choices=("gliclass", "laya"), required=True)
    parser.add_argument("--split", choices=("development", "all"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scenario-file", type=Path, required=True)
    parser.add_argument("--revision-file", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate_model_family(args.model_family, args.scenario_file, args.output_dir, args.revision_file, args.split)
    _json_write(args.output_dir / "worker-summary.json", result)
    print(f"Completed isolated {args.model_family} workflow worker", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
