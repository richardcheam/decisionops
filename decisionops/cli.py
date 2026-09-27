"""Command-line entry point."""

import argparse
import json
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
    workflow = subparsers.add_parser("workflow", help="run the offline recorded-observation diagnostic workflow")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    episode = workflow_commands.add_parser("episode", help="run one bounded synthetic episode")
    episode.add_argument("--scenario-id", required=True)
    episode.add_argument("--policy", choices=("fixed_order", "rules", "gliclass", "gliclass_evidence_masked"), default="rules")
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
    replay = workflow_commands.add_parser("replay", help="validate and reconstruct a JSONL workflow trace")
    replay.add_argument("--trace-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "workflow":
        from .workflow import replay_trace
        from .workflow_eval import DEFAULT_OUTPUT_DIR, DEFAULT_PINS as WORKFLOW_PINS, run_one_episode, evaluate_suite
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
            report = evaluate_suite(args.scenario_file or SCENARIO_FILE, args.output_dir or DEFAULT_OUTPUT_DIR,
                                    args.revision_file or WORKFLOW_PINS, split=args.split)
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
