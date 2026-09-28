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
    scored_candidate_ids: tuple[str, ...] | None = None
    excluded_candidates: dict[str, str] = field(default_factory=dict)
    native_metadata: dict[str, Any] | None = None
    policy_input: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProposalValidation:
    proposal: Proposal | None
    outcome: str
    acceptance: dict[str, Any]
    invalid_proposal: bool = False
    supporting_evidence_ids: tuple[str, ...] = ()
    cited_evidence_ids: tuple[str, ...] = ()


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


class PolicyExecutionFailure(RuntimeError):
    """Model failure that retains the attempted input, candidates, and native output."""

    def __init__(self, message: str, policy_input: dict[str, Any], scored_candidate_ids: tuple[str, ...],
                 excluded_candidates: dict[str, str], native_output: Any):
        super().__init__(message)
        self.policy_input = copy.deepcopy(policy_input)
        self.scored_candidate_ids = tuple(scored_candidate_ids)
        self.excluded_candidates = copy.deepcopy(excluded_candidates)
        self.native_output = copy.deepcopy(native_output)


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
        return {
            "action_id": proposal.action_id,
            "evidence_ids": list(proposal.evidence_ids),
            "scores": proposal.scores,
            "scored_candidate_ids": None if proposal.scored_candidate_ids is None else list(proposal.scored_candidate_ids),
            "excluded_candidates": copy.deepcopy(proposal.excluded_candidates),
            "native_metadata": copy.deepcopy(proposal.native_metadata),
        }
    if isinstance(proposal, dict):
        return copy.deepcopy(proposal)
    if isinstance(proposal, (str, int, float, bool)) or proposal is None:
        return proposal
    return repr(proposal)


def _decode_proposal(raw: Any) -> tuple[Proposal | None, str | None]:
    if isinstance(raw, Proposal):
        proposal = raw
    elif isinstance(raw, dict) and set(raw) <= {"action_id", "evidence_ids", "scores", "scored_candidate_ids", "excluded_candidates", "native_metadata"} and "action_id" in raw:
        evidence = raw.get("evidence_ids", ())
        if not isinstance(evidence, (tuple, list)) or not all(isinstance(value, str) for value in evidence):
            return None, "malformed_evidence_references"
        scores = raw.get("scores")
        if scores is not None and not isinstance(scores, dict):
            return None, "malformed_scores"
        scored_ids = raw.get("scored_candidate_ids")
        if scored_ids is not None and (not isinstance(scored_ids, (tuple, list)) or not all(isinstance(value, str) for value in scored_ids)):
            return None, "malformed_scored_candidate_ids"
        excluded = raw.get("excluded_candidates", {})
        if not isinstance(excluded, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in excluded.items()):
            return None, "malformed_excluded_candidates"
        native_metadata = raw.get("native_metadata")
        if native_metadata is not None and not isinstance(native_metadata, dict):
            return None, "malformed_native_metadata"
        if native_metadata is not None:
            try:
                json.dumps(native_metadata, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError):
                return None, "malformed_native_metadata"
        proposal = Proposal(raw["action_id"], tuple(evidence), scores, None if scored_ids is None else tuple(scored_ids), excluded, native_metadata)
    else:
        return None, "malformed_proposal"
    if not isinstance(proposal.action_id, str):
        return None, "malformed_action_id"
    if proposal.native_metadata is not None:
        if not isinstance(proposal.native_metadata, dict):
            return None, "malformed_native_metadata"
        try:
            json.dumps(proposal.native_metadata, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return None, "malformed_native_metadata"
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
        proposal = Proposal(proposal.action_id, tuple(proposal.evidence_ids), values, proposal.scored_candidate_ids,
                            proposal.excluded_candidates, proposal.native_metadata, proposal.policy_input)
    if proposal.scored_candidate_ids is not None and (not all(isinstance(value, str) for value in proposal.scored_candidate_ids) or len(set(proposal.scored_candidate_ids)) != len(proposal.scored_candidate_ids)):
        return None, "malformed_scored_candidate_ids"
    if not isinstance(proposal.excluded_candidates, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in proposal.excluded_candidates.items()):
        return None, "malformed_excluded_candidates"
    return proposal, None


def _validate_scores(proposal: Proposal, eligible: tuple[str, ...], require_complete_metadata: bool = True) -> str | None:
    if proposal.scores is None and proposal.scored_candidate_ids is None:
        return None
    scored = tuple(proposal.scored_candidate_ids) if proposal.scored_candidate_ids is not None else tuple(proposal.scores)
    if not set(scored) <= set(eligible):
        return "scored_candidates_include_harness_disallowed_actions"
    if proposal.action_id not in scored:
        return "selected_action_not_scored"
    if proposal.scores is None:
        if require_complete_metadata:
            if set(scored) & set(proposal.excluded_candidates):
                return "scored_candidates_cannot_also_be_excluded"
            if set(scored) | set(proposal.excluded_candidates) != set(ACTION_IDS):
                return "candidate_exclusions_must_account_for_every_action"
        return None
    if set(proposal.scores) != set(scored):
        return "model_scores_must_cover_exactly_scored_candidates"
    if require_complete_metadata:
        if set(scored) & set(proposal.excluded_candidates):
            return "scored_candidates_cannot_also_be_excluded"
        if set(scored) | set(proposal.excluded_candidates) != set(ACTION_IDS):
            return "candidate_exclusions_must_account_for_every_action"
    if abs(sum(proposal.scores.values()) - 1.0) > 0.01:
        return "model_action_scores_do_not_sum_to_one"
    if proposal.scores[proposal.action_id] + 0.0011 < max(proposal.scores.values()):
        return "selected_action_disagrees_with_largest_score"
    return None


def _validate_proposal(
    state: EpisodeState,
    raw: Any,
    eligible: tuple[str, ...],
    *,
    trace_version: int = 3,
    malformed_reason: str | None = None,
) -> ProposalValidation:
    """Classify a proposal using only deterministic harness state and rules."""
    proposal, decoded_reason = _decode_proposal(raw)
    malformed_reason = malformed_reason or decoded_reason
    if malformed_reason:
        return ProposalValidation(
            proposal, "invalid", {"accepted": False, "reason": malformed_reason, "detail": "proposal could not be parsed"},
            invalid_proposal=True,
        )
    assert proposal is not None
    action_id = proposal.action_id
    if action_id not in ACTION_KIND:
        return ProposalValidation(
            proposal, "invalid", {"accepted": False, "reason": "unknown_action", "detail": f"unknown action {action_id!r}"},
            invalid_proposal=True,
        )
    if action_id not in eligible:
        if action_id in TOOL_ACTIONS and state.remaining_tool_calls <= 0:
            return ProposalValidation(
                proposal, "exhausted", {"accepted": False, "reason": "tool_call_budget_exhausted", "detail": "tool call budget is zero"},
            )
        reason = "tool_already_attempted" if action_id in state.actions_attempted else "action_not_eligible"
        return ProposalValidation(
            proposal, "invalid", {"accepted": False, "reason": reason, "detail": f"{action_id} is not currently eligible"},
            invalid_proposal=True,
        )
    score_error = _validate_scores(proposal, eligible, require_complete_metadata=trace_version in {2, 3})
    if score_error:
        return ProposalValidation(
            proposal, "invalid", {"accepted": False, "reason": "malformed_scores", "detail": score_error}, invalid_proposal=True,
        )
    seen = {obs["observation_id"] for obs in state.observations}
    if any(ref not in seen for ref in proposal.evidence_ids):
        return ProposalValidation(
            proposal, "invalid", {"accepted": False, "reason": "unseen_evidence_reference", "detail": "proposal cited evidence not present in visible state"},
            invalid_proposal=True,
        )
    if action_id in TOOL_ACTIONS:
        if proposal.evidence_ids:
            return ProposalValidation(
                proposal, "invalid", {"accepted": False, "reason": "tool_action_cannot_cite_terminal_evidence", "detail": "evidence references are only valid on terminal proposals"},
                invalid_proposal=True,
            )
        return ProposalValidation(proposal, "tool", {"accepted": True, "reason": "tool_observation_recorded"})
    if action_id == "request_review":
        return ProposalValidation(
            proposal, "review", {"accepted": True, "reason": "review_requested", "detail": "review is always an available terminal choice"},
            cited_evidence_ids=proposal.evidence_ids,
        )

    passed, reason, support_ids = check_terminal_evidence(state, action_id)
    cited_ids = tuple(proposal.evidence_ids) if proposal.evidence_ids else tuple(support_ids)
    if any(ref not in support_ids for ref in cited_ids):
        passed, reason = False, "cited_observation_does_not_support_proposed_diagnosis"
    if passed:
        return ProposalValidation(
            proposal, "diagnosis", {"accepted": True, "reason": "diagnosis_supported", "detail": reason},
            supporting_evidence_ids=tuple(support_ids), cited_evidence_ids=cited_ids,
        )
    return ProposalValidation(
        proposal, "unsupported_diagnosis",
        {
            "accepted": False,
            "reason": "unsupported_diagnosis",
            "detail": f"proposed diagnosis does not support: {reason}",
            "evidence_check_reason": reason,
            "deterministic_supporting_evidence_ids": support_ids,
        },
        supporting_evidence_ids=tuple(support_ids), cited_evidence_ids=cited_ids,
    )


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
    policy_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal_data = _proposal_dict(proposal)
    if isinstance(proposal_data, dict):
        scored_candidate_ids = proposal_data.get("scored_candidate_ids")
        if scored_candidate_ids is None:
            scores = proposal_data.get("scores")
            scored_candidate_ids = list(scores) if isinstance(scores, dict) else []
        excluded_candidates = proposal_data.get("excluded_candidates") or {}
    else:
        scored_candidate_ids, excluded_candidates = [], {}
    return {
        "trace_version": 3, "event_type": event_type, "episode_id": episode_id, "step_id": step_id,
        "visible_state_before": before, "eligible_actions": list(eligible),
        "policy_input": copy.deepcopy(policy_input),
        "scored_candidate_ids": scored_candidate_ids,
        "excluded_candidates": copy.deepcopy(excluded_candidates),
        "proposal": proposal_data, "acceptance": acceptance,
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
        policy_state = state.visible()
        policy_input = {"visible_state": policy_state.as_dict(), "eligible_action_ids": list(eligible)}
        try:
            raw = policy.propose(policy_state, eligible)
        except Exception as exc:
            raw = {"policy_error": f"{type(exc).__name__}: {exc}"}
            if isinstance(exc, PolicyExecutionFailure):
                policy_input.update(exc.policy_input)
                raw.update({
                    "scored_candidate_ids": list(exc.scored_candidate_ids),
                    "excluded_candidates": exc.excluded_candidates,
                    "native_output": exc.native_output,
                })
            proposal, malformed_reason = None, "policy_execution_error"
        else:
            proposal, malformed_reason = _decode_proposal(raw)
            if proposal is not None and proposal.policy_input is not None:
                policy_input.update(copy.deepcopy(proposal.policy_input))
        validation = _validate_proposal(state, raw, eligible, malformed_reason=malformed_reason)
        proposal = validation.proposal
        acceptance = validation.acceptance
        observation = None
        if validation.outcome == "invalid":
            if validation.invalid_proposal:
                state.invalid_proposals_rejected += 1
            _finish(state, "invalid_proposal")
        elif validation.outcome == "exhausted":
            _finish(state, "exhausted_budget")
        elif validation.outcome == "tool":
            assert proposal is not None
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
        elif validation.outcome == "review":
            assert proposal is not None
            _finish(state, "review", "request_review", validation.cited_evidence_ids)
        elif validation.outcome == "diagnosis":
            assert proposal is not None
            _finish(state, "completed", proposal.action_id, validation.cited_evidence_ids)
        elif validation.outcome == "unsupported_diagnosis":
            state.unsupported_diagnosis_proposals += 1
            state.rejection_feedback.append(validation.acceptance["evidence_check_reason"])
            if state.recovery_attempts >= MAX_EVIDENCE_RECOVERY_ATTEMPTS:
                _finish(state, "invalid_proposal")
            else:
                state.recovery_attempts += 1
        else:
            raise RuntimeError(f"unhandled proposal validation outcome: {validation.outcome}")
        trace.append(_make_event(episode_id, state.decision_count, before, eligible, raw, acceptance, observation, state, policy_input=policy_input))

    return EpisodeResult(
        episode_id=episode_id, terminal_status=state.terminal_status, terminal_reason=state.terminal_reason or "tool_failure",
        terminal_action=state.terminal_action, cited_evidence_ids=tuple(state.cited_evidence_ids),
        observations=tuple(copy.deepcopy(state.observations)), trace=tuple(trace), tool_call_count=state.tool_call_count,
        decision_count=state.decision_count, unsupported_diagnosis_proposals=state.unsupported_diagnosis_proposals,
        invalid_proposals_rejected=state.invalid_proposals_rejected, end_to_end_seconds=time.perf_counter() - start,
        model_loading_seconds=float(getattr(policy, "load_seconds", 0.0)), simulator_failure=simulator_failure, final_state=state,
    )


def _restore_state(data: dict[str, Any]) -> EpisodeState:
    if not isinstance(data, dict):
        raise ValueError("trace visible state must be an object")
    allowed = set(VisibleState.__dataclass_fields__)
    if set(data) != allowed:
        raise ValueError("trace visible state has unexpected or missing fields")
    integer_fields = ("max_tool_calls", "max_decisions", "remaining_tool_calls", "remaining_decisions")
    if any(not isinstance(data[field], int) or isinstance(data[field], bool) for field in integer_fields):
        raise ValueError("trace visible state budgets must be integers")
    if any(data[field] < 0 for field in integer_fields) or data["remaining_tool_calls"] > data["max_tool_calls"] or data["remaining_decisions"] > data["max_decisions"]:
        raise ValueError("trace visible state budgets are out of range")
    if not isinstance(data["initial_report"], str):
        raise ValueError("trace visible state report must be text")
    if not isinstance(data["observations"], list) or not all(isinstance(obs, dict) for obs in data["observations"]):
        raise ValueError("trace visible state observations must be objects")
    if not isinstance(data["actions_attempted"], list) or not all(isinstance(action_id, str) for action_id in data["actions_attempted"]):
        raise ValueError("trace visible state attempted actions must be strings")
    if not isinstance(data["rejection_feedback"], list) or not all(isinstance(reason, str) for reason in data["rejection_feedback"]):
        raise ValueError("trace visible state rejection feedback must be strings")
    if not isinstance(data["cited_evidence_ids"], list) or not all(isinstance(ref, str) for ref in data["cited_evidence_ids"]):
        raise ValueError("trace visible state evidence citations must be strings")
    if data["terminal_status"] != "in_progress" or data["terminal_reason"] is not None or data["terminal_action"] is not None:
        raise ValueError("trace initial state is already terminal")
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
    if not isinstance(events, list) or not events:
        raise ValueError("trace is empty")
    try:
        events = json.loads(json.dumps(events, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("trace contains non-JSON data") from exc
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise ValueError(f"event {index}: expected an object")
    versions = set()
    for index, event in enumerate(events, 1):
        version = event.get("trace_version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError(f"event {index}: trace version must be an integer")
        versions.add(version)
    if not versions <= {1, 2, 3} or len(versions) != 1:
        raise ValueError("trace contains an unsupported or mixed format version")
    trace_version = next(iter(versions))
    episode_id = events[0].get("episode_id")
    try:
        initial = _restore_state(events[0]["visible_state_before"])
    except ValueError as exc:
        raise ValueError(f"event 1: {exc}") from exc
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"event 1: malformed initial state ({type(exc).__name__})") from exc
    if initial.observations or initial.actions_attempted or initial.decision_count:
        raise ValueError("event 1: trace does not start from an empty episode state")
    state = initial
    terminal_seen = False
    next_step = 1
    for event in events:
        event_number = next_step
        try:
            step_id = event.get("step_id")
            if event.get("episode_id") != episode_id or not isinstance(step_id, int) or isinstance(step_id, bool) or step_id != next_step:
                raise ValueError("trace episode or step IDs are inconsistent")
            next_step += 1
            if event.get("visible_state_before") != _json_state(state):
                raise ValueError("trace visible-state transition does not match prior event")
            if terminal_seen:
                raise ValueError("trace contains events after terminal state")
            event_type = event.get("event_type")
            if event_type == "termination":
                no_decisions = state.remaining_decisions <= 0
                no_actions = not eligible_actions(state)
                expected_detail = "decision budget exhausted" if no_decisions else "no eligible actions remain"
                expected_acceptance = {"accepted": False, "reason": "exhausted_budget", "detail": expected_detail}
                if (not no_decisions and not no_actions) or event.get("eligible_actions") != list(eligible_actions(state)):
                    raise ValueError("trace termination does not follow exhausted budgets or actions")
                if event.get("proposal") is not None or event.get("acceptance") != expected_acceptance:
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
                if trace_version in {2, 3}:
                    expected_policy_input = {"visible_state": _json_state(state), "eligible_action_ids": list(eligible)}
                    recorded_policy_input = event.get("policy_input")
                    if not isinstance(recorded_policy_input, dict) or any(recorded_policy_input.get(key) != value for key, value in expected_policy_input.items()):
                        raise ValueError("trace policy input does not match the actual decision state")
                    if trace_version == 2 and recorded_policy_input != expected_policy_input:
                        raise ValueError("version 2 policy input has unexpected fields")
                    if trace_version == 3:
                        model_family = recorded_policy_input.get("model_family")
                        if model_family is None:
                            if set(recorded_policy_input) != set(expected_policy_input):
                                raise ValueError("trace policy input has unexpected fields")
                        elif model_family in {"gliclass", "laya"}:
                            from .workflow_policies import build_laya_workflow_question, render_visible_state
                            if recorded_policy_input.get("state_text") != render_visible_state(state.visible()):
                                raise ValueError("trace model state text does not match visible state")
                            proposal_for_input, _malformed_for_input = _decode_proposal(event.get("proposal"))
                            if proposal_for_input is not None and proposal_for_input.scored_candidate_ids is not None:
                                candidate_ids = tuple(proposal_for_input.scored_candidate_ids)
                            elif event["acceptance"].get("reason") == "policy_execution_error":
                                candidate_ids = tuple(event.get("scored_candidate_ids", ()))
                            else:
                                raise ValueError("trace model input has no scored candidates")
                            if model_family == "gliclass":
                                expected_candidates = [{"id": action_id, "name": ACTION_NAMES[action_id]} for action_id in candidate_ids]
                                if recorded_policy_input.get("candidates") != expected_candidates or set(recorded_policy_input) != set(expected_policy_input) | {"model_family", "state_text", "candidates"}:
                                    raise ValueError("trace GLiClass candidate input does not match scored candidates")
                            else:
                                if recorded_policy_input.get("question") != build_laya_workflow_question(candidate_ids) or set(recorded_policy_input) != set(expected_policy_input) | {"model_family", "state_text", "question"}:
                                    raise ValueError("trace Laya question does not match scored candidates")
                        else:
                            raise ValueError("trace model input names an unsupported model family")
                    scored_ids = event.get("scored_candidate_ids")
                    excluded = event.get("excluded_candidates")
                    proposal_for_metadata, _metadata_error = _decode_proposal(event.get("proposal"))
                    if not isinstance(scored_ids, list) or not all(isinstance(action_id, str) for action_id in scored_ids):
                        raise ValueError("trace scored candidates are malformed")
                    if proposal_for_metadata is not None:
                        if len(set(scored_ids)) != len(scored_ids):
                            raise ValueError("trace scored candidates are malformed")
                        if not isinstance(excluded, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in excluded.items()):
                            raise ValueError("trace candidate exclusions are malformed")
                        if set(scored_ids) & set(excluded):
                            raise ValueError("trace candidates are both scored and excluded")
                acceptance = event["acceptance"]
                if not isinstance(acceptance, dict) or not isinstance(acceptance.get("accepted"), bool):
                    raise ValueError("trace acceptance is malformed")
                raw_proposal = event.get("proposal")
                proposal, malformed = _decode_proposal(raw_proposal)
                policy_failure = (
                    acceptance.get("reason") == "policy_execution_error"
                    and isinstance(raw_proposal, dict)
                    and isinstance(raw_proposal.get("policy_error"), str)
                )
                if trace_version in {2, 3} and proposal is not None:
                    proposal_scores = list(proposal.scored_candidate_ids) if proposal.scored_candidate_ids is not None else list(proposal.scores or {})
                    if proposal_scores != event["scored_candidate_ids"] or proposal.excluded_candidates != event["excluded_candidates"]:
                        raise ValueError("trace candidate metadata differs from the recorded proposal")
                    if trace_version == 3 and event["policy_input"].get("model_family") == "laya":
                        metadata = proposal.native_metadata
                        if not isinstance(metadata, dict):
                            raise ValueError("trace Laya proposal has no native output metadata")
                        choice = metadata.get("choice")
                        if isinstance(choice, str):
                            selected_id = next((action_id for action_id in proposal_scores if ACTION_NAMES[action_id] == choice), None)
                        elif isinstance(choice, int) and not isinstance(choice, bool) and 0 <= choice < len(proposal_scores):
                            selected_id = proposal_scores[choice]
                        else:
                            selected_id = None
                        if selected_id != proposal.action_id:
                            raise ValueError("trace Laya choice does not match the selected action ID")
                        native_probabilities = metadata.get("probabilities")
                        if isinstance(native_probabilities, dict):
                            native_scores = {
                                next((action_id for action_id in proposal_scores if ACTION_NAMES[action_id] == name), ""): float(value)
                                for name, value in native_probabilities.items()
                            }
                        elif isinstance(native_probabilities, (list, tuple)) and len(native_probabilities) == len(proposal_scores):
                            native_scores = {action_id: float(value) for action_id, value in zip(proposal_scores, native_probabilities, strict=True)}
                        else:
                            native_scores = {}
                        if native_scores != proposal.scores:
                            raise ValueError("trace native Laya probabilities do not match canonical policy scores")
                validation = _validate_proposal(
                    state,
                    raw_proposal,
                    eligible,
                    trace_version=trace_version,
                    malformed_reason="policy_execution_error" if policy_failure else None,
                )
                if acceptance["accepted"]:
                    if validation.outcome == "tool":
                        observation = event.get("tool_observation")
                        if not isinstance(observation, dict) or observation.get("tool_name") != validation.proposal.action_id:
                            raise ValueError("accepted tool proposal has no matching observation")
                        if observation.get("status") not in {"success", "timeout", "error"}:
                            raise ValueError("accepted tool proposal has an invalid observation status")
                        expected_acceptance = {"accepted": True, "reason": "tool_observation_recorded", "detail": observation["status"]}
                        if acceptance != expected_acceptance:
                            raise ValueError("accepted tool proposal has an inconsistent outcome")
                        observation_id = observation.get("observation_id")
                        if not isinstance(observation_id, str) or not observation_id or observation_id in {obs["observation_id"] for obs in state.observations}:
                            raise ValueError("accepted tool proposal has an invalid or repeated observation ID")
                        if not isinstance(observation.get("facts"), dict) or observation.get("time_scope") not in {"current", "historical"}:
                            raise ValueError("accepted tool observation facts or time scope are malformed")
                        if not isinstance(observation.get("observed_at"), str) or not isinstance(observation.get("message"), str):
                            raise ValueError("accepted tool observation metadata are malformed")
                        state.actions_attempted.append(validation.proposal.action_id)
                        state.remaining_tool_calls -= 1
                        state.observations.append(copy.deepcopy(observation))
                    elif validation.outcome in {"review", "diagnosis"}:
                        if acceptance != validation.acceptance:
                            raise ValueError("accepted terminal proposal disagrees with deterministic validation")
                        _finish(
                            state,
                            "review" if validation.outcome == "review" else "completed",
                            validation.proposal.action_id,
                            validation.cited_evidence_ids,
                        )
                        terminal_seen = True
                    else:
                        raise ValueError("trace accepts a proposal rejected by deterministic validation")
                elif validation.outcome == "tool" and acceptance.get("reason") == "tool_execution_failure":
                    if acceptance.get("detail") is None or not isinstance(acceptance.get("detail"), str) or event.get("tool_observation") is not None:
                        raise ValueError("recorded tool failure has malformed failure details")
                    if set(acceptance) != {"accepted", "reason", "detail"}:
                        raise ValueError("recorded tool failure has unexpected acceptance fields")
                    state.actions_attempted.append(validation.proposal.action_id)
                    state.remaining_tool_calls -= 1
                    _finish(state, "tool_failure")
                    terminal_seen = True
                else:
                    if acceptance != validation.acceptance:
                        raise ValueError(
                            f"recorded rejection reason {acceptance.get('reason')!r} "
                            f"does not match expected {validation.acceptance.get('reason')!r}"
                        )
                    if validation.outcome == "invalid":
                        state.invalid_proposals_rejected += 1
                        _finish(state, "invalid_proposal")
                        terminal_seen = True
                    elif validation.outcome == "exhausted":
                        _finish(state, "exhausted_budget")
                        terminal_seen = True
                    elif validation.outcome == "unsupported_diagnosis":
                        state.unsupported_diagnosis_proposals += 1
                        state.rejection_feedback.append(validation.acceptance["evidence_check_reason"])
                        if state.recovery_attempts >= MAX_EVIDENCE_RECOVERY_ATTEMPTS:
                            _finish(state, "invalid_proposal")
                            terminal_seen = True
                        else:
                            state.recovery_attempts += 1
                    else:
                        raise ValueError("recorded rejection does not describe a rejected proposal")
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
        except ValueError as exc:
            raise ValueError(f"event {event_number}: {exc}") from exc
        except (KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ValueError(f"event {event_number}: malformed trace fields ({type(exc).__name__})") from exc
    if not terminal_seen:
        raise ValueError("trace is incomplete and has no terminal event")
    return {"episode_id": episode_id, "terminal_action": state.terminal_action, "terminal_reason": state.terminal_reason,
            "tool_call_count": state.tool_call_count, "decision_count": state.decision_count, "cited_evidence_ids": list(state.cited_evidence_ids),
            "final_state": state.as_dict()}
