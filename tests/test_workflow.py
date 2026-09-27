import json
import unittest
from dataclasses import asdict

from decisionops.workflow import (
    ACTION_IDS,
    DEFAULT_MAX_DECISIONS,
    DEFAULT_MAX_TOOL_CALLS,
    Proposal,
    eligible_actions,
    replay_trace,
    run_episode,
)
from decisionops.workflow_eval import summarize_results
from decisionops.workflow_policies import FixedOrderPolicy
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

    def test_tool_call_budget_is_enforced(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("check_authentication")])
        result = run_episode(self.scenarios["dev-database-clear"], policy, max_tool_calls=1)
        self.assertEqual(result.terminal_reason, "exhausted_budget")
        self.assertEqual(result.tool_call_count, 1)

    def test_decision_budget_guarantees_termination(self):
        policy = FakePolicy([Proposal("check_database"), Proposal("check_authentication"), Proposal("check_storage")])
        result = run_episode(self.scenarios["dev-database-clear"], policy, max_decisions=1)
        self.assertEqual(result.terminal_reason, "exhausted_budget")
        self.assertLessEqual(result.decision_count, 1)

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


if __name__ == "__main__":
    unittest.main()
