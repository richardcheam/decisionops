import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from decisionops import CandidateSpec
import decisionops.backends as backend_api
from decisionops.workflow import ACTION_IDS, ACTION_NAMES, Proposal, replay_trace, run_episode
import decisionops.workflow_eval as workflow_eval
import decisionops.workflow_policies as workflow_policies
from decisionops.workflow_scenarios import load_scenarios
from decisionops.workflow_scenarios import SCENARIO_FILE


def workflow_candidates(candidate_ids):
    descriptions = getattr(workflow_policies, "WORKFLOW_LAYA_ACTION_DESCRIPTIONS", {})
    return tuple(CandidateSpec(action_id, ACTION_NAMES[action_id], descriptions[action_id]) for action_id in candidate_ids)


def laya_result(question, choice, probabilities, confidence=0.41, answer_confidence=0.72, act_probability=0.96):
    return {"answers": {"next_action": {
        "type": "choice", "choice": choice, "probabilities": probabilities,
        "confidence": confidence, "answer_confidence": answer_confidence,
        "action": {"act_probability": act_probability},
    }}}


class FakeLayaAgent:
    load_seconds = 0.0

    def __init__(self, choice_for_text=None):
        self.choice_for_text = choice_for_text or (lambda _text, names: names[0])
        self.calls = []

    def predict(self, text, questions):
        question = questions["next_action"]
        names = list(question["criteria"])
        selected = self.choice_for_text(text, names)
        scores = {name: 0.0 for name in names}
        scores[selected] = 1.0 if len(names) == 1 else 0.8
        if len(names) > 1:
            remaining = [name for name in names if name != selected]
            for name in remaining:
                scores[name] = 0.2 / len(remaining)
        result = laya_result(question, selected, scores)
        self.calls.append((text, questions, result))
        return result


class LayaWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = {scenario.scenario_id: scenario for scenario in load_scenarios()}

    @unittest.skipUnless(
        importlib.util.find_spec("laya") is not None,
        "requires the Laya package API; model-free CI does not install ML dependencies",
    )
    def test_laya_named_choice_maps_using_the_installed_api_choice_order(self):
        from laya.agent import Agent

        build_question = getattr(workflow_policies, "build_laya_workflow_question", None)
        normalize = getattr(backend_api, "normalize_laya_workflow_result", None)
        self.assertTrue(callable(build_question), "workflow action question builder is missing")
        self.assertTrue(callable(normalize), "workflow native result adapter is missing")
        candidate_ids = ("check_storage", "request_review")
        question = build_question(candidate_ids)
        definition = question["next_action"]
        Agent._check_question("next_action", definition)
        names = list(definition["criteria"])
        self.assertEqual(names, ["Check storage", "Request review"])
        normalized = normalize(
            laya_result(definition, "Request review", {names[0]: 0.2, names[1]: 0.8}),
            workflow_candidates(candidate_ids),
        )
        self.assertEqual(normalized["selected_action_id"], "request_review")
        self.assertEqual(normalized["scores"], {"check_storage": 0.2, "request_review": 0.8})

    def test_laya_rejects_missing_extra_nonfinite_and_inconsistent_probabilities(self):
        candidate_ids = ("check_database", "request_review")
        normalize = getattr(backend_api, "normalize_laya_workflow_result", None)
        self.assertTrue(callable(normalize), "workflow native result adapter is missing")
        valid = {"Check database": 0.8, "Request review": 0.2}
        invalid_outputs = (
            ("Check database", {"Check database": 1.0}),
            ("Check database", {**valid, "Healthy": 0.0}),
            ("Check database", {"Check database": float("nan"), "Request review": 0.0}),
            ("Check database", {"Check database": 0.2, "Request review": 0.8}),
        )
        for choice, probabilities in invalid_outputs:
            with self.subTest(choice=choice, probabilities=probabilities), self.assertRaises(ValueError):
                normalize(laya_result({}, choice, probabilities), workflow_candidates(candidate_ids))

    def test_shared_candidate_selection_masks_only_unsupported_diagnoses(self):
        scenario = self.scenarios["dev-database-clear"]
        from decisionops.workflow import VisibleState

        select_candidates = getattr(workflow_policies, "select_action_candidates", None)
        self.assertTrue(callable(select_candidates), "shared candidate selector is missing")
        state = VisibleState(scenario.initial_report, (), (), 4, 4, 6, 6)
        unmasked, _unmasked_excluded = select_candidates(state, ACTION_IDS, evidence_masked=False)
        masked, excluded = select_candidates(state, ACTION_IDS, evidence_masked=True)
        self.assertEqual(unmasked, ACTION_IDS)
        self.assertEqual(masked, ACTION_IDS[:4] + ("request_review",))
        self.assertIn("request_review", masked)
        self.assertIn("diagnose_database_failure", excluded)

    def test_laya_unmasked_and_masked_questions_use_the_expected_candidates(self):
        from decisionops.workflow import VisibleState

        LayaPolicy = getattr(workflow_policies, "LayaPolicy", None)
        self.assertTrue(callable(LayaPolicy), "Laya workflow policy is missing")
        instructions = getattr(workflow_policies, "WORKFLOW_LAYA_INSTRUCTIONS", None)
        state = VisibleState("no diagnosis yet", (), (), 4, 4, 6, 6)
        unmasked_agent = FakeLayaAgent()
        unmasked = LayaPolicy(unmasked_agent).propose(state, ACTION_IDS)
        masked_agent = FakeLayaAgent()
        masked = LayaPolicy(masked_agent, evidence_masked=True).propose(state, ACTION_IDS)
        self.assertEqual(unmasked.scored_candidate_ids, ACTION_IDS)
        self.assertEqual(masked.scored_candidate_ids, ACTION_IDS[:4] + ("request_review",))
        self.assertEqual(list(unmasked_agent.calls[0][1]["next_action"]["criteria"]), [
            "Check database", "Check authentication", "Check storage", "Check service health",
            "Database failure", "Authentication failure", "Disk full", "Healthy", "Request review",
        ])
        self.assertEqual(list(masked_agent.calls[0][1]["next_action"]["criteria"]), [
            "Check database", "Check authentication", "Check storage", "Check service health", "Request review",
        ])
        self.assertIsNotNone(instructions)
        self.assertEqual(unmasked_agent.calls[0][1]["next_action"]["instructions"], instructions)

    @unittest.skipUnless(
        importlib.util.find_spec("laya") is not None,
        "requires the Laya package API; model-free CI does not install ML dependencies",
    )
    def test_laya_infers_for_single_remaining_candidate_and_keeps_native_metadata(self):
        from decisionops.workflow import VisibleState
        from laya.agent import Agent

        LayaPolicy = getattr(workflow_policies, "LayaPolicy", None)
        build_question = getattr(workflow_policies, "build_laya_workflow_question", None)
        self.assertTrue(callable(LayaPolicy), "Laya workflow policy is missing")
        self.assertTrue(callable(build_question), "workflow action question builder is missing")
        state = VisibleState("no diagnosis yet", (), ACTION_IDS[:4], 0, 4, 6, 6)
        agent = FakeLayaAgent()
        question = build_question(("request_review",))
        Agent._check_question("next_action", question["next_action"])
        proposal = LayaPolicy(agent, evidence_masked=True).propose(state, ("request_review",))
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(proposal.action_id, "request_review")
        self.assertEqual(proposal.scores, {"request_review": 1.0})
        self.assertEqual(proposal.native_metadata["confidence"], 0.41)
        self.assertEqual(proposal.native_metadata["answer_confidence"], 0.72)
        self.assertEqual(proposal.native_metadata["act_probability"], 0.96)
        self.assertEqual(proposal.native_metadata["choice"], "Request review")

    def test_laya_trace_records_exact_input_and_replays_without_agent_calls(self):
        def choose(text, names):
            if "Recorded observations: none" in text:
                return "Check database"
            return "Database failure"

        agent = FakeLayaAgent(choose)
        LayaPolicy = getattr(workflow_policies, "LayaPolicy", None)
        self.assertTrue(callable(LayaPolicy), "Laya workflow policy is missing")
        policy = LayaPolicy(agent, evidence_masked=True)
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        self.assertEqual(result.terminal_action, "diagnose_database_failure")
        event = result.trace[0]
        self.assertEqual(event["policy_input"]["model_family"], "laya")
        self.assertEqual(event["policy_input"]["state_text"], agent.calls[0][0])
        self.assertEqual(event["policy_input"]["question"], agent.calls[0][1])
        self.assertEqual(event["proposal"]["native_metadata"]["choice"], "Check database")
        self.assertEqual(event["proposal"]["native_metadata"]["probabilities"], agent.calls[0][2]["answers"]["next_action"]["probabilities"])
        self.assertIn("Database failure", agent.calls[1][1]["next_action"]["criteria"])
        calls_before_replay = len(agent.calls)
        replay = replay_trace(list(result.trace))
        self.assertEqual(replay["terminal_action"], result.terminal_action)
        self.assertEqual(len(agent.calls), calls_before_replay)
        tampered = json.loads(json.dumps(result.trace))
        tampered[0]["proposal"]["native_metadata"]["choice"] = "Request review"
        with self.assertRaises(ValueError):
            replay_trace(tampered)

    def test_laya_invalid_native_result_keeps_candidates_input_and_raw_output_in_trace(self):
        from decisionops.workflow import VisibleState

        class InvalidLayaAgent:
            load_seconds = 0.0

            def predict(self, _text, question):
                names = list(question["next_action"]["criteria"])
                return laya_result(question, names[0], {name: (0.1 if index == 0 else 0.9 / (len(names) - 1))
                                                         for index, name in enumerate(names)})

        policy = workflow_policies.LayaPolicy(InvalidLayaAgent(), evidence_masked=True)
        result = run_episode(self.scenarios["dev-database-clear"], policy)
        event = result.trace[0]
        self.assertEqual(result.terminal_reason, "invalid_proposal")
        self.assertEqual(event["acceptance"]["reason"], "policy_execution_error")
        self.assertEqual(event["scored_candidate_ids"], list(ACTION_IDS[:4]) + ["request_review"])
        self.assertEqual(event["policy_input"]["model_family"], "laya")
        self.assertEqual(event["proposal"]["native_output"]["answers"]["next_action"]["choice"], "Check database")
        self.assertEqual(replay_trace(list(result.trace))["terminal_reason"], "invalid_proposal")

    def test_failed_model_worker_discards_partial_artifacts_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "fresh-report"
            output.mkdir()

            def failed_worker(worker_dir, *_args):
                script = (
                    "from pathlib import Path; import sys; "
                    f"Path({str(worker_dir / 'gliclass-summary.json')!r}).write_text('partial'); "
                    "print('started'); print('worker crashed', file=sys.stderr); raise SystemExit(7)"
                )
                return [sys.executable, "-c", script]

            run_model_worker = getattr(workflow_eval, "_run_model_worker", None)
            self.assertTrue(callable(run_model_worker), "isolated model worker launcher is missing")
            status, summaries = run_model_worker(
                "gliclass", split="development", output_dir=output,
                scenario_path=Path("scenarios.jsonl"), pin_path=Path("revisions.env"), command_factory=failed_worker,
            )
            self.assertEqual(status["status"], "failed")
            self.assertIn("worker crashed", status["stderr"])
            self.assertIsNone(summaries)
            self.assertFalse((output / "gliclass-summary.json").exists())
            self.assertEqual(list(output.glob(".worker-*")), [])
            self.assertEqual(json.loads((output / "workers/gliclass-process.json").read_text())["status"], "failed")

    def test_incomplete_zero_exit_worker_is_still_reported_as_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "fresh-report"
            output.mkdir()

            def incomplete_worker(worker_dir, *_args):
                script = (
                    "from pathlib import Path; "
                    f"Path({str(worker_dir / 'worker-summary.json')!r}).write_text('{{\"worker_status\":\"completed\"}}')"
                )
                return [sys.executable, "-c", script]

            status, summaries = workflow_eval._run_model_worker(
                "laya", split="development", output_dir=output,
                scenario_path=SCENARIO_FILE, pin_path=Path("revisions.env"), command_factory=incomplete_worker,
            )
            self.assertEqual(status["status"], "failed")
            self.assertIn("incomplete", status["error"])
            self.assertIsNone(summaries)
            self.assertEqual(list(output.glob(".worker-*")), [])
            self.assertEqual(json.loads((output / "workers/laya-process.json").read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
