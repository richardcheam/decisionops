"""Sequential scenario evaluation, replayable traces, and provenance reports."""

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
from typing import Any

from .backends import GLiClassActionRanker, REPOSITORIES, parse_revision_pins
from .workflow import EpisodeResult, run_episode
from .workflow_policies import FixedOrderPolicy, GLiClassPolicy, RulesPolicy
from .workflow_scenarios import SCENARIO_FILE, Scenario, load_scenarios

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "diagnostic-workflow-20260927"
DEFAULT_PINS = ROOT / "model-revisions.env"
POLICY_NAMES = ("fixed_order", "rules", "gliclass")
WORKFLOW_CODE_FILES = (
    ROOT / "decisionops" / "workflow.py", ROOT / "decisionops" / "workflow_eval.py",
    ROOT / "decisionops" / "workflow_policies.py", ROOT / "decisionops" / "workflow_scenarios.py",
    ROOT / "decisionops" / "backends.py", ROOT / "decisionops" / "cli.py",
    ROOT / "data" / "build_workflow_scenarios.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _package_versions() -> dict[str, str | None]:
    names = ("torch", "transformers", "gliclass", "huggingface-hub")
    versions = {"decisionops": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _peak_rss_bytes() -> int | None:
    if sys.platform != "linux":
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = int(position), int(position + 0.999999999)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (position - low)


def _assertion_matches(observations: tuple[dict[str, Any], ...], assertion: dict[str, Any]) -> str | None:
    for observation in observations:
        if observation["tool_name"] != assertion["tool_name"] or observation["status"] != "success" or observation["time_scope"] != assertion["time_scope"]:
            continue
        if assertion["fact"] in observation["facts"] and observation["facts"][assertion["fact"]] == assertion["equals"]:
            return observation["observation_id"]
    return None


def has_acceptable_gold_evidence(scenario: Scenario, result: EpisodeResult) -> bool:
    if not scenario.acceptable_evidence:
        return scenario.gold_terminal_action == "request_review"
    if not result.cited_evidence_ids:
        return False
    cited = set(result.cited_evidence_ids)
    return any(
        all((obs_id := _assertion_matches(result.observations, assertion)) is not None and obs_id in cited for assertion in alternative)
        for alternative in scenario.acceptable_evidence
    )


def summarize_results(scenarios: list[Scenario], results: list[EpisodeResult]) -> dict[str, Any]:
    if len(scenarios) != len(results):
        raise ValueError("scenario and episode result counts differ")
    diagnosable = [index for index, scenario in enumerate(scenarios) if scenario.gold_terminal_action != "request_review"]
    review_required = [index for index, scenario in enumerate(scenarios) if scenario.gold_terminal_action == "request_review"]
    supported_correct = sum(
        results[index].terminal_action == scenarios[index].gold_terminal_action
        and results[index].terminal_reason == "completed"
        and has_acceptable_gold_evidence(scenarios[index], results[index])
        for index in diagnosable
    )
    correct_review = sum(results[index].terminal_action == "request_review" and results[index].terminal_reason == "review" for index in review_required)
    incorrect = sum(
        result.terminal_action in {"diagnose_database_failure", "diagnose_authentication_failure", "diagnose_disk_full", "diagnose_healthy"}
        and result.terminal_action != scenario.gold_terminal_action
        for scenario, result in zip(scenarios, results, strict=True)
    )
    latencies = [result.end_to_end_seconds for result in results]
    calls = [result.tool_call_count for result in results]
    return {
        "scenario_count": len(scenarios), "diagnosable_count": len(diagnosable), "review_required_count": len(review_required),
        "correct_supported_diagnoses": supported_correct,
        "correct_supported_diagnosis_rate": supported_correct / len(diagnosable) if diagnosable else None,
        "correct_review_decisions": correct_review,
        "correct_review_decision_rate": correct_review / len(review_required) if review_required else None,
        "incorrect_diagnoses": incorrect,
        "unnecessary_review_on_diagnosable_cases": sum(results[index].terminal_action == "request_review" for index in diagnosable),
        "unsupported_diagnosis_proposals": sum(result.unsupported_diagnosis_proposals for result in results),
        "invalid_proposals_rejected": sum(result.invalid_proposals_rejected for result in results),
        "policy_execution_errors": sum(
            event["acceptance"]["reason"] == "policy_execution_error"
            for result in results for event in result.trace
        ),
        "budget_exhaustion_episodes": sum(result.terminal_reason == "exhausted_budget" for result in results),
        "tool_related_failures": sum(result.terminal_reason == "tool_failure" for result in results),
        "simulator_failures": sum(result.simulator_failure for result in results),
        "tool_calls": {"total": sum(calls), "per_episode_mean": sum(calls) / len(calls) if calls else None},
        "end_to_end_latency_seconds": {"sample_count": len(latencies), "mean": sum(latencies) / len(latencies) if latencies else None,
                                       "p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
    }


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _trace_text(events: tuple[dict[str, Any], ...]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _evaluate_policy(name: str, scenarios: list[Scenario], policy, output_dir: Path) -> tuple[dict[str, Any], list[EpisodeResult], list[dict[str, Any]]]:
    trace_dir = output_dir / "traces" / name
    trace_dir.mkdir(parents=True, exist_ok=True)
    for old in trace_dir.glob("*.jsonl"):
        old.unlink()
    results, episode_rows = [], []
    for index, scenario in enumerate(scenarios, 1):
        split_order = sum(1 for prior in scenarios[:index - 1] if prior.split == scenario.split) + 1
        episode_id = f"{scenario.split[:3]}-{split_order:03d}"
        result = run_episode(scenario, policy, episode_id=episode_id)
        trace_path = trace_dir / f"{episode_id}.jsonl"
        trace_path.write_text(_trace_text(result.trace), encoding="utf-8")
        results.append(result)
        supported = has_acceptable_gold_evidence(scenario, result) if result.terminal_action == scenario.gold_terminal_action else False
        episode_rows.append({
            "episode_id": episode_id, "scenario_id": scenario.scenario_id, "split": scenario.split,
            "gold_terminal_action": scenario.gold_terminal_action, "terminal_action": result.terminal_action,
            "terminal_reason": result.terminal_reason, "gold_evidence_supported": supported,
            "tool_call_count": result.tool_call_count, "decision_count": result.decision_count,
            "end_to_end_seconds": result.end_to_end_seconds, "trace": str(trace_path.relative_to(output_dir)),
        })
    grouped = {}
    for split in ("development", "evaluation"):
        indexes = [index for index, scenario in enumerate(scenarios) if scenario.split == split]
        grouped[split] = summarize_results([scenarios[index] for index in indexes], [results[index] for index in indexes])
    summary = {
        "policy": name, "model_loading_seconds": float(getattr(policy, "load_seconds", 0.0)),
        "peak_process_rss_bytes": _peak_rss_bytes(), "metrics_by_split": grouped,
        "episodes": episode_rows,
    }
    _json_write(output_dir / f"{name}-summary.json", summary)
    return summary, results, episode_rows


def _provenance(scenario_path: Path, pin_path: Path) -> dict[str, Any]:
    revisions = parse_revision_pins(pin_path)
    implementation = {str(path.relative_to(ROOT)): _sha256(path) for path in WORKFLOW_CODE_FILES}
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False)
    dirty_paths = status.stdout.rstrip("\n").splitlines() if status.returncode == 0 else []
    try:
        python_packages = {"python": platform.python_version(), "platform": platform.platform(), "pytorch_threads": 4, "batch_size": 1, "device": "cpu", "offline": os.environ.get("HF_HUB_OFFLINE")}
    except Exception:
        python_packages = {}
    return {
        "git_head": _git("rev-parse", "HEAD"), "git_dirty": bool(dirty_paths), "git_dirty_paths": [line[3:] for line in dirty_paths],
        "implementation_sha256": implementation, "scenario_file": str(scenario_path.resolve()), "scenario_sha256": _sha256(scenario_path),
        "package_versions": _package_versions(), "runtime": python_packages,
        "model_repository": REPOSITORIES["gliclass"][0], "model_revision": revisions[REPOSITORIES["gliclass"][1]],
        "action_candidate_representation": [{"id": action_id, "model_name": name} for action_id, name in __import__("decisionops.workflow", fromlist=["ACTION_NAMES"]).ACTION_NAMES.items()],
        "policy_order": list(POLICY_NAMES), "max_tool_calls": 4, "max_decisions": 6,
        "split_counts": {split: 12 for split in ("development", "evaluation")},
    }


def evaluate_suite(scenario_path: Path = SCENARIO_FILE, output_dir: Path = DEFAULT_OUTPUT_DIR, pin_path: Path = DEFAULT_PINS) -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    scenarios = load_scenarios(scenario_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("all-summary.json", "all-summary.md", "provenance.json"):
        (output_dir / name).unlink(missing_ok=True)
    all_summaries = {}
    policies = {"fixed_order": FixedOrderPolicy(), "rules": RulesPolicy()}
    for name in ("fixed_order", "rules"):
        all_summaries[name], _results, _episodes = _evaluate_policy(name, scenarios, policies[name], output_dir)
    ranker = GLiClassActionRanker(pin_path)
    ranker.load()
    gliclass_policy = GLiClassPolicy(ranker)
    all_summaries["gliclass"], _results, _episodes = _evaluate_policy("gliclass", scenarios, gliclass_policy, output_dir)
    provenance = _provenance(scenario_path, pin_path)
    provenance["model_loading_seconds"] = ranker.load_seconds
    _json_write(output_dir / "provenance.json", provenance)
    comparison = []
    for name in POLICY_NAMES:
        summary = all_summaries[name]
        for split, metrics in summary["metrics_by_split"].items():
            comparison.append({"policy": name, "split": split, **{key: metrics[key] for key in (
                "correct_supported_diagnoses", "diagnosable_count", "correct_review_decisions", "review_required_count",
                "incorrect_diagnoses", "unnecessary_review_on_diagnosable_cases", "unsupported_diagnosis_proposals",
                "invalid_proposals_rejected", "policy_execution_errors", "budget_exhaustion_episodes", "tool_related_failures",
                "tool_calls", "end_to_end_latency_seconds",
            )}, "model_loading_seconds": summary["model_loading_seconds"], "peak_process_rss_bytes": summary["peak_process_rss_bytes"]})
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "scenario_sha256": _sha256(scenario_path), "provenance": provenance, "policies": all_summaries, "comparison": comparison}
    _json_write(output_dir / "all-summary.json", result)
    _write_comparison_markdown(output_dir / "all-summary.md", result)
    _write_example_trace(output_dir, all_summaries)
    return result


def _write_example_trace(output_dir: Path, summaries: dict[str, Any]) -> None:
    trace_dir = output_dir / "examples"
    trace_dir.mkdir(parents=True, exist_ok=True)
    fixed = summaries["fixed_order"]["episodes"]
    episode = next(row for row in fixed if row["scenario_id"] == "dev-database-clear")
    source = output_dir / episode["trace"]
    (trace_dir / "fixed-order-database-example.jsonl").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _write_comparison_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Recorded diagnostic workflow evaluation", "",
        "> Offline synthetic simulation. Fixture tools return recorded observations; no shell command, live service, or host action is executed.", "",
        "| Policy | Split | Supported diagnoses | Correct reviews | Incorrect diagnoses | Unnecessary review | Unsupported diagnosis proposals | Invalid proposals | Policy errors | Budget exhausted | Tool failures | Tool calls mean | Latency p50 / p95 | Model load | Peak RSS |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["comparison"]:
        latency = row["end_to_end_latency_seconds"]
        lines.append(
            f"| {row['policy']} | {row['split']} | {row['correct_supported_diagnoses']}/{row['diagnosable_count']} | "
            f"{row['correct_review_decisions']}/{row['review_required_count']} | {row['incorrect_diagnoses']} | "
            f"{row['unnecessary_review_on_diagnosable_cases']} | {row['unsupported_diagnosis_proposals']} | "
            f"{row['invalid_proposals_rejected']} | {row['policy_execution_errors']} | {row['budget_exhaustion_episodes']} | {row['tool_related_failures']} | "
            f"{row['tool_calls']['per_episode_mean']:.2f} | {latency['p50'] * 1000:.1f} / {latency['p95'] * 1000:.1f} ms | "
            f"{row['model_loading_seconds']:.2f} s | {row['peak_process_rss_bytes']} bytes |"
        )
    lines += ["", "Diagnosable and review-required cases use separate denominators. Review-everything is therefore visible as unnecessary review and zero supported diagnoses. Policies received the same initial reports and could request only tools or terminal choices allowed by the harness. Tool fixture timeouts/errors are observations, not simulator failures.", "", "See `provenance.json` for code/scenario hashes, package versions, model pin, runtime, candidate order, and budgets. Each policy summary has episode outcomes; `traces/` contains one JSONL replay trace per episode. `examples/fixed-order-database-example.jsonl` is a compact example.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_one_episode(scenario_id: str, policy_name: str, scenario_path: Path = SCENARIO_FILE, pin_path: Path = DEFAULT_PINS,
                    max_tool_calls: int = 4, max_decisions: int = 6) -> tuple[Scenario, EpisodeResult]:
    scenarios = load_scenarios(scenario_path)
    scenario = next((item for item in scenarios if item.scenario_id == scenario_id), None)
    if scenario is None:
        raise ValueError(f"unknown scenario ID {scenario_id!r}")
    if policy_name == "fixed_order":
        policy = FixedOrderPolicy()
    elif policy_name == "rules":
        policy = RulesPolicy()
    elif policy_name == "gliclass":
        ranker = GLiClassActionRanker(pin_path)
        ranker.load()
        policy = GLiClassPolicy(ranker)
    else:
        raise ValueError(f"unknown policy {policy_name!r}")
    result = run_episode(scenario, policy, episode_id=f"{scenario.split[:3]}-one", max_tool_calls=max_tool_calls, max_decisions=max_decisions)
    return scenario, result
