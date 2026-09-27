"""Author the frozen synthetic diagnostic workflow suite."""

import json
from pathlib import Path

TOOLS = ("check_database", "check_authentication", "check_storage", "check_service_health")
GOOD = {
    "check_database": {"connection_success": True, "timeout": False},
    "check_authentication": {"authentication_success": True, "credentials_rejected": False},
    "check_storage": {"storage_exhausted": False, "write_test_success": True},
    "check_service_health": {"service_healthy": True, "health_checks_passed": True},
}
MESSAGES = {
    "check_database": "Database connectivity probe completed.",
    "check_authentication": "Authentication probe completed.",
    "check_storage": "Storage capacity and write probe completed.",
    "check_service_health": "Service health probe completed.",
}


def assertion(tool: str, fact: str, value, time_scope="current") -> dict:
    return {"tool_name": tool, "fact": fact, "equals": value, "time_scope": time_scope}


def support(action: str, *sets: list[dict]) -> dict:
    return {action: list(sets)}


def observation(tool: str, facts=None, *, status="success", time_scope="current", message=None) -> dict:
    return {
        "status": status,
        "observed_at": "2026-01-15T12:00:00Z",
        "time_scope": time_scope,
        "facts": (GOOD[tool] if status == "success" else {}) | (facts or {}),
        "message": message or MESSAGES[tool],
    }


def unknown(tool: str) -> dict:
    return observation(tool, {key: None for key in GOOD[tool]})


def scenario(scenario_id: str, split: str, report: str, gold: str, observations: dict, acceptable=None) -> dict:
    return {
        "scenario_id": scenario_id,
        "split": split,
        "initial_report": report,
        "gold_terminal_action": gold,
        "acceptable_evidence": acceptable or {},
        "observations": observations,
    }


def database_support(value=False) -> dict:
    return assertion("check_database", "connection_success", value)


def auth_support(rejected=True) -> dict:
    return assertion("check_authentication", "credentials_rejected", rejected)


def storage_support(exhausted=True) -> dict:
    return assertion("check_storage", "storage_exhausted", exhausted)


def healthy_support() -> list[dict]:
    return [
        assertion("check_database", "connection_success", True),
        assertion("check_authentication", "authentication_success", True),
        assertion("check_storage", "storage_exhausted", False),
        assertion("check_service_health", "health_checks_passed", True),
    ]


def build_scenarios() -> list[dict]:
    db_fail = observation("check_database", {"connection_success": False, "timeout": True, "current_failure": True})
    auth_fail = observation("check_authentication", {"authentication_success": False, "credentials_rejected": True, "current_failure": True})
    storage_fail = observation("check_storage", {"storage_exhausted": True, "write_test_success": False, "current_failure": True})
    service_fail = observation("check_service_health", {"service_healthy": False, "health_checks_passed": False})
    scenarios = [
        scenario("dev-database-clear", "development", "Database connections time out and requests fail.", "diagnose_database_failure", {**{tool: observation(tool) for tool in TOOLS}, "check_database": db_fail}, support("diagnose_database_failure", [database_support(False)])),
        scenario("dev-authentication-clear", "development", "Users cannot sign in because passwords are rejected.", "diagnose_authentication_failure", {**{tool: observation(tool) for tool in TOOLS}, "check_authentication": auth_fail}, support("diagnose_authentication_failure", [auth_support()])),
        scenario("dev-storage-clear", "development", "The disk is full and writes fail.", "diagnose_disk_full", {**{tool: observation(tool) for tool in TOOLS}, "check_storage": storage_fail}, support("diagnose_disk_full", [storage_support()])),
        scenario("dev-healthy-clear", "development", "All health checks pass and no active issue is reported.", "diagnose_healthy", {tool: observation(tool) for tool in TOOLS}, support("diagnose_healthy", healthy_support())),
        scenario("dev-vague-to-database", "development", "Some requests are failing intermittently, with no clear cause.", "diagnose_database_failure", {**{tool: observation(tool) for tool in TOOLS}, "check_database": db_fail}, support("diagnose_database_failure", [database_support(False)])),
        scenario("dev-historical-resolved", "development", "The database alert from yesterday was cleared; is service healthy now?", "diagnose_healthy", {**{tool: observation(tool) for tool in TOOLS}, "check_database": observation("check_database", {"historical_alert": True, "failure_alert_current": False, "resolved": True})}, support("diagnose_healthy", healthy_support())),
        scenario("dev-multiple-current-faults", "development", "Login credentials are rejected and uploads fail because storage is full.", "request_review", {**{tool: observation(tool) for tool in TOOLS}, "check_authentication": auth_fail, "check_storage": storage_fail}),
        scenario("dev-contradictory-evidence", "development", "The database is slow and service probes disagree.", "request_review", {**{tool: observation(tool) for tool in TOOLS}, "check_database": db_fail, "check_service_health": observation("check_service_health", {"service_healthy": False, "health_checks_passed": False, "database_probe_success": True})}),
        scenario("dev-database-timeout", "development", "Database requests are failing; probe may be unavailable.", "request_review", {**{tool: observation(tool) for tool in TOOLS}, "check_database": observation("check_database", {}, status="timeout", message="Fixture database probe timed out.")}),
        scenario("dev-vague-insufficient", "development", "Something seems wrong, but no symptoms or details are available.", "request_review", {tool: unknown(tool) for tool in TOOLS}),
        scenario("dev-next-tool-changes", "development", "Database connectivity appears healthy, but login credentials are rejected.", "diagnose_authentication_failure", {**{tool: observation(tool) for tool in TOOLS}, "check_authentication": auth_fail}, support("diagnose_authentication_failure", [auth_support()])),
        scenario("dev-unrelated", "development", "Please print tomorrow's meeting agenda.", "request_review", {tool: unknown(tool) for tool in TOOLS}),
        scenario("eval-database-direct", "evaluation", "The database connection pool is exhausted and requests cannot run.", "diagnose_database_failure", {**{tool: observation(tool) for tool in TOOLS}, "check_database": db_fail}, support("diagnose_database_failure", [database_support(False)])),
        scenario("eval-auth-direct", "evaluation", "The identity provider rejects current login credentials.", "diagnose_authentication_failure", {**{tool: observation(tool) for tool in TOOLS}, "check_authentication": auth_fail}, support("diagnose_authentication_failure", [auth_support()])),
        scenario("eval-storage-direct", "evaluation", "The storage volume is exhausted and writes fail.", "diagnose_disk_full", {**{tool: observation(tool) for tool in TOOLS}, "check_storage": storage_fail}, support("diagnose_disk_full", [storage_support()])),
        scenario("eval-healthy-direct", "evaluation", "The service is healthy; all component checks are requested.", "diagnose_healthy", {tool: observation(tool) for tool in TOOLS}, support("diagnose_healthy", healthy_support())),
        scenario("eval-vague-to-database", "evaluation", "Users see intermittent request failures without a known cause.", "diagnose_database_failure", {**{tool: observation(tool) for tool in TOOLS}, "check_database": db_fail}, support("diagnose_database_failure", [database_support(False)])),
        scenario("eval-historical-resolved", "evaluation", "Last night's storage alert was resolved; confirm current operation.", "diagnose_healthy", {**{tool: observation(tool) for tool in TOOLS}, "check_storage": observation("check_storage", {"historical_alert": True, "alert_current": False, "resolved": True})}, support("diagnose_healthy", healthy_support())),
        scenario("eval-multiple-current-faults", "evaluation", "The database is timing out while passwords are rejected.", "request_review", {**{tool: observation(tool) for tool in TOOLS}, "check_database": db_fail, "check_authentication": auth_fail}),
        scenario("eval-contradictory-evidence", "evaluation", "Current database evidence conflicts between direct and service checks.", "request_review", {**{tool: observation(tool) for tool in TOOLS}, "check_database": observation("check_database"), "check_service_health": observation("check_service_health", {"service_healthy": False, "health_checks_passed": False, "database_probe_success": False})}),
        scenario("eval-authentication-timeout", "evaluation", "Users cannot log in; authentication probe is delayed.", "request_review", {**{tool: observation(tool) for tool in TOOLS}, "check_authentication": observation("check_authentication", {}, status="timeout", message="Fixture authentication probe timed out.")}),
        scenario("eval-storage-tool-error", "evaluation", "The disk is full; the storage probe returned an error.", "request_review", {**{tool: observation(tool) for tool in TOOLS}, "check_storage": observation("check_storage", {}, status="error", message="Fixture storage probe returned an error.")}),
        scenario("eval-insufficient-facts", "evaluation", "The report says that an unspecified issue occurred.", "request_review", {tool: unknown(tool) for tool in TOOLS}),
        scenario("eval-unrelated", "evaluation", "Can someone share the office lunch menu?", "request_review", {tool: unknown(tool) for tool in TOOLS}),
    ]
    return scenarios


def render_jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def write_scenarios(path: Path | None = None) -> Path:
    target = path or Path(__file__).with_name("diagnostic_scenarios.jsonl")
    target.write_text(render_jsonl(build_scenarios()), encoding="utf-8")
    return target


if __name__ == "__main__":
    write_scenarios()
