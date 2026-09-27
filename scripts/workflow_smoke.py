"""Explicit, offline GLiClass smoke check for the bounded workflow."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decisionops.workflow import replay_trace
from decisionops.workflow_eval import run_one_episode


def main() -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    scenario, result = run_one_episode("dev-database-clear", "gliclass")
    replay = replay_trace(list(result.trace))
    smoke_passed = (
        result.model_loading_seconds > 0
        and result.decision_count > 0
        and result.decision_count <= 6
        and result.tool_call_count <= 4
        and replay["terminal_action"] == result.terminal_action
        and replay["terminal_reason"] == result.terminal_reason
    )
    print(json.dumps({
        "smoke_status": "passed" if smoke_passed else "failed",
        "offline_simulation": True,
        "policy": "gliclass",
        "scenario_id": scenario.scenario_id,
        "terminal_action": result.terminal_action,
        "terminal_reason": result.terminal_reason,
        "decision_count": result.decision_count,
        "tool_call_count": result.tool_call_count,
        "model_loading_seconds": result.model_loading_seconds,
        "trace_replayed": replay["terminal_action"] == result.terminal_action,
        "semantic_match": result.terminal_action == scenario.gold_terminal_action,
    }, indent=2))
    return 0 if smoke_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
