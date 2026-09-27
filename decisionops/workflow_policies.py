"""Policies that propose one currently eligible workflow action."""

import re
from typing import Any

from .workflow import ACTION_NAMES, TOOL_ACTIONS, VisibleState, Proposal, check_terminal_evidence

TOOL_ORDER = ("check_database", "check_authentication", "check_storage", "check_service_health")
SYMPTOM_PATTERNS = (
    ("check_database", re.compile(r"\b(?:database|postgres(?:ql)?|mysql|sql|connection|query|queries|pool)\b", re.I)),
    ("check_authentication", re.compile(r"\b(?:login|log in|sign in|password|credential|token|unauthorized|identity provider|authentication)\b", re.I)),
    ("check_storage", re.compile(r"\b(?:disk|storage|filesystem|volume|partition|uploads?|space left|writes? fail)\b", re.I)),
)


def _current_diagnosis(state: VisibleState) -> str | None:
    candidates = ("diagnose_database_failure", "diagnose_authentication_failure", "diagnose_disk_full", "diagnose_healthy")
    for action in candidates:
        supported, _reason, evidence = check_terminal_evidence(state, action)
        if supported and evidence:
            return action
    return None


def _symptom_tools(report: str) -> list[str]:
    matches = []
    for tool, pattern in SYMPTOM_PATTERNS:
        found = pattern.search(report)
        if found:
            matches.append((found.start(), tool))
    return [tool for _position, tool in sorted(matches)]


class FixedOrderPolicy:
    name = "fixed_order"
    load_seconds = 0.0

    def propose(self, state: VisibleState, eligible_action_ids: tuple[str, ...]) -> Proposal:
        for tool in TOOL_ORDER:
            if tool in eligible_action_ids:
                return Proposal(tool)
        diagnosis = _current_diagnosis(state)
        return Proposal(diagnosis or "request_review")


class RulesPolicy:
    name = "rules"
    load_seconds = 0.0

    def propose(self, state: VisibleState, eligible_action_ids: tuple[str, ...]) -> Proposal:
        if any(obs["status"] != "success" for obs in state.observations):
            return Proposal("request_review")
        targeted = [tool for tool in _symptom_tools(state.initial_report) if tool in eligible_action_ids]
        diagnosis = _current_diagnosis(state)
        if targeted:
            return Proposal(targeted[0])
        if diagnosis:
            return Proposal(diagnosis)
        for tool in TOOL_ORDER:
            if tool in eligible_action_ids:
                return Proposal(tool)
        return Proposal("request_review")


def render_visible_state(state: VisibleState) -> str:
    lines = [f"Initial report: {state.initial_report}"]
    if state.observations:
        lines.append("Recorded observations:")
        for observation in state.observations:
            lines.append(
                f"[{observation['observation_id']}] tool={observation['tool_name']} status={observation['status']} "
                f"time_scope={observation['time_scope']} facts={observation['facts']} message={observation['message']}"
            )
    else:
        lines.append("Recorded observations: none")
    lines += [
        f"Tools already attempted: {', '.join(state.actions_attempted) if state.actions_attempted else 'none'}",
        f"Remaining budgets: tool_calls={state.remaining_tool_calls}/{state.max_tool_calls}, decisions={state.remaining_decisions}/{state.max_decisions}",
    ]
    if state.rejection_feedback:
        lines.append("Harness feedback: " + "; ".join(state.rejection_feedback))
    return "\n".join(lines)


class GLiClassPolicy:
    """Rank action candidates directly using the visible episode state."""

    name = "gliclass"

    def __init__(self, ranker: Any):
        self.ranker = ranker
        self.load_seconds = float(getattr(ranker, "load_seconds", 0.0))

    def propose(self, state: VisibleState, eligible_action_ids: tuple[str, ...]) -> Proposal:
        candidates = [(action_id, ACTION_NAMES[action_id]) for action_id in eligible_action_ids]
        scores = self.ranker.rank(render_visible_state(state), candidates)
        if set(scores) != set(eligible_action_ids):
            raise ValueError("GLiClass action ranker returned scores outside eligible actions")
        selected = max(eligible_action_ids, key=scores.get)
        return Proposal(selected, scores=scores)
