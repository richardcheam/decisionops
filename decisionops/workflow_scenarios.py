"""Hidden simulator fixtures and evaluation-only scenario annotations."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCENARIO_FILE = Path(__file__).resolve().parents[1] / "data" / "diagnostic_scenarios.jsonl"
TOOL_NAMES = ("check_database", "check_authentication", "check_storage", "check_service_health")
GOLD_ACTIONS = {
    "diagnose_database_failure", "diagnose_authentication_failure", "diagnose_disk_full", "diagnose_healthy", "request_review"
}
FORBIDDEN_FIXTURE_KEYS = {"diagnosis", "recommended_action", "next_action", "final_diagnosis"}


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    split: str
    initial_report: str
    gold_terminal_action: str
    acceptable_evidence: tuple[tuple[dict[str, Any], ...], ...]
    observations: dict[str, dict[str, Any]]


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in FORBIDDEN_FIXTURE_KEYS or _contains_forbidden_key(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def validate_scenarios(rows: list[dict[str, Any]]) -> None:
    ids = set()
    for row in rows:
        required = {"scenario_id", "split", "initial_report", "gold_terminal_action", "acceptable_evidence", "observations"}
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("scenario has missing or unexpected fields")
        scenario_id = row["scenario_id"]
        if not isinstance(scenario_id, str) or not scenario_id or scenario_id in ids:
            raise ValueError("scenario IDs must be unique and non-empty")
        ids.add(scenario_id)
        if row["split"] not in {"development", "evaluation"}:
            raise ValueError(f"{scenario_id}: split must be development or evaluation")
        if not isinstance(row["initial_report"], str) or not row["initial_report"].strip():
            raise ValueError(f"{scenario_id}: initial report must be non-empty")
        if row["gold_terminal_action"] not in GOLD_ACTIONS:
            raise ValueError(f"{scenario_id}: invalid gold outcome")
        fixtures = row["observations"]
        if not isinstance(fixtures, dict) or set(fixtures) != set(TOOL_NAMES):
            raise ValueError(f"{scenario_id}: all four fixture observations are required")
        if _contains_forbidden_key(fixtures):
            raise ValueError(f"{scenario_id}: a tool fixture contains final-decision or next-action data")
        for tool_name, item in fixtures.items():
            if set(item) != {"status", "observed_at", "time_scope", "facts", "message"}:
                raise ValueError(f"{scenario_id}/{tool_name}: invalid observation fields")
            if item["status"] not in {"success", "timeout", "error"}:
                raise ValueError(f"{scenario_id}/{tool_name}: invalid tool status")
            if item["time_scope"] not in {"current", "historical"}:
                raise ValueError(f"{scenario_id}/{tool_name}: time scope must be current or historical")
            if not isinstance(item["observed_at"], str) or not isinstance(item["message"], str) or not isinstance(item["facts"], dict):
                raise ValueError(f"{scenario_id}/{tool_name}: observation metadata malformed")
        acceptable = row["acceptable_evidence"]
        if not isinstance(acceptable, dict):
            raise ValueError(f"{scenario_id}: acceptable evidence must be an object")
        for action, alternatives in acceptable.items():
            if action != row["gold_terminal_action"] or not isinstance(alternatives, list):
                raise ValueError(f"{scenario_id}: acceptable evidence must describe its gold action")
            for assertions in alternatives:
                if not isinstance(assertions, list) or not assertions:
                    raise ValueError(f"{scenario_id}: acceptable evidence alternatives must be non-empty lists")
                for assertion in assertions:
                    if set(assertion) != {"tool_name", "fact", "equals", "time_scope"} or assertion["tool_name"] not in TOOL_NAMES:
                        raise ValueError(f"{scenario_id}: invalid acceptable evidence assertion")
        if row["gold_terminal_action"] == "request_review" and acceptable:
            raise ValueError(f"{scenario_id}: review scenarios do not carry diagnosis evidence")
        if row["gold_terminal_action"] != "request_review" and not acceptable:
            raise ValueError(f"{scenario_id}: diagnosable scenario needs acceptable evidence")
    if len(rows) != 24:
        raise ValueError(f"scenario suite must contain 24 fixtures, got {len(rows)}")
    for split in ("development", "evaluation"):
        if sum(row["split"] == split for row in rows) != 12:
            raise ValueError(f"scenario suite must contain 12 {split} fixtures")


def load_scenarios(path: Path = SCENARIO_FILE) -> list[Scenario]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    validate_scenarios(rows)
    return [Scenario(
        scenario_id=row["scenario_id"], split=row["split"], initial_report=row["initial_report"],
        gold_terminal_action=row["gold_terminal_action"],
        acceptable_evidence=tuple(tuple(assertion for assertion in alternative) for alternative in row["acceptable_evidence"].get(row["gold_terminal_action"], [])),
        observations=row["observations"],
    ) for row in rows]
