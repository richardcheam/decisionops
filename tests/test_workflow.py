import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from decisionops.workflow import (
    ACTION_IDS,
    DEFAULT_MAX_DECISIONS,
    DEFAULT_MAX_TOOL_CALLS,
    Proposal,
    ToolExecutionError,
    VisibleState,
    eligible_actions,
    replay_trace,
    run_episode,
)
from decisionops.workflow_eval import summarize_results
from decisionops.workflow_policies import FixedOrderPolicy, GLiClassPolicy
from decisionops.workflow_scenarios import load_scenarios
from decisionops.backends import canonicalize_named_scores


class FakePolicy:
    name = "fake"
    load_seconds = 0.0

    def __init__(self, proposals):
        self.proposals = iter(proposals)
        self.visible_states = []

    def propose(self, state, eligible):
        self.visible_states.append((state, tuple(eligible)))
        proposal = next(self.proposals, Proposal("request_review"))
        if isinstance(proposal, Exception):
            raise proposal
        return proposal


class FakeRanker:
    load_seconds = 0.0

    def __init__(self, preferred_actions=()):
        self.preferred_actions = list(preferred_actions)
        self.inputs = []
        self.candidate_ids = []

    def rank(self, text, candidates):
        ids = tuple(candidate_id for candidate_id, _name in candidates)
        self.inputs.append(text)
        self.candidate_ids.append(ids)
        preferred = self.preferred_actions[len(self.inputs) - 1] if len(self.inputs) <= len(self.preferred_actions) else None
        selected = preferred if preferred in ids else ids[0]
        return {candidate_id: (1.0 if len(ids) == 1 else 0.9 if candidate_id == selected else 0.1 / (len(ids) - 1)) for candidate_id in ids}


def empty_visible_state(**overrides):
    state = {
        "initial_report": "a service request failed",
        "observations": (),
        "actions_attempted": (),
        "remaining_tool_calls": 4,
        "max_tool_calls": 4,
        "remaining_decisions": 6,
        "max_decisions": 6,
    }
    state.update(overrides)
    return VisibleState(**state)


class WorkflowFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = {scenario.scenario_id: scenario for scenario in load_scenarios()}

    def test_scenario_suite_has_frozen_balanced_splits(self):
        scenarios = load_scenarios()
        self.assertEqual(len(scenarios), 24)
        self.assertEqual(sum(scenario.split == "development" for scenario in scenarios), 12)
        self.assertEqual(sum(scenario.split == "evaluation" for scenario in scenarios), 12)

    def test_named_action_scores_map_to_stable_ids_in_non_default_order(self):
        scores = canonicalize_named_scores({"Request review": 0.7, "Check database": 0.3}, ("request_review", "check_database"), ("Request review", "Check database"))
        self.assertEqual(scores, {"request_review": 0.7, "check_database": 0.3})

    def test_policy_sees_only_requested_observations_and_public_state(self):
        scenario = self.scenarios["dev-database-clear"]
        policy = FakePolicy([Proposal("request_review")])
        result = run_episode(scenario, policy, episode_id="dev-001")
        state, _eligible = policy.visible_states[0]
        self.assertEqual(state.initial_report, scenario.initial_report)
        self.assertEqual(state.observations, ())
        self.assertFalse(hasattr(state, "scenario_id"))
        self.assertFalse(hasattr(state, "gold_terminal_action"))
        self.assertFalse(hasattr(state, "fixtures"))
        self.assertNotIn("scenario_id", result.trace[0]["visible_state_before"])

    def test_eligible_actions_exclude_repeated_tools_and_keep_terminals(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("request_review")])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        second_eligible = policy.visible_states[1][1]
        self.assertNotIn("check_database", second_eligible)
        self.assertIn("request_review", second_eligible)
        self.assertEqual(DEFAULT_MAX_TOOL_CALLS, 4)
        self.assertEqual(DEFAULT_MAX_DECISIONS, 6)
        self.assertEqual(set(ACTION_IDS) - {"check_database"}, set(eligible_actions(result.final_state)))

    def test_repeated_tool_proposal_is_rejected_and_terminates(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("check_database")])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        self.assertEqual(result.terminal_reason, "invalid_proposal")
        self.assertEqual(result.invalid_proposals_rejected, 1)
        self.assertEqual(result.trace[-1]["acceptance"]["reason"], "tool_already_attempted")
        self.assertEqual(replay_trace(json.loads(json.dumps(result.trace)))["terminal_reason"], "invalid_proposal")

    def test_tool_call_budget_is_enforced(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("check_authentication")])
        result = run_episode(self.scenarios["dev-database-clear"], policy, max_tool_calls=1)
        self.assertEqual(result.terminal_reason, "exhausted_budget")
        self.assertEqual(result.tool_call_count, 1)
        self.assertEqual(replay_trace(json.loads(json.dumps(result.trace)))["terminal_reason"], "exhausted_budget")

    def test_decision_budget_guarantees_termination(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("check_authentication"), Proposal("check_storage")])
        result = run_episode(self.scenarios["dev-database-clear"], policy, max_decisions=1)
        self.assertEqual(result.terminal_reason, "exhausted_budget")
        self.assertLessEqual(result.decision_count, 1)
        self.assertEqual(replay_trace(json.loads(json.dumps(result.trace)))["terminal_reason"], "exhausted_budget")

    def test_timeout_is_visible_observation_and_review_is_allowed(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("request_review")])
        result = run_episode(self.scenarios["dev-database-timeout"], policy)
        self.assertEqual(result.terminal_action, "request_review")
        self.assertEqual(result.terminal_reason, "review")
        self.assertEqual(result.observations[0]["status"], "timeout")
        self.assertEqual(policy.visible_states[1][0].observations[0]["status"], "timeout")

    def test_supported_diagnosis_gets_deterministic_visible_evidence_ids(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("diagnose_database_failure")])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        self.assertEqual(result.terminal_reason, "completed")
        self.assertEqual(result.terminal_action, "diagnose_database_failure")
        self.assertEqual(result.cited_evidence_ids, (result.observations[0]["observation_id"],))

    def test_unsupported_diagnosis_is_rejected_without_replacing_with_gold(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("diagnose_disk_full"), Proposal("request_review")])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        self.assertEqual(result.terminal_action, "request_review")
        self.assertEqual(result.unsupported_diagnosis_proposals, 1)
        rejected = next(event for event in result.trace if event["acceptance"]["reason"] == "unsupported_diagnosis")
        self.assertEqual(rejected["proposal"]["action_id"], "diagnose_disk_full")
        self.assertIn("does not support", rejected["acceptance"]["detail"])

    def test_contradictory_observations_reject_diagnosis(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("check_service_health"), Proposal("diagnose_database_failure"), Proposal("request_review")])
        result = run_episode(self.scenarios["dev-contradictory-evidence"], policy)
        self.assertEqual(result.terminal_action, "request_review")
        self.assertEqual(result.unsupported_diagnosis_proposals, 1)

    def test_malformed_and_unknown_actions_are_rejected(self):
        policy = FakePolicy([{"action": "check_database"}])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        self.assertEqual(result.terminal_reason, "invalid_proposal")
        self.assertEqual(result.invalid_proposals_rejected, 1)
        self.assertEqual(replay_trace(json.loads(json.dumps(result.trace)))["terminal_reason"], "invalid_proposal")

        malformed_action = run_episode(
            self.scenarios["dev-database-clear"], FakePolicy([Proposal(None)]),
        )
        self.assertEqual(malformed_action.trace[0]["acceptance"]["reason"], "malformed_action_id")
        self.assertEqual(replay_trace(json.loads(json.dumps(malformed_action.trace)))["terminal_reason"], "invalid_proposal")

    def test_replay_rejects_unknown_action_reason_for_known_review_proposal(self):
        result = run_episode(
            self.scenarios["dev-database-clear"],
            FakePolicy([Proposal("not_an_action")]),
        )
        tampered = json.loads(json.dumps(result.trace))
        tampered[0]["proposal"]["action_id"] = "request_review"

        with self.assertRaisesRegex(ValueError, "event 1.*unknown_action"):
            replay_trace(tampered)

    def test_replay_checks_repeated_tool_and_invalid_score_rejection_reasons(self):
        repeated = run_episode(
            self.scenarios["dev-database-clear"],
            FakePolicy([Proposal("check_database"), Proposal("check_database")]),
        )
        repeated_tampered = json.loads(json.dumps(repeated.trace))
        repeated_tampered[1]["proposal"]["action_id"] = "request_review"
        with self.assertRaisesRegex(ValueError, "event 2.*tool_already_attempted.*review_requested"):
            replay_trace(repeated_tampered)

        invalid_scores = run_episode(
            self.scenarios["dev-database-clear"],
            FakePolicy([Proposal("request_review", scores={"request_review": float("nan")}, scored_candidate_ids=("request_review",))]),
        )
        self.assertEqual(replay_trace(json.loads(json.dumps(invalid_scores.trace)))["terminal_reason"], "invalid_proposal")
        scores_tampered = json.loads(json.dumps(invalid_scores.trace))
        scores_tampered[0]["acceptance"]["reason"] = "unknown_action"
        with self.assertRaisesRegex(ValueError, "event 1.*unknown_action.*malformed_scores"):
            replay_trace(scores_tampered)

    def test_replay_checks_candidate_membership_and_unseen_evidence_reasons(self):
        bad_candidates = Proposal(
            "request_review",
            scores={"request_review": 0.5, "not_eligible": 0.5},
            scored_candidate_ids=("request_review", "not_eligible"),
        )
        result = run_episode(self.scenarios["dev-database-clear"], FakePolicy([bad_candidates]))
        self.assertEqual(result.trace[0]["acceptance"]["reason"], "malformed_scores")
        self.assertEqual(replay_trace(json.loads(json.dumps(result.trace)))["terminal_reason"], "invalid_proposal")

        malformed_candidates = run_episode(
            self.scenarios["dev-database-clear"],
            FakePolicy([Proposal("request_review", scored_candidate_ids=("request_review", "request_review"))]),
        )
        self.assertEqual(malformed_candidates.trace[0]["acceptance"]["reason"], "malformed_scored_candidate_ids")
        self.assertEqual(replay_trace(json.loads(json.dumps(malformed_candidates.trace)))["terminal_reason"], "invalid_proposal")

        unseen = run_episode(
            self.scenarios["dev-database-clear"],
            FakePolicy([Proposal("request_review", evidence_ids=("obs-not-seen",))]),
        )
        self.assertEqual(replay_trace(json.loads(json.dumps(unseen.trace)))["terminal_reason"], "invalid_proposal")

    def test_replay_accepts_authentic_overlap_candidate_rejection_only(self):
        result = run_episode(
            self.scenarios["dev-database-clear"],
            FakePolicy([Proposal(
                "request_review",
                scores={"request_review": 1.0},
                scored_candidate_ids=("request_review",),
                excluded_candidates={action_id: "masked" for action_id in ACTION_IDS},
            )]),
        )
        recorded = result.trace[0]["acceptance"]
        self.assertEqual(recorded["reason"], "malformed_scores")
        self.assertEqual(recorded["detail"], "scored_candidates_cannot_also_be_excluded")
        replayed = replay_trace(json.loads(json.dumps(result.trace)))
        self.assertEqual(replayed["terminal_reason"], "invalid_proposal")

        falsely_accepted = json.loads(json.dumps(result.trace))
        falsely_accepted[0]["acceptance"] = {"accepted": True, "reason": "review_requested", "detail": "review is always an available terminal choice"}
        with self.assertRaisesRegex(ValueError, "event 1: trace accepts a proposal rejected by deterministic validation"):
            replay_trace(falsely_accepted)

        falsely_rejected = json.loads(json.dumps(result.trace))
        falsely_rejected[0]["acceptance"]["reason"] = "unknown_action"
        with self.assertRaisesRegex(ValueError, "event 1.*unknown_action.*malformed_scores"):
            replay_trace(falsely_rejected)

    def test_unseen_evidence_reference_is_rejected(self):
        policy = FakePolicy([Proposal("request_review", evidence_ids=("obs-not-seen",))])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        self.assertEqual(result.terminal_reason, "invalid_proposal")
        self.assertEqual(result.trace[0]["acceptance"]["reason"], "unseen_evidence_reference")

    def test_replay_handles_rejected_diagnosis_recovery(self):
        policy = FakePolicy([
            Proposal("check_database"),
            Proposal("diagnose_disk_full"),
            Proposal("request_review"),
        ])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        replayed = replay_trace(json.loads(json.dumps(result.trace)))
        self.assertEqual(replayed["terminal_action"], "request_review")
        self.assertEqual(replayed["terminal_reason"], "review")

    def test_replay_handles_supported_diagnosis_with_wrong_visible_citation(self):
        policy = FakePolicy([
            Proposal("check_database"),
            Proposal("check_storage"),
            Proposal("diagnose_database_failure", evidence_ids=("obs-02-check_storage",)),
            Proposal("request_review"),
        ])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        rejected = result.trace[2]["acceptance"]
        self.assertEqual(rejected["reason"], "unsupported_diagnosis")
        self.assertEqual(rejected["evidence_check_reason"], "cited_observation_does_not_support_proposed_diagnosis")
        replayed = replay_trace(json.loads(json.dumps(result.trace)))
        self.assertEqual(replayed["terminal_action"], "request_review")
        self.assertEqual(replayed["terminal_reason"], "review")

    def test_replay_handles_tool_failure_and_exhausted_tool_budget(self):
        with patch("decisionops.workflow.RecordedToolEnvironment.execute", side_effect=ToolExecutionError("fixture unavailable")):
            failed_tool = run_episode(
                self.scenarios["dev-database-clear"],
                FakePolicy([Proposal("check_database")]),
            )
        replayed_failure = replay_trace(json.loads(json.dumps(failed_tool.trace)))
        self.assertEqual(replayed_failure["terminal_reason"], "tool_failure")
        self.assertEqual(list(replayed_failure["final_state"]["actions_attempted"]), ["check_database"])
        self.assertEqual(replayed_failure["final_state"]["remaining_tool_calls"], DEFAULT_MAX_TOOL_CALLS - 1)

        exhausted = run_episode(
            self.scenarios["dev-database-clear"],
            FakePolicy([Proposal("check_database")]),
            max_tool_calls=0,
        )
        replayed_budget = replay_trace(json.loads(json.dumps(exhausted.trace)))
        self.assertEqual(replayed_budget["terminal_reason"], "exhausted_budget")
        self.assertEqual(replayed_budget["final_state"]["remaining_tool_calls"], 0)

    def test_valid_terminal_replay_matches_final_budgets_and_evidence(self):
        cases = (
            ("diagnosis", FakePolicy([Proposal("check_database"), Proposal("diagnose_database_failure")])),
            ("review", FakePolicy([Proposal("check_database"), Proposal("request_review", evidence_ids=("obs-01-check_database",))])),
        )
        for name, policy in cases:
            with self.subTest(name=name):
                result = run_episode(self.scenarios["dev-database-clear"], policy, episode_id=f"{name}-episode")
                replayed = replay_trace(json.loads(json.dumps(result.trace)))
                self.assertEqual(replayed["terminal_action"], result.terminal_action)
                self.assertEqual(replayed["terminal_reason"], result.terminal_reason)
                self.assertEqual(replayed["cited_evidence_ids"], list(result.cited_evidence_ids))
                self.assertEqual(
                    json.loads(json.dumps(replayed["final_state"])),
                    json.loads(json.dumps(result.final_state.as_dict())),
                )

    def test_replay_handles_zero_decision_budget_termination(self):
        result = run_episode(
            self.scenarios["dev-database-clear"], FakePolicy([]), max_decisions=0,
        )
        replayed = replay_trace(json.loads(json.dumps(result.trace)))
        self.assertEqual(replayed["terminal_reason"], "exhausted_budget")
        self.assertEqual(replayed["final_state"]["remaining_decisions"], 0)

    def test_replay_errors_include_event_context_for_malformed_fields(self):
        result = run_episode(self.scenarios["dev-database-clear"], FakePolicy([Proposal("request_review")]))
        malformed = json.loads(json.dumps(result.trace))
        del malformed[0]["acceptance"]
        with self.assertRaisesRegex(ValueError, r"event 1: malformed trace fields \(KeyError\)"):
            replay_trace(malformed)

    def test_trace_replay_validates_transitions_without_policy_execution(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("diagnose_database_failure")])
        result = run_episode(self.scenarios["dev-database-clear"], policy, episode_id="dev-001")
        replayed = replay_trace(json.loads(json.dumps(result.trace)))
        self.assertEqual(replayed["episode_id"], "dev-001")
        self.assertEqual(replayed["terminal_action"], result.terminal_action)
        self.assertEqual(replayed["terminal_reason"], result.terminal_reason)
        tampered = json.loads(json.dumps(result.trace))
        tampered[-1]["visible_state_before"]["observations"] = []
        with self.assertRaises(ValueError):
            replay_trace(tampered)

    def test_metrics_separate_diagnosable_and_review_denominators(self):
        scenarios = [self.scenarios["dev-database-clear"], self.scenarios["dev-unrelated"]]
        results = [
            run_episode(scenarios[0], FakePolicy([Proposal("request_review")]), episode_id="dev-001"),
            run_episode(scenarios[1], FakePolicy([Proposal("request_review")]), episode_id="dev-002"),
        ]
        metrics = summarize_results(scenarios, results)
        self.assertEqual(metrics["diagnosable_count"], 1)
        self.assertEqual(metrics["review_required_count"], 1)
        self.assertEqual(metrics["correct_supported_diagnoses"], 0)
        self.assertEqual(metrics["correct_review_decisions"], 1)
        self.assertEqual(metrics["unnecessary_review_on_diagnosable_cases"], 1)

    def test_masked_gliclass_initially_scores_tools_and_review_only(self):
        ranker = FakeRanker(["check_database"])
        policy = GLiClassPolicy(ranker, evidence_masked=True)
        proposal = policy.propose(empty_visible_state(), tuple(ACTION_IDS))
        self.assertEqual(proposal.scored_candidate_ids, tuple(ACTION_IDS[:4]) + ("request_review",))
        self.assertTrue(all(action.startswith("check_") or action == "request_review" for action in proposal.scored_candidate_ids))
        self.assertEqual(set(proposal.excluded_candidates), set(ACTION_IDS) - set(proposal.scored_candidate_ids))
        self.assertIn("diagnosis_not_supported", proposal.excluded_candidates["diagnose_database_failure"])

    def test_masked_gliclass_enables_diagnosis_after_visible_support(self):
        ranker = FakeRanker(["check_database", "diagnose_database_failure"])
        result = run_episode(self.scenarios["dev-database-clear"], GLiClassPolicy(ranker, evidence_masked=True))
        self.assertEqual(result.terminal_action, "diagnose_database_failure")
        self.assertNotIn("diagnose_database_failure", ranker.candidate_ids[0])
        self.assertIn("diagnose_database_failure", ranker.candidate_ids[1])

    def test_masked_gliclass_disables_diagnosis_after_contradiction(self):
        ranker = FakeRanker(["check_database", "check_service_health", "request_review"])
        result = run_episode(self.scenarios["dev-contradictory-evidence"], GLiClassPolicy(ranker, evidence_masked=True))
        self.assertEqual(result.terminal_action, "request_review")
        self.assertNotIn("diagnose_database_failure", ranker.candidate_ids[2])
        self.assertIn("contradictory_current_evidence", result.trace[2]["excluded_candidates"]["diagnose_database_failure"])

    def test_masked_gliclass_healthy_requires_all_four_current_successes(self):
        ranker = FakeRanker(["check_database", "check_authentication", "check_storage", "check_service_health", "diagnose_healthy"])
        result = run_episode(self.scenarios["dev-healthy-clear"], GLiClassPolicy(ranker, evidence_masked=True))
        self.assertEqual(result.terminal_action, "diagnose_healthy")
        self.assertNotIn("diagnose_healthy", ranker.candidate_ids[3])
        self.assertIn("diagnose_healthy", ranker.candidate_ids[4])

    def test_masked_gliclass_preserves_tool_budget_repeat_and_review_constraints(self):
        state = empty_visible_state(actions_attempted=("check_database",), remaining_tool_calls=0)
        ranker = FakeRanker(["request_review"])
        proposal = GLiClassPolicy(ranker, evidence_masked=True).propose(state, eligible_actions(state))
        self.assertEqual(proposal.scored_candidate_ids, ("request_review",))
        self.assertEqual(proposal.excluded_candidates["check_database"], "tool_already_attempted")
        self.assertEqual(proposal.excluded_candidates["check_authentication"], "tool_call_budget_exhausted")
        self.assertEqual(proposal.action_id, "request_review")

    def test_harness_rejects_out_of_candidate_scores_and_selected_action(self):
        candidates = tuple(ACTION_IDS)
        bad_scores = {action: 1 / len(candidates) for action in candidates}
        bad_scores["not_a_candidate"] = 0.0
        for proposal in (
            Proposal("request_review", scores=bad_scores, scored_candidate_ids=candidates),
            Proposal("diagnose_database_failure", scores={"request_review": 1.0}, scored_candidate_ids=("request_review",)),
            Proposal("request_review", scores={**{action: 1 / len(candidates) for action in candidates}, "check_database": float("nan")}, scored_candidate_ids=candidates),
        ):
            result = run_episode(self.scenarios["dev-database-clear"], FakePolicy([proposal]))
            self.assertEqual(result.terminal_status, "failed")
            self.assertEqual(result.invalid_proposals_rejected, 1)

    def test_trace_records_exact_post_decrement_policy_input(self):
        policy = FakePolicy([Proposal("request_review")])
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        event = result.trace[0]
        self.assertEqual(event["trace_version"], 3)
        self.assertEqual(event["policy_input"]["visible_state"], policy.visible_states[0][0].as_dict())
        self.assertEqual(event["policy_input"]["eligible_action_ids"], list(policy.visible_states[0][1]))
        self.assertEqual(event["visible_state_before"]["remaining_decisions"], 6)
        self.assertEqual(event["policy_input"]["visible_state"]["remaining_decisions"], 5)

    def test_trace_replay_still_accepts_version_one_events(self):
        result = run_episode(self.scenarios["dev-database-clear"], FakePolicy([Proposal("request_review")]))
        old_events = json.loads(json.dumps(result.trace))
        for event in old_events:
            event.pop("trace_version")
            event.pop("policy_input")
            event.pop("scored_candidate_ids")
            event.pop("excluded_candidates")
        replayed = replay_trace(old_events)
        self.assertEqual(replayed["terminal_reason"], "review")

    def test_trace_replay_still_accepts_version_two_events(self):
        result = run_episode(self.scenarios["dev-database-clear"], FakePolicy([Proposal("request_review")]))
        version_two = json.loads(json.dumps(result.trace))
        for event in version_two:
            event["trace_version"] = 2
            event["policy_input"] = {key: event["policy_input"][key] for key in ("visible_state", "eligible_action_ids")}
        replayed = replay_trace(version_two)
        self.assertEqual(replayed["terminal_reason"], "review")

    def test_masked_trace_replays_without_loading_or_invoking_a_model(self):
        ranker = FakeRanker(["check_database", "diagnose_database_failure"])
        result = run_episode(self.scenarios["dev-database-clear"], GLiClassPolicy(ranker, evidence_masked=True))
        saved = json.loads(json.dumps(result.trace))
        replayed = replay_trace(saved)
        self.assertEqual(replayed["terminal_action"], "diagnose_database_failure")
        self.assertEqual(replayed["terminal_reason"], "completed")

    def test_metrics_count_every_terminal_outcome_and_surface_failed_run(self):
        scenario = self.scenarios["dev-database-clear"]
        result = run_episode(scenario, FakePolicy([Proposal("diagnose_disk_full"), Proposal("diagnose_disk_full")]))
        self.assertEqual(result.invalid_proposals_rejected, 0)
        metrics = summarize_results([scenario], [result])
        self.assertEqual(metrics["run_status"], "failed")
        self.assertEqual(metrics["episode_count"], 1)
        self.assertEqual(metrics["failed_episodes"], 1)
        self.assertEqual(sum(metrics["terminal_status_counts"].values()), metrics["episode_count"])
        self.assertEqual(sum(metrics["terminal_reason_counts"].values()), metrics["episode_count"])


if __name__ == "__main__":
    unittest.main()
