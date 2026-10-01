"""Command-line entry point."""

import argparse
import json
import math
import sys
from pathlib import Path

from .runner import DEFAULT_DATASET, DEFAULT_PINS, evaluate_all, evaluate_worker


def _positive_finite_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite positive number of seconds") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number of seconds")
    return seconds


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline incident-classification development evaluation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate", help="run one backend or all backends sequentially")
    evaluate.add_argument("--backend", choices=("rules", "gliclass", "laya", "all"), required=True)
    evaluate.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    evaluate.add_argument("--output-dir", type=Path, default=Path("runs/latest"))
    evaluate.add_argument("--revision-file", type=Path, default=DEFAULT_PINS)
    evaluate.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    workflow = subparsers.add_parser("workflow", help="run the offline recorded-observation diagnostic workflow")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    episode = workflow_commands.add_parser("episode", help="run one bounded synthetic episode")
    episode.add_argument("--scenario-id", required=True)
    episode.add_argument("--policy", choices=("fixed_order", "rules", "gliclass", "gliclass_evidence_masked", "laya", "laya_evidence_masked"), default="rules")
    episode.add_argument("--trace-file", type=Path, default=Path("runs/workflow-episode.jsonl"))
    episode.add_argument("--scenario-file", type=Path)
    episode.add_argument("--revision-file", type=Path)
    episode.add_argument("--max-tool-calls", type=int, default=4)
    episode.add_argument("--max-decisions", type=int, default=6)
    workflow_eval = workflow_commands.add_parser("evaluate", help="compare all workflow policies over the frozen scenario suite")
    workflow_eval.add_argument("--scenario-file", type=Path)
    workflow_eval.add_argument("--output-dir", type=Path)
    workflow_eval.add_argument("--revision-file", type=Path)
    workflow_eval.add_argument("--split", choices=("development", "all"), default="all", help="run development only or both development and evaluation splits")
    workflow_eval.add_argument("--worker-timeout-seconds", type=_positive_finite_seconds, default=600.0,
                               help="deadline for each model-family worker, including model loading and both variants (default: 600 seconds)")
    replay = workflow_commands.add_parser("replay", help="validate and reconstruct a JSONL workflow trace")
    replay.add_argument("--trace-file", type=Path, required=True)
    html_report = workflow_commands.add_parser("export-html", help="export an existing workflow report as a standalone offline HTML viewer")
    html_report.add_argument("--report-dir", type=Path, required=True, help="completed report directory containing summaries and traces")
    html_report.add_argument("--output", type=Path, required=True, help="HTML output path outside the report directory")
    coverage_audit = workflow_commands.add_parser("audit-coverage", help="audit investigation coverage from an existing replayable workflow report")
    coverage_audit.add_argument("--report-dir", type=Path, required=True, help="completed six-policy workflow report to audit")
    coverage_audit.add_argument("--scenario-file", type=Path, help="scenario source whose SHA-256 must match report provenance")
    coverage_audit.add_argument("--output-dir", type=Path, required=True, help="new directory for JSON and Markdown audit outputs")
    args = parser.parse_args(argv)
    if args.command == "workflow":
        if args.workflow_command == "export-html":
            from .workflow_report import ReportLoadError, export_report

            try:
                output = export_report(args.report_dir, args.output)
            except (OSError, ReportLoadError) as exc:
                parser.error(str(exc))
            print(f"Wrote standalone offline workflow viewer to {output}")
            return 0
        if args.workflow_command == "audit-coverage":
            from .workflow_audit import CoverageAuditError, audit_report
            from .workflow_scenarios import SCENARIO_FILE

            try:
                json_path, markdown_path = audit_report(
                    args.report_dir, args.output_dir, args.scenario_file or SCENARIO_FILE,
                )
            except (CoverageAuditError, OSError) as exc:
                parser.error(str(exc))
            print(f"Wrote investigation coverage audit JSON to {json_path}")
            print(f"Wrote investigation coverage report to {markdown_path}")
            return 0
        from .workflow import replay_trace
        from .workflow_eval import DEFAULT_OUTPUT_DIR, DEFAULT_PINS as WORKFLOW_PINS, run_one_episode, evaluate_suite, WorkflowEvaluationError
        from .workflow_scenarios import SCENARIO_FILE

        if args.workflow_command == "episode":
            scenario_file = args.scenario_file or SCENARIO_FILE
            revision_file = args.revision_file or WORKFLOW_PINS
            scenario, result = run_one_episode(
                args.scenario_id, args.policy, scenario_path=scenario_file, pin_path=revision_file,
                max_tool_calls=args.max_tool_calls, max_decisions=args.max_decisions,
            )
            args.trace_file.parent.mkdir(parents=True, exist_ok=True)
            args.trace_file.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in result.trace), encoding="utf-8")
            print(json.dumps({
                "episode_id": result.episode_id, "scenario_id": scenario.scenario_id, "split": scenario.split,
                "gold_terminal_action": scenario.gold_terminal_action, "policy": args.policy,
                "terminal_action": result.terminal_action, "terminal_reason": result.terminal_reason,
                "cited_evidence_ids": result.cited_evidence_ids, "tool_call_count": result.tool_call_count,
                "decision_count": result.decision_count, "end_to_end_seconds": result.end_to_end_seconds,
                "trace_file": str(args.trace_file),
            }, indent=2))
            return 0
        if args.workflow_command == "evaluate":
            try:
                report = evaluate_suite(args.scenario_file or SCENARIO_FILE, args.output_dir or DEFAULT_OUTPUT_DIR,
                                        args.revision_file or WORKFLOW_PINS, split=args.split,
                                        worker_timeout_seconds=args.worker_timeout_seconds)
            except WorkflowEvaluationError as exc:
                print(str(exc), file=sys.stderr)
                return exc.exit_code
            print(f"Wrote workflow comparison to {args.output_dir or DEFAULT_OUTPUT_DIR}")
            print(json.dumps({name: policies["metrics_by_split"] for name, policies in report["policies"].items()}, indent=2))
            return 0
        events = [json.loads(line) for line in args.trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(json.dumps(replay_trace(events), indent=2))
        return 0
    if args.backend == "all":
        if args.worker:
            parser.error("--worker cannot be used with --backend all")
        return evaluate_all(args.dataset, args.output_dir, args.revision_file)
    summary = evaluate_worker(args.backend, args.dataset, args.output_dir, args.revision_file)
    print(f"{args.backend}: accuracy={summary['metrics_unambiguous']['accuracy']} coverage={summary['metrics_unambiguous']['coverage']}")
    print(f"Wrote predictions and summary to {args.output_dir}")
    return 0
