"""Model-free investigation-coverage audit for committed workflow reports."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .workflow_report import POLICY_NAMES, ReportLoadError, load_report
from .workflow_scenarios import SCENARIO_FILE, TOOL_NAMES, load_scenarios


class CoverageAuditError(ValueError):
    """The report and scenario source cannot be safely joined for an audit."""


_DIAGNOSIS_CATEGORY = {
    "diagnose_database_failure": "database_failure",
    "diagnose_authentication_failure": "authentication_failure",
    "diagnose_disk_full": "disk_full",
}

# These structured facts are the same current-evidence signals used by
# workflow._area_evidence. Free-text fixture messages are deliberately ignored.
_FACT_RULES = {
    "check_database": (
        ("database_failure", "fault", "connection_success", False),
        ("database_failure", "fault", "timeout", True),
        ("database_failure", "counterevidence", "connection_success", True),
    ),
    "check_authentication": (
        ("authentication_failure", "fault", "authentication_success", False),
        ("authentication_failure", "fault", "credentials_rejected", True),
        ("authentication_failure", "counterevidence", "authentication_success", True),
        ("authentication_failure", "counterevidence", "credentials_rejected", False),
    ),
    "check_storage": (
        ("disk_full", "fault", "storage_exhausted", True),
        ("disk_full", "fault", "write_test_success", False),
        ("disk_full", "counterevidence", "storage_exhausted", False),
        ("disk_full", "counterevidence", "write_test_success", True),
    ),
    "check_service_health": (
        ("database_failure", "fault", "database_probe_success", False),
        ("database_failure", "counterevidence", "database_probe_success", True),
        ("authentication_failure", "fault", "authentication_probe_success", False),
        ("authentication_failure", "counterevidence", "authentication_probe_success", True),
        ("disk_full", "fault", "storage_probe_success", False),
        ("disk_full", "counterevidence", "storage_probe_success", True),
    ),
}

_OUTCOME_NAMES = (
    "correct_diagnoses", "incorrect_diagnoses", "reviews", "failed_episodes", "other_terminal_outcomes",
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _signals_for_fixture(tool_name: str, fixture: dict[str, Any]) -> list[dict[str, Any]]:
    if fixture.get("status") != "success" or fixture.get("time_scope") != "current":
        return []
    facts = fixture.get("facts", {})
    collected: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for category, kind, key, expected in _FACT_RULES[tool_name]:
        if key in facts and facts[key] is expected:
            collected.setdefault((category, kind), []).append({"fact": key, "equals": expected})
    return [
        {"fault_category": category, "signal": kind, "facts": matched}
        for (category, kind), matched in collected.items()
    ]


def _hindsight_annotations(scenario, unrequested_tools: set[str], terminal_action: str | None) -> dict[str, Any]:
    annotations = []
    terminal_category = _DIAGNOSIS_CATEGORY.get(terminal_action)
    for tool_name in TOOL_NAMES:
        if tool_name not in unrequested_tools:
            continue
        fixture = scenario.observations[tool_name]
        for signal in _signals_for_fixture(tool_name, fixture):
            category, kind = signal["fault_category"], signal["signal"]
            relationship = None
            if terminal_category is not None:
                if kind == "fault" and category != terminal_category:
                    relationship = "additional_fault"
                elif kind == "counterevidence" and category == terminal_category:
                    relationship = "contradicts_terminal_diagnosis"
            elif terminal_action == "diagnose_healthy":
                if kind == "fault":
                    relationship = "contradicts_terminal_diagnosis"
            elif terminal_action == "request_review" and scenario.gold_terminal_action == "request_review":
                if kind == "fault":
                    relationship = "additional_fault_supporting_evaluator_review"
            if relationship:
                annotations.append({
                    "tool_name": tool_name,
                    "status": fixture["status"],
                    "time_scope": fixture["time_scope"],
                    "fault_category": category,
                    "relationship": relationship,
                    "facts": signal["facts"],
                })
    return {
        "label": "Evaluator-only hindsight; these observations were not available to the policy.",
        "unrequested_structured_signals": annotations,
    }


def _episode_outcome(episode: dict[str, Any], terminal: dict[str, Any], gold_action: str) -> tuple[str, dict[str, bool]]:
    action, reason, status = terminal["action"], terminal["reason"], terminal["status"]
    diagnosis = isinstance(action, str) and action.startswith("diagnose_")
    is_correct_diagnosis = bool(
        diagnosis and action == gold_action and reason == "completed" and episode.get("gold_evidence_supported") is True
        and gold_action != "request_review"
    )
    is_incorrect_diagnosis = bool(diagnosis and action != gold_action)
    is_review = action == "request_review"
    is_failed = status == "failed"
    flags = {
        "correct_diagnosis": is_correct_diagnosis,
        "incorrect_diagnosis": is_incorrect_diagnosis,
        "review": is_review,
        "failed_episode": is_failed,
        "correct_review": bool(is_review and reason == "review" and gold_action == "request_review"),
        "unnecessary_review": bool(is_review and gold_action != "request_review"),
    }
    # These four requested outcomes are normally mutually exclusive. Keep
    # malformed or unusual terminal combinations visible under an explicit
    # residual rather than making the counts silently overlap.
    for key, name in (
        ("failed_episode", "failed_episodes"), ("review", "reviews"),
        ("correct_diagnosis", "correct_diagnoses"), ("incorrect_diagnosis", "incorrect_diagnoses"),
    ):
        if flags[key]:
            return name, flags
    return "other_terminal_outcomes", flags


def _trace_tool_data(events: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not events:
        raise CoverageAuditError("report contains an empty trace after replay validation")
    final_state = events[-1].get("visible_state_after")
    terminal = events[-1].get("terminal_decision")
    if not isinstance(final_state, dict) or not isinstance(terminal, dict):
        raise CoverageAuditError("replayed trace is missing its final state or terminal decision")
    attempted_set = set(final_state.get("actions_attempted", ()))
    attempted = [tool for tool in TOOL_NAMES if tool in attempted_set]
    returned: dict[str, dict[str, Any]] = {}
    for event in events:
        observation = event.get("tool_observation")
        if isinstance(observation, dict) and observation.get("tool_name") in TOOL_NAMES:
            returned[observation["tool_name"]] = observation
    successful_current = [
        tool for tool in TOOL_NAMES if tool in returned and returned[tool].get("status") == "success"
        and returned[tool].get("time_scope") == "current"
    ]
    historical = [tool for tool in TOOL_NAMES if tool in returned and returned[tool].get("time_scope") == "historical"]
    timeouts = [tool for tool in TOOL_NAMES if tool in returned and returned[tool].get("status") == "timeout"]
    errors = [tool for tool in TOOL_NAMES if tool in returned and returned[tool].get("status") == "error"]
    all_four = set(successful_current) == set(TOOL_NAMES)
    return ({
        "attempted": attempted,
        "never_attempted": [tool for tool in TOOL_NAMES if tool not in attempted_set],
        "successful_current_observations": successful_current,
        "historical_observations": historical,
        "timeout_observations": timeouts,
        "error_observations": errors,
        "all_four_current_success": all_four,
    }, {
        "action": terminal.get("action_id"), "reason": terminal.get("reason"),
        "status": terminal.get("status"),
    })


def _empty_group(all_four: bool) -> dict[str, Any]:
    return {
        "all_four_current_coverage": all_four,
        "episode_denominator": 0,
        "diagnosable_episode_denominator": 0,
        "classified_episode_count": 0,
        "outcomes": {
            name: {"count": 0, "denominator": 0, "rate": None}
            for name in _OUTCOME_NAMES
        },
        "correct_review_decisions": 0,
        "unnecessary_reviews_on_diagnosable_cases": 0,
    }


def build_coverage_audit(report_dir: Path | str, scenario_file: Path | str = SCENARIO_FILE) -> dict[str, Any]:
    """Replay and audit every trace in a completed six-policy comparison."""
    try:
        report_root = Path(report_dir).resolve(strict=True)
        report = load_report(report_root)  # Replays all summary-referenced traces before audit derivation.
    except (OSError, ReportLoadError) as exc:
        raise CoverageAuditError(str(exc)) from exc
    scenario_path = Path(scenario_file).resolve(strict=True)
    recorded_hash = report.get("provenance", {}).get("scenario_sha256")
    actual_hash = _source_hash(scenario_path)
    if not isinstance(recorded_hash, str) or actual_hash != recorded_hash:
        raise CoverageAuditError(
            f"scenario source SHA-256 mismatch: report records {recorded_hash!r}, "
            f"provided file hashes to {actual_hash}"
        )
    try:
        scenarios = load_scenarios(scenario_path)
    except (OSError, ValueError) as exc:
        raise CoverageAuditError(f"cannot load matching scenario source: {exc}") from exc
    scenario_index = {(scenario.split, scenario.scenario_id): scenario for scenario in scenarios}

    audit_episodes: list[dict[str, Any]] = []
    grouped: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
        policy: {split: {"partial": _empty_group(False), "all_four": _empty_group(True)}
                for split in report["policies"][policy]["metrics_by_split"]}
        for policy in POLICY_NAMES
    }
    source_episodes: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for policy in POLICY_NAMES:
        summary_path = report_root / f"{policy}-summary.json"
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CoverageAuditError(f"cannot read {summary_path.name}: {exc}") from exc
        source_episodes[policy] = {(row["split"], row["scenario_id"]): row for row in summary["episodes"]}

    for policy in POLICY_NAMES:
        for split, by_scenario in report["policies"][policy]["episodes"].items():
            for scenario_id, loaded in by_scenario.items():
                key = (split, scenario_id)
                scenario = scenario_index.get(key)
                if scenario is None:
                    raise CoverageAuditError(f"no matching scenario fixture for {split}/{scenario_id}")
                episode = source_episodes[policy].get(key)
                evaluator = report["evaluator"][split][scenario_id]
                if episode is None or policy not in evaluator["policy_outcomes"]:
                    raise CoverageAuditError(f"missing evaluator outcome or episode row for {policy}/{split}/{scenario_id}")
                tools, terminal = _trace_tool_data(loaded["events"])
                outcome, outcome_flags = _episode_outcome(
                    {"gold_evidence_supported": evaluator["policy_outcomes"][policy]["gold_evidence_supported"]},
                    terminal, evaluator["gold"]["gold_terminal_action"],
                )
                coverage_key = "all_four" if tools["all_four_current_success"] else "partial"
                group = grouped[policy][split][coverage_key]
                group["episode_denominator"] += 1
                group["classified_episode_count"] += 1
                group["outcomes"][outcome]["count"] += 1
                if evaluator["gold"]["gold_terminal_action"] != "request_review":
                    group["diagnosable_episode_denominator"] += 1
                if outcome_flags["correct_review"]:
                    group["correct_review_decisions"] += 1
                if outcome_flags["unnecessary_review"]:
                    group["unnecessary_reviews_on_diagnosable_cases"] += 1

                state = loaded["events"][-1]["visible_state_after"]
                audit_episodes.append({
                    "policy": policy, "split": split, "scenario_id": scenario_id,
                    "episode_id": loaded["episode_id"], "trace": episode["trace"],
                    "terminal": terminal,
                    "tools": tools,
                    "ended_with_diagnosis_or_review": bool(
                        terminal["action"] == "request_review"
                        or (isinstance(terminal["action"], str) and terminal["action"].startswith("diagnose_"))
                    ),
                    "evaluator_outcome": outcome,
                    "evaluator_outcome_flags": outcome_flags,
                    "policy_visible_evidence": {
                        "initial_report": state.get("initial_report"),
                        "observations": state.get("observations", []),
                        "actions_attempted": state.get("actions_attempted", []),
                        "remaining_tool_calls": state.get("remaining_tool_calls"),
                        "remaining_decisions": state.get("remaining_decisions"),
                    },
                    "evaluator_only_hindsight": _hindsight_annotations(
                        scenario, set(tools["never_attempted"]), terminal["action"],
                    ),
                })

    for policy, splits in grouped.items():
        for split, coverages in splits.items():
            for group in coverages.values():
                denominator = group["episode_denominator"]
                for name, metric in group["outcomes"].items():
                    metric["denominator"] = (
                        group["diagnosable_episode_denominator"] if name == "correct_diagnoses" else denominator
                    )
                    metric["rate"] = metric["count"] / metric["denominator"] if metric["denominator"] else None

            # Confirm the audit's per-episode join preserves the historical aggregate metric definitions.
            metrics = report["policies"][policy]["metrics_by_split"][split]
            total = lambda name: sum(c["outcomes"][name]["count"] for c in coverages.values())
            expected = {
                "correct_diagnoses": metrics["correct_supported_diagnoses"],
                "incorrect_diagnoses": metrics["incorrect_diagnoses"],
                "failed_episodes": metrics["failed_episodes"],
                "reviews": metrics["terminal_status_counts"]["review"],
                "correct_review_decisions": metrics["correct_review_decisions"],
                "unnecessary_reviews_on_diagnosable_cases": metrics["unnecessary_review_on_diagnosable_cases"],
            }
            for name, value in expected.items():
                observed = (
                    sum(c["correct_review_decisions"] for c in coverages.values())
                    if name == "correct_review_decisions" else
                    sum(c["unnecessary_reviews_on_diagnosable_cases"] for c in coverages.values())
                    if name == "unnecessary_reviews_on_diagnosable_cases" else total(name)
                )
                if observed != value:
                    raise CoverageAuditError(
                        f"{policy} {split} {name} per-episode join ({observed}) disagrees with report metric ({value})"
                    )
            if sum(c["diagnosable_episode_denominator"] for c in coverages.values()) != metrics["diagnosable_count"]:
                raise CoverageAuditError(f"{policy} {split} diagnosable denominator disagrees with the policy summary")
            for coverage_name, group in coverages.items():
                selected_outcome_count = sum(bucket["count"] for bucket in group["outcomes"].values())
                if selected_outcome_count != group["episode_denominator"]:
                    raise CoverageAuditError(
                        f"{policy} {split} {coverage_name} outcome buckets ({selected_outcome_count}) "
                        f"do not equal the episode denominator ({group['episode_denominator']})"
                    )
                if group["classified_episode_count"] != group["episode_denominator"]:
                    raise CoverageAuditError(
                        f"{policy} {split} {coverage_name} classified count disagrees with its episode denominator"
                    )

    audit_episodes.sort(key=lambda row: (row["split"], row["scenario_id"], POLICY_NAMES.index(row["policy"])))
    partial = [row for row in audit_episodes if not row["tools"]["all_four_current_success"]]
    partial_incorrect = sum(row["evaluator_outcome"] == "incorrect_diagnoses" for row in partial)
    outcome_counts = {
        name: sum(row["evaluator_outcome"] == name for row in audit_episodes)
        for name in _OUTCOME_NAMES
    }
    classified_episode_count = sum(outcome_counts.values())
    if classified_episode_count != len(audit_episodes):
        raise CoverageAuditError("top-level evaluator outcome buckets do not account for every policy episode")
    summary = {
        "policy_episode_count": len(audit_episodes),
        "classified_episode_count": classified_episode_count,
        "outcome_counts": outcome_counts,
        "incomplete_coverage_episode_count": len(partial),
        "incomplete_coverage_incorrect_diagnosis_count": partial_incorrect,
        "incomplete_coverage_correct_diagnosis_count": sum(row["evaluator_outcome"] == "correct_diagnoses" for row in partial),
        "incomplete_coverage_review_count": sum(row["evaluator_outcome"] == "reviews" for row in partial),
        "incomplete_coverage_failed_episode_count": sum(row["evaluator_outcome"] == "failed_episodes" for row in partial),
        "incomplete_coverage_other_terminal_outcome_count": sum(row["evaluator_outcome"] == "other_terminal_outcomes" for row in partial),
        "stricter_stopping_rule_study": "justified_as_a_separate_question" if partial_incorrect else "not_indicated_by_coverage_counts_alone",
    }
    try:
        source_report = str(report_root.relative_to(_REPOSITORY_ROOT))
    except ValueError:
        source_report = str(report_root)
    try:
        source_scenarios = str(scenario_path.relative_to(_REPOSITORY_ROOT))
    except ValueError:
        source_scenarios = str(scenario_path)
    return {
        "audit_version": 1,
        "source_report": source_report,
        "scenario_file": source_scenarios,
        "scenario_sha256": actual_hash,
        "trace_replay": {"status": "passed", "referenced_trace_count": len(audit_episodes)},
        "episode_count": len(audit_episodes),
        "summary": summary,
        "policies": grouped,
        "episodes": audit_episodes,
    }


def _markdown(audit: dict[str, Any], report_root: Path, output_dir: Path) -> str:
    lines = [
        "# Investigation coverage audit", "",
        "**Offline, model-free audit of the committed synthetic comparison.** "
        "Coverage is based on recorded trace observations; correctness remains the report's evaluator outcome.", "",
        f"Source report: `{report_root.name}` · scenario SHA-256 verified: `{audit['scenario_sha256']}` · "
        f"replayed traces: {audit['trace_replay']['referenced_trace_count']}/{audit['trace_replay']['referenced_trace_count']}.", "",
        "## Definitions", "",
        "An episode has **all-four current coverage** when each of the four tools returned a successful observation with `time_scope=current`. "
        "Historical, timeout, and error observations are listed separately and do not count toward coverage. Missing tool observations are not treated as healthy or faulty.", "",
        "Correct diagnoses use the existing evaluator definition: terminal diagnosis equals the scenario gold action, termination reason is `completed`, and recorded gold evidence is supported. Incorrect diagnoses use the existing metric: a terminal diagnosis differs from the gold terminal action. Reviews count terminal `request_review` actions; failed episodes use replayed terminal status `failed`. A residual outcome includes an episode outside those buckets, such as a completed diagnosis matching gold whose recorded gold evidence is unsupported. `classified_episode_count` counts every episode assigned exactly one selected outcome bucket, including residual outcomes, so it equals the coverage group's episode denominator.", "",
        "Successful current observations measure how much of the fixture was checked. They do not guarantee informative facts, a complete diagnosis, or correctness. Fewer tool calls do not automatically mean greater efficiency: this audit does not assign utility to latency, risk, or missed faults, and tool calls have no live operational cost here.", "",
        "## Coverage and evaluator outcomes", "",
        f"Across all {audit['summary']['classified_episode_count']} policy-episode runs, selected outcome counts are: "
        + "; ".join(f"{name.replace('_', ' ')} {count}" for name, count in audit["summary"]["outcome_counts"].items()) + ".", "",
        "Correct diagnoses are shown as count / diagnosable episodes within that coverage group. Other outcomes use count / all episodes in the group. `n` is the episode denominator; empty groups have no rate.", "",
        "| Policy | Split | Coverage | n | Correct diagnoses / diagnosable | Incorrect diagnoses / n | Reviews / n | Failed / n | Other / n |", "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for policy, splits in audit["policies"].items():
        for split, coverage_groups in splits.items():
            for key in ("partial", "all_four"):
                group = coverage_groups[key]
                outcomes = group["outcomes"]
                correct = outcomes["correct_diagnoses"]
                lines.append(
                    f"| `{policy}` | {split} | {'all four' if key == 'all_four' else 'partial'} | {group['episode_denominator']} | "
                    f"{correct['count']} / {correct['denominator']} | "
                    f"{outcomes['incorrect_diagnoses']['count']} / {group['episode_denominator']} | "
                    f"{outcomes['reviews']['count']} / {group['episode_denominator']} | "
                    f"{outcomes['failed_episodes']['count']} / {group['episode_denominator']} | "
                    f"{outcomes['other_terminal_outcomes']['count']} / {group['episode_denominator']} |"
                )
    s = audit["summary"]
    residual_count = s["outcome_counts"]["other_terminal_outcomes"]
    lines += [
        "", "## Interpretation", "",
        f"Across {s['policy_episode_count']} policy-episode runs, {s['incomplete_coverage_episode_count']} ended without all four successful current observations; "
        f"{s['incomplete_coverage_correct_diagnosis_count']} were evaluator-correct diagnoses, {s['incomplete_coverage_incorrect_diagnosis_count']} were incorrect diagnoses, "
        f"{s['incomplete_coverage_review_count']} ended in review, and {s['incomplete_coverage_failed_episode_count']} were failed episodes. "
        "Failed episodes are not necessarily deliberate early-stop choices; they include traces whose harness outcome was failure. "
        "The accepted diagnosis/review actions are policy choices, while action eligibility and evidence support are deterministic harness checks. "
        f"The {s['incomplete_coverage_incorrect_diagnosis_count']} incomplete-coverage incorrect diagnoses support studying a stricter stopping rule as a separate question. "
        "They do not establish that such a rule would improve outcomes; no stopping behavior was changed or evaluated here.", "",
        "The traces show only report text, requested observations, tool attempts, and recorded budgets. The section below is evaluator-only hindsight: the policy did not see unrequested observations. Its annotations use only exact structured current facts that match the existing workflow evidence rules; free-text fixture messages are not interpreted.", "",
    ]
    if residual_count:
        lines += [
            f"{residual_count} episode{' was' if residual_count == 1 else 's were'} assigned to the residual outcome bucket. "
            "This includes completed diagnoses matching gold when the evaluator did not mark the recorded gold evidence as supported; historical correctness metrics retain their existing definitions.", "",
        ]
    lines += [
        "## Per-episode trace evidence", "",
        "Links open the recorded JSONL traces. Each row lists the observed coverage and terminal result; hidden fixture annotations are kept in the evaluator-only section below.", "",
        "| Policy | Split / scenario | Coverage | Terminal action / reason | Evaluator outcome | Trace |", "|---|---|---|---|---|---|",
    ]
    for row in audit["episodes"]:
        link_target = os.path.relpath(report_root / row["trace"], output_dir)
        label = f"{row['policy']} {row['episode_id']}"
        lines.append(
            f"| `{row['policy']}` | {row['split']} / `{row['scenario_id']}` | "
            f"{'all four' if row['tools']['all_four_current_success'] else 'partial'} | "
            f"`{row['terminal']['action'] or 'none'}` / `{row['terminal']['reason']}` | "
            f"{row['evaluator_outcome']} | [{label}]({link_target}) |"
        )
    lines += ["", "## Evaluator-only hindsight", "", "These annotations are derived from unrequested fixture observations after the scenario hash check. They are not policy-visible evidence and do not change replay, proposal selection, or the historical evaluator metrics.", ""]
    hindsight_rows = [row for row in audit["episodes"] if row["evaluator_only_hindsight"]["unrequested_structured_signals"]]
    if not hindsight_rows:
        lines.append("No relevant unrequested structured fault or contradiction signals were recorded.")
    else:
        lines += ["| Policy / split / scenario | Tool | Relationship | Exact structured facts | Trace |", "|---|---|---|---|---|"]
        for row in hindsight_rows:
            target = os.path.relpath(report_root / row["trace"], output_dir)
            for signal in row["evaluator_only_hindsight"]["unrequested_structured_signals"]:
                fact_text = ", ".join(f"`{item['fact']}={json.dumps(item['equals'])}`" for item in signal["facts"])
                lines.append(
                    f"| `{row['policy']}` / {row['split']} / `{row['scenario_id']}` | `{signal['tool_name']}` | "
                    f"{signal['relationship']} ({signal['fault_category']}) | {fact_text} | [trace]({target}) |"
                )
    lines.append("")
    return "\n".join(lines)


def write_coverage_audit(audit: dict[str, Any], report_dir: Path | str, output_dir: Path | str) -> tuple[Path, Path]:
    """Write JSON and Markdown artifacts into a new output directory."""
    report_root = Path(report_dir).resolve(strict=True)
    destination = Path(output_dir).resolve()
    try:
        destination.relative_to(report_root)
    except ValueError:
        pass
    else:
        raise CoverageAuditError("audit output directory must be outside the source report")
    if destination.exists() and any(destination.iterdir()):
        raise CoverageAuditError(f"audit output directory is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "investigation-coverage.json"
    markdown_path = destination / "investigation-coverage.md"
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(audit, report_root, destination), encoding="utf-8")
    return json_path, markdown_path


def audit_report(report_dir: Path | str, output_dir: Path | str, scenario_file: Path | str = SCENARIO_FILE) -> tuple[Path, Path]:
    audit = build_coverage_audit(report_dir, scenario_file)
    return write_coverage_audit(audit, report_dir, output_dir)
