"""Policies that propose one currently eligible workflow action."""

import re
from typing import Any

from .workflow import ACTION_IDS, ACTION_NAMES, TERMINAL_ACTIONS, TOOL_ACTIONS, VisibleState, Proposal, check_terminal_evidence

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
    """Rank eligible actions; optionally mask diagnoses unsupported by visible evidence."""

    def __init__(self, ranker: Any, evidence_masked: bool = False):
        self.ranker = ranker
        self.evidence_masked = evidence_masked
        self.name = "gliclass_evidence_masked" if evidence_masked else "gliclass"
        self.load_seconds = float(getattr(ranker, "load_seconds", 0.0))

    def candidate_set(self, state: VisibleState, eligible_action_ids: tuple[str, ...]) -> tuple[tuple[str, ...], dict[str, str]]:
        eligible = set(eligible_action_ids)
        scored = []
        excluded = {}
        diagnoses = set(TERMINAL_ACTIONS[:-1])
        for action_id in ACTION_IDS:
            if action_id not in eligible:
                if action_id in TOOL_ACTIONS and action_id in state.actions_attempted:
                    excluded[action_id] = "tool_already_attempted"
                elif action_id in TOOL_ACTIONS and state.remaining_tool_calls <= 0:
                    excluded[action_id] = "tool_call_budget_exhausted"
                else:
                    excluded[action_id] = "not_harness_eligible"
            elif self.evidence_masked and action_id in diagnoses:
                supported, reason, _evidence_ids = check_terminal_evidence(state, action_id)
                if not supported:
                    excluded[action_id] = f"diagnosis_not_supported:{reason}"
                else:
                    scored.append(action_id)
            else:
                scored.append(action_id)
        return tuple(scored), excluded

    def propose(self, state: VisibleState, eligible_action_ids: tuple[str, ...]) -> Proposal:
        scored_candidate_ids, excluded_candidates = self.candidate_set(state, eligible_action_ids)
        candidates = [(action_id, ACTION_NAMES[action_id]) for action_id in scored_candidate_ids]
        scores = self.ranker.rank(render_visible_state(state), candidates)
        if set(scores) != set(scored_candidate_ids):
            raise ValueError("GLiClass action ranker must return scores for exactly its scored candidate IDs")
        selected = max(scored_candidate_ids, key=scores.get)
        return Proposal(selected, scores=scores, scored_candidate_ids=scored_candidate_ids, excluded_candidates=excluded_candidates)
