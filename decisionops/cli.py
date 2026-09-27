"""Command-line entry point."""

import argparse
from pathlib import Path

from .runner import DEFAULT_DATASET, DEFAULT_PINS, evaluate_all, evaluate_worker


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline incident-classification development evaluation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate", help="run one backend or all backends sequentially")
    evaluate.add_argument("--backend", choices=("rules", "gliclass", "laya", "all"), required=True)
    evaluate.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    evaluate.add_argument("--output-dir", type=Path, default=Path("runs/latest"))
    evaluate.add_argument("--revision-file", type=Path, default=DEFAULT_PINS)
    evaluate.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.backend == "all":
        if args.worker:
            parser.error("--worker cannot be used with --backend all")
        return evaluate_all(args.dataset, args.output_dir, args.revision_file)
    summary = evaluate_worker(args.backend, args.dataset, args.output_dir, args.revision_file)
    print(f"{args.backend}: accuracy={summary['metrics_unambiguous']['accuracy']} coverage={summary['metrics_unambiguous']['coverage']}")
    print(f"Wrote predictions and summary to {args.output_dir}")
    return 0
