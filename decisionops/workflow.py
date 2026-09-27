"""Bounded harness for policies acting on recorded diagnostic observations."""

import copy
import json
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .workflow_scenarios import Scenario, TOOL_NAMES

TOOL_ACTIONS = TOOL_NAMES
TERMINAL_ACTIONS = (
    "diagnose_database_failure", "diagnose_authentication_failure", "diagnose_disk_full", "diagnose_healthy", "request_review"
)
ACTION_IDS = (*TOOL_ACTIONS, *TERMINAL_ACTIONS)
ACTION_NAMES = {
    "check_database": "Check database",
    "check_authentication": "Check authentication",
    "check_storage": "Check storage",
    "check_service_health": "Check service health",
    "diagnose_database_failure": "Database failure",
    "diagnose_authentication_failure": "Authentication failure",
    "diagnose_disk_full": "Disk full",
    "diagnose_healthy": "Healthy",
    "request_review": "Request review",
}
ACTION_KIND = {action: ("tool" if action in TOOL_ACTIONS else "terminal") for action in ACTION_IDS}
DEFAULT_MAX_TOOL_CALLS = 4
DEFAULT_MAX_DECISIONS = 6
MAX_EVIDENCE_RECOVERY_ATTEMPTS = 1


@dataclass(frozen=True)
class Proposal:
    action_id: Any
    evidence_ids: tuple[str, ...] = ()
    scores: dict[str, float] | None = None


@dataclass(frozen=True)
class VisibleState:
    initial_report: str
    observations: tuple[dict[str, Any], ...]
    actions_attempted: tuple[str, ...]
    remaining_tool_calls: int
    max_tool_calls: int
    remaining_decisions: int
    max_decisions: int
    rejection_feedback: tuple[str, ...] = ()
    terminal_status: str = "in_progress"
    terminal_reason: str | None = None
    terminal_action: str | None = None
    cited_evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EpisodeState:
    initial_report: str
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    max_decisions: int = DEFAULT_MAX_DECISIONS
    observations: list[dict[str, Any]] = field(default_factory=list)
    actions_attempted: list[str] = field(default_factory=list)
    remaining_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    remaining_decisions: int = DEFAULT_MAX_DECISIONS
    decision_count: int = 0
    terminal_status: str = "in_progress"
    terminal_reason: str | None = None
    terminal_action: str | None = None
    cited_evidence_ids: list[str] = field(default_factory=list)
    rejection_feedback: list[str] = field(default_factory=list)
    unsupported_diagnosis_proposals: int = 0
    invalid_proposals_rejected: int = 0
    recovery_attempts: int = 0

    @property
    def tool_call_count(self) -> int:
        return len(self.actions_attempted)

    def visible(self) -> VisibleState:
        return VisibleState(
            initial_report=self.initial_report,
            observations=tuple(copy.deepcopy(self.observations)),
            actions_attempted=tuple(self.actions_attempted),
            remaining_tool_calls=self.remaining_tool_calls,
            max_tool_calls=self.max_tool_calls,
            remaining_decisions=self.remaining_decisions,
            max_decisions=self.max_decisions,
            rejection_feedback=tuple(self.rejection_feedback),
            terminal_status=self.terminal_status,
            terminal_reason=self.terminal_reason,
            terminal_action=self.terminal_action,
            cited_evidence_ids=tuple(self.cited_evidence_ids),
        )

    def as_dict(self) -> dict[str, Any]:
        return self.visible().as_dict()


@dataclass(frozen=True)
class EpisodeResult:
    episode_id: str
    terminal_status: str
    terminal_reason: str
    terminal_action: str | None
    cited_evidence_ids: tuple[str, ...]
    observations: tuple[dict[str, Any], ...]
    trace: tuple[dict[str, Any], ...]
    tool_call_count: int
    decision_count: int
    unsupported_diagnosis_proposals: int
    invalid_proposals_rejected: int
    end_to_end_seconds: float
    model_loading_seconds: float
    simulator_failure: bool
    final_state: EpisodeState


class Policy(Protocol):
    name: str
    load_seconds: float

    def propose(self, state: VisibleState, eligible_action_ids: tuple[str, ...]) -> Proposal: ...


class ToolExecutionError(RuntimeError):
    pass


class RecordedToolEnvironment:
    """Provides one fixture result on demand; never executes external actions."""

    def __init__(self, scenario: Scenario):
        self.__fixtures = copy.deepcopy(scenario.observations)
        self.__requested: set[str] = set()

    def execute(self, tool_name: str, observation_id: str) -> dict[str, Any]:
        if tool_name not in TOOL_NAMES or tool_name not in self.__fixtures:
            raise ToolExecutionError(f"no recorded fixture for {tool_name!r}")
        if tool_name in self.__requested:
            raise ToolExecutionError(f"tool {tool_name!r} was already requested")
        self.__requested.add(tool_name)
        fixture = self.__fixtures[tool_name]
        return {"observation_id": observation_id, "tool_name": tool_name, **copy.deepcopy(fixture)}


def eligible_actions(state: EpisodeState | VisibleState) -> tuple[str, ...]:
    actions = []
    if state.remaining_tool_calls > 0:
        actions.extend(tool for tool in TOOL_ACTIONS if tool not in state.actions_attempted)
    actions.extend(TERMINAL_ACTIONS)
    return tuple(actions)


def _current_observations(state: EpisodeState | VisibleState) -> list[dict[str, Any]]:
    return [obs for obs in state.observations if obs["status"] == "success" and obs["time_scope"] == "current"]


def _area_evidence(state: EpisodeState | VisibleState) -> dict[str, dict[str, list[str]]]:
    evidence: dict[str, dict[str, list[str]]] = {
        category: {"positive": [], "negative": []}
        for category in ("database_failure", "authentication_failure", "disk_full")
    }
    for obs in _current_observations(state):
        facts, source, observation_id = obs["facts"], obs["tool_name"], obs["observation_id"]
        if source == "check_database":
            if facts.get("connection_success") is True:
                evidence["database_failure"]["positive"].append(observation_id)
            if facts.get("connection_success") is False or facts.get("timeout") is True:
                evidence["database_failure"]["negative"].append(observation_id)
        if source == "check_service_health":
            if facts.get("database_probe_success") is True:
                evidence["database_failure"]["positive"].append(observation_id)
            if facts.get("database_probe_success") is False:
                evidence["database_failure"]["negative"].append(observation_id)
        if source == "check_authentication":
            if facts.get("authentication_success") is True or facts.get("credentials_rejected") is False:
                evidence["authentication_failure"]["positive"].append(observation_id)
            if facts.get("authentication_success") is False or facts.get("credentials_rejected") is True:
                evidence["authentication_failure"]["negative"].append(observation_id)
        if source == "check_service_health":
            if facts.get("authentication_probe_success") is True:
                evidence["authentication_failure"]["positive"].append(observation_id)
            if facts.get("authentication_probe_success") is False:
                evidence["authentication_failure"]["negative"].append(observation_id)
        if source == "check_storage":
            if facts.get("storage_exhausted") is False or facts.get("write_test_success") is True:
                evidence["disk_full"]["positive"].append(observation_id)
            if facts.get("storage_exhausted") is True or facts.get("write_test_success") is False:
                evidence["disk_full"]["negative"].append(observation_id)
        if source == "check_service_health":
            if facts.get("storage_probe_success") is True:
                evidence["disk_full"]["positive"].append(observation_id)
            if facts.get("storage_probe_success") is False:
                evidence["disk_full"]["negative"].append(observation_id)
    return evidence


def _healthy_evidence_ids(state: EpisodeState | VisibleState) -> list[str]:
    requirements = {
        "check_database": {"connection_success": True},
        "check_authentication": {"authentication_success": True, "credentials_rejected": False},
        "check_storage": {"storage_exhausted": False},
        "check_service_health": {"health_checks_passed": True, "service_healthy": True},
    }
    by_tool = {obs["tool_name"]: obs for obs in _current_observations(state)}
    if set(requirements) - set(by_tool):
        return []
    for tool, facts in requirements.items():
        if any(by_tool[tool]["facts"].get(key) is not expected for key, expected in facts.items()):
            return []
    return [by_tool[tool]["observation_id"] for tool in requirements]


def _supporting_ids(state: EpisodeState | VisibleState, action_id: str) -> list[str]:
    if action_id == "diagnose_healthy":
        return _healthy_evidence_ids(state)
    category = {
        "diagnose_database_failure": "database_failure",
        "diagnose_authentication_failure": "authentication_failure",
        "diagnose_disk_full": "disk_full",
    }.get(action_id)
    if category is None:
        return []
    return list(dict.fromkeys(_area_evidence(state)[category]["negative"]))


def check_terminal_evidence(state: EpisodeState | VisibleState, action_id: str) -> tuple[bool, str, list[str]]:
    seen_ids = {obs["observation_id"] for obs in state.observations}
    failures = [obs for obs in state.observations if obs["status"] != "success"]
    support_ids = _supporting_ids(state, action_id)
    if failures:
        return False, "unresolved_tool_failure", support_ids
    if action_id == "diagnose_healthy":
        if not support_ids:
            return False, "healthy_requires_current_success_from_all_four_tools", support_ids
        faults = _area_evidence(state)
        if any(item["negative"] for item in faults.values()):
            return False, "current_fault_conflicts_with_healthy_diagnosis", support_ids
        if any(item["positive"] and item["negative"] for item in faults.values()):
            return False, "contradictory_current_evidence", support_ids
        return True, "supported", support_ids
    if action_id in ("diagnose_database_failure", "diagnose_authentication_failure", "diagnose_disk_full"):
        category = action_id.removeprefix("diagnose_")
        evidence = _area_evidence(state)
        if any(item["positive"] and item["negative"] for item in evidence.values()):
            return False, "contradictory_current_evidence", support_ids
        negative_categories = [name for name, item in evidence.items() if item["negative"]]
        if len(negative_categories) > 1:
            return False, "multiple_current_fault_categories", support_ids
        if category not in negative_categories:
            return False, f"current_observations_do_not_support_{category}", support_ids
        if not support_ids or any(obs_id not in seen_ids for obs_id in support_ids):
            return False, "diagnosis_requires_visible_supporting_observations", support_ids
        return True, "supported", support_ids
    return action_id == "request_review", "review_requested", []


def _proposal_dict(proposal: Any) -> dict[str, Any] | Any:
    if isinstance(proposal, Proposal):
        return {"action_id": proposal.action_id, "evidence_ids": list(proposal.evidence_ids), "scores": proposal.scores}
    if isinstance(proposal, dict):
        return copy.deepcopy(proposal)
    if isinstance(proposal, (str, int, float, bool)) or proposal is None:
        return proposal
    return repr(proposal)


def _decode_proposal(raw: Any) -> tuple[Proposal | None, str | None]:
    if isinstance(raw, Proposal):
        proposal = raw
    elif isinstance(raw, dict) and set(raw) <= {"action_id", "evidence_ids", "scores"} and "action_id" in raw:
        evidence = raw.get("evidence_ids", ())
        if not isinstance(evidence, (tuple, list)) or not all(isinstance(value, str) for value in evidence):
            return None, "malformed_evidence_references"
        scores = raw.get("scores")
        if scores is not None and not isinstance(scores, dict):
            return None, "malformed_scores"
        proposal = Proposal(raw["action_id"], tuple(evidence), scores)
    else:
        return None, "malformed_proposal"
    if not isinstance(proposal.action_id, str):
        return None, "malformed_action_id"
    if not all(isinstance(value, str) for value in proposal.evidence_ids):
        return None, "malformed_evidence_references"
    if proposal.scores is not None:
        if not isinstance(proposal.scores, dict) or not all(isinstance(key, str) for key in proposal.scores):
            return None, "malformed_scores"
        try:
            values = {key: float(value) for key, value in proposal.scores.items()}
        except (TypeError, ValueError):
            return None, "malformed_scores"
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values.values()):
            return None, "malformed_scores"
        proposal = Proposal(proposal.action_id, tuple(proposal.evidence_ids), values)
    return proposal, None


def _validate_scores(proposal: Proposal, eligible: tuple[str, ...]) -> str | None:
    if proposal.scores is None:
        return None
    if set(proposal.scores) != set(eligible):
        return "model_scores_must_cover_exactly_eligible_actions"
    if abs(sum(proposal.scores.values()) - 1.0) > 0.01:
        return "model_action_scores_do_not_sum_to_one"
    if proposal.scores[proposal.action_id] + 0.0011 < max(proposal.scores.values()):
        return "selected_action_disagrees_with_largest_score"
    return None


def _terminal_status(reason: str) -> str:
    if reason == "completed":
        return "completed"
    if reason == "review":
        return "review"
    return "failed"


def _finish(state: EpisodeState, reason: str, action: str | None = None, evidence_ids=()) -> None:
    state.terminal_reason = reason
    state.terminal_status = _terminal_status(reason)
    state.terminal_action = action
    state.cited_evidence_ids = list(evidence_ids)


def _make_event(
    episode_id: str,
    step_id: int,
    before: dict[str, Any],
    eligible: tuple[str, ...],
    proposal: Any,
    acceptance: dict[str, Any],
    observation: dict[str, Any] | None,
    state: EpisodeState,
    event_type: str = "decision",
) -> dict[str, Any]:
    return {
        "event_type": event_type, "episode_id": episode_id, "step_id": step_id,
        "visible_state_before": before, "eligible_actions": list(eligible),
        "proposal": _proposal_dict(proposal), "acceptance": acceptance,
        "tool_observation": copy.deepcopy(observation), "visible_state_after": state.as_dict(),
        "remaining_budgets": {"tool_calls": state.remaining_tool_calls, "decisions": state.remaining_decisions},
        "terminal_decision": None if state.terminal_reason is None else {"action_id": state.terminal_action, "reason": state.terminal_reason, "status": state.terminal_status, "cited_evidence_ids": list(state.cited_evidence_ids)},
    }


def run_episode(
    scenario: Scenario,
    policy: Policy,
    episode_id: str = "episode-001",
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    max_decisions: int = DEFAULT_MAX_DECISIONS,
) -> EpisodeResult:
    if max_tool_calls < 0 or max_decisions < 0:
        raise ValueError("workflow budgets must be non-negative")
    state = EpisodeState(scenario.initial_report, max_tool_calls=max_tool_calls, max_decisions=max_decisions,
                         remaining_tool_calls=max_tool_calls, remaining_decisions=max_decisions)
    environment = RecordedToolEnvironment(scenario)
    trace: list[dict[str, Any]] = []
    start = time.perf_counter()
    simulator_failure = False

    while state.terminal_reason is None:
        if state.remaining_decisions <= 0:
            before = state.as_dict()
            _finish(state, "exhausted_budget")
            trace.append(_make_event(episode_id, state.decision_count + 1, before, eligible_actions(state), None,
                                     {"accepted": False, "reason": "exhausted_budget", "detail": "decision budget exhausted"}, None, state, "termination"))
            break
        before = state.as_dict()
        eligible = eligible_actions(state)
        if not eligible:
            _finish(state, "exhausted_budget")
            trace.append(_make_event(episode_id, state.decision_count + 1, before, eligible, None,
                                     {"accepted": False, "reason": "exhausted_budget", "detail": "no eligible actions remain"}, None, state, "termination"))
            break
        state.remaining_decisions -= 1
        state.decision_count += 1
        try:
            raw = policy.propose(state.visible(), eligible)
        except Exception as exc:
            raw = {"policy_error": f"{type(exc).__name__}: {exc}"}
            proposal, malformed_reason = None, "policy_execution_error"
        else:
            proposal, malformed_reason = _decode_proposal(raw)
        acceptance = {"accepted": False, "reason": "", "detail": ""}
        observation = None
        if malformed_reason:
            acceptance = {"accepted": False, "reason": malformed_reason, "detail": "proposal could not be parsed"}
            state.invalid_proposals_rejected += 1
            _finish(state, "invalid_proposal")
        elif proposal.action_id not in ACTION_KIND:
            acceptance = {"accepted": False, "reason": "unknown_action", "detail": f"unknown action {proposal.action_id!r}"}
            state.invalid_proposals_rejected += 1
            _finish(state, "invalid_proposal")
        elif proposal.action_id not in eligible:
            if proposal.action_id in TOOL_ACTIONS and state.remaining_tool_calls <= 0:
                acceptance = {"accepted": False, "reason": "tool_call_budget_exhausted", "detail": "tool call budget is zero"}
                _finish(state, "exhausted_budget")
            else:
                acceptance = {"accepted": False, "reason": "tool_already_attempted" if proposal.action_id in state.actions_attempted else "action_not_eligible", "detail": f"{proposal.action_id} is not currently eligible"}
                state.invalid_proposals_rejected += 1
                _finish(state, "invalid_proposal")
        else:
            score_error = _validate_scores(proposal, eligible)
            seen = {obs["observation_id"] for obs in state.observations}
            if score_error:
                acceptance = {"accepted": False, "reason": "malformed_scores", "detail": score_error}
                state.invalid_proposals_rejected += 1
                _finish(state, "invalid_proposal")
            elif any(ref not in seen for ref in proposal.evidence_ids):
                acceptance = {"accepted": False, "reason": "unseen_evidence_reference", "detail": "proposal cited evidence not present in visible state"}
                state.invalid_proposals_rejected += 1
                _finish(state, "invalid_proposal")
            elif proposal.action_id in TOOL_ACTIONS:
                if proposal.evidence_ids:
                    acceptance = {"accepted": False, "reason": "tool_action_cannot_cite_terminal_evidence", "detail": "evidence references are only valid on terminal proposals"}
                    state.invalid_proposals_rejected += 1
                    _finish(state, "invalid_proposal")
                else:
                    state.actions_attempted.append(proposal.action_id)
                    state.remaining_tool_calls -= 1
                    try:
                        observation = environment.execute(proposal.action_id, f"obs-{len(state.observations) + 1:02d}-{proposal.action_id}")
                        if observation["tool_name"] != proposal.action_id or observation["status"] not in {"success", "timeout", "error"}:
                            raise ToolExecutionError("tool returned a malformed observation")
                        state.observations.append(observation)
                        acceptance = {"accepted": True, "reason": "tool_observation_recorded", "detail": observation["status"]}
                    except Exception as exc:
                        simulator_failure = True
                        acceptance = {"accepted": False, "reason": "tool_execution_failure", "detail": f"{type(exc).__name__}: {exc}"}
                        _finish(state, "tool_failure")
            elif proposal.action_id == "request_review":
                acceptance = {"accepted": True, "reason": "review_requested", "detail": "review is always an available terminal choice"}
                _finish(state, "review", "request_review", proposal.evidence_ids)
            else:
                passed, reason, support_ids = check_terminal_evidence(state, proposal.action_id)
                cited = list(proposal.evidence_ids) if proposal.evidence_ids else support_ids
                if any(ref not in support_ids for ref in cited):
                    passed, reason = False, "cited_observation_does_not_support_proposed_diagnosis"
                if passed:
                    acceptance = {"accepted": True, "reason": "diagnosis_supported", "detail": reason}
                    _finish(state, "completed", proposal.action_id, cited)
                else:
                    state.unsupported_diagnosis_proposals += 1
                    state.rejection_feedback.append(reason)
                    acceptance = {"accepted": False, "reason": "unsupported_diagnosis", "detail": f"proposed diagnosis does not support: {reason}", "evidence_check_reason": reason, "deterministic_supporting_evidence_ids": support_ids}
                    if state.recovery_attempts >= MAX_EVIDENCE_RECOVERY_ATTEMPTS:
                        _finish(state, "invalid_proposal")
                    else:
                        state.recovery_attempts += 1
        trace.append(_make_event(episode_id, state.decision_count, before, eligible, raw, acceptance, observation, state))

    return EpisodeResult(
        episode_id=episode_id, terminal_status=state.terminal_status, terminal_reason=state.terminal_reason or "tool_failure",
        terminal_action=state.terminal_action, cited_evidence_ids=tuple(state.cited_evidence_ids),
        observations=tuple(copy.deepcopy(state.observations)), trace=tuple(trace), tool_call_count=state.tool_call_count,
        decision_count=state.decision_count, unsupported_diagnosis_proposals=state.unsupported_diagnosis_proposals,
        invalid_proposals_rejected=state.invalid_proposals_rejected, end_to_end_seconds=time.perf_counter() - start,
        model_loading_seconds=float(getattr(policy, "load_seconds", 0.0)), simulator_failure=simulator_failure, final_state=state,
    )


def _restore_state(data: dict[str, Any]) -> EpisodeState:
    allowed = set(VisibleState.__dataclass_fields__)
    if set(data) != allowed:
        raise ValueError("trace visible state has unexpected or missing fields")
    state = EpisodeState(
        initial_report=data["initial_report"], max_tool_calls=data["max_tool_calls"], max_decisions=data["max_decisions"],
        observations=list(copy.deepcopy(data["observations"])), actions_attempted=list(data["actions_attempted"]),
        remaining_tool_calls=data["remaining_tool_calls"], remaining_decisions=data["remaining_decisions"],
        terminal_status=data["terminal_status"], terminal_reason=data["terminal_reason"], terminal_action=data["terminal_action"],
        cited_evidence_ids=list(data["cited_evidence_ids"]), rejection_feedback=list(data["rejection_feedback"]),
    )
    state.decision_count = state.max_decisions - state.remaining_decisions
    return state


def _json_state(state: EpisodeState) -> dict[str, Any]:
    """Return the exact list-shaped state representation used in JSONL traces."""
    return json.loads(json.dumps(state.as_dict(), ensure_ascii=False))


def replay_trace(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate recorded state transitions without invoking a policy or model."""
    if not events:
        raise ValueError("trace is empty")
    events = json.loads(json.dumps(events, ensure_ascii=False))
    episode_id = events[0].get("episode_id")
    initial = _restore_state(events[0]["visible_state_before"])
    if initial.observations or initial.actions_attempted or initial.decision_count:
        raise ValueError("trace does not start from an empty episode state")
    state = initial
    terminal_seen = False
    next_step = 1
    for event in events:
        if event.get("episode_id") != episode_id or event.get("step_id") != next_step:
            raise ValueError("trace episode or step IDs are inconsistent")
        next_step += 1
        if event.get("visible_state_before") != _json_state(state):
            raise ValueError("trace visible-state transition does not match prior event")
        if terminal_seen:
            raise ValueError("trace contains events after terminal state")
        event_type = event.get("event_type")
        if event_type == "termination":
            if state.remaining_decisions > 0 or event["acceptance"]["reason"] != "exhausted_budget":
                raise ValueError("invalid budget termination event")
            _finish(state, "exhausted_budget")
            terminal_seen = True
        elif event_type == "decision":
            if state.remaining_decisions <= 0:
                raise ValueError("decision made after decision budget expired")
            eligible = eligible_actions(state)
            if event.get("eligible_actions") != list(eligible):
                raise ValueError("trace eligible actions do not match visible state")
            state.remaining_decisions -= 1
            state.decision_count += 1
            acceptance = event["acceptance"]
            proposal, malformed = _decode_proposal(event.get("proposal"))
            if acceptance.get("accepted"):
                if malformed or proposal is None or proposal.action_id not in eligible:
                    raise ValueError("trace accepted a malformed or ineligible proposal")
                if proposal.scores and _validate_scores(proposal, eligible):
                    raise ValueError("trace accepted malformed model scores")
                if proposal.action_id in TOOL_ACTIONS:
                    if proposal.evidence_ids or state.remaining_tool_calls <= 0:
                        raise ValueError("trace accepted a disallowed tool action")
                    observation = event.get("tool_observation")
                    if not isinstance(observation, dict) or observation.get("tool_name") != proposal.action_id:
                        raise ValueError("trace tool observation does not match the accepted tool")
                    if observation.get("status") not in {"success", "timeout", "error"}:
                        raise ValueError("trace has invalid tool status")
                    if observation.get("observation_id") in {obs["observation_id"] for obs in state.observations}:
                        raise ValueError("trace reuses an observation ID")
                    state.actions_attempted.append(proposal.action_id)
                    state.remaining_tool_calls -= 1
                    state.observations.append(copy.deepcopy(observation))
                elif proposal.action_id == "request_review":
                    seen = {obs["observation_id"] for obs in state.observations}
                    if any(ref not in seen for ref in proposal.evidence_ids):
                        raise ValueError("trace review cites unseen evidence")
                    _finish(state, "review", proposal.action_id, proposal.evidence_ids)
                    terminal_seen = True
                else:
                    passed, _reason, support_ids = check_terminal_evidence(state, proposal.action_id)
                    cited = list(proposal.evidence_ids) if proposal.evidence_ids else support_ids
                    if not passed or any(ref not in support_ids for ref in cited):
                        raise ValueError("trace accepted an unsupported diagnosis")
                    _finish(state, "completed", proposal.action_id, cited)
                    terminal_seen = True
            else:
                reason = acceptance.get("reason")
                if reason == "unsupported_diagnosis":
                    if malformed or proposal is None or proposal.action_id not in TERMINAL_ACTIONS[:-1]:
                        raise ValueError("trace rejected non-diagnosis as unsupported")
                    passed, actual_reason, support_ids = check_terminal_evidence(state, proposal.action_id)
                    if passed or acceptance.get("evidence_check_reason") != actual_reason or acceptance.get("detail") != f"proposed diagnosis does not support: {actual_reason}" or acceptance.get("deterministic_supporting_evidence_ids") != support_ids:
                        raise ValueError("trace evidence rejection does not match visible evidence")
                    state.unsupported_diagnosis_proposals += 1
                    state.rejection_feedback.append(actual_reason)
                    if state.recovery_attempts >= MAX_EVIDENCE_RECOVERY_ATTEMPTS:
                        _finish(state, "invalid_proposal")
                        terminal_seen = True
                    else:
                        state.recovery_attempts += 1
                elif reason == "tool_execution_failure":
                    if malformed or proposal is None or proposal.action_id not in TOOL_ACTIONS:
                        raise ValueError("trace tool failure is not attached to a tool proposal")
                    state.actions_attempted.append(proposal.action_id)
                    state.remaining_tool_calls -= 1
                    _finish(state, "tool_failure")
                    terminal_seen = True
                elif reason == "tool_call_budget_exhausted":
                    _finish(state, "exhausted_budget")
                    terminal_seen = True
                else:
                    state.invalid_proposals_rejected += 1
                    _finish(state, "invalid_proposal")
                    terminal_seen = True
        else:
            raise ValueError("unknown trace event type")
        if event.get("visible_state_after") != _json_state(state):
            raise ValueError("trace post-event state does not match replayed transition")
        expected_budgets = {"tool_calls": state.remaining_tool_calls, "decisions": state.remaining_decisions}
        if event.get("remaining_budgets") != expected_budgets:
            raise ValueError("trace remaining budgets do not match replay")
        expected_terminal = None if state.terminal_reason is None else {"action_id": state.terminal_action, "reason": state.terminal_reason, "status": state.terminal_status, "cited_evidence_ids": state.cited_evidence_ids}
        if event.get("terminal_decision") != expected_terminal:
            raise ValueError("trace terminal decision does not match replay")
    if not terminal_seen:
        raise ValueError("trace is incomplete and has no terminal event")
    return {"episode_id": episode_id, "terminal_action": state.terminal_action, "terminal_reason": state.terminal_reason,
            "tool_call_count": state.tool_call_count, "decision_count": state.decision_count, "cited_evidence_ids": list(state.cited_evidence_ids),
            "final_state": state.as_dict()}
