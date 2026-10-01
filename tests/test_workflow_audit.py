import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from decisionops.workflow import Proposal, run_episode
from decisionops.workflow_audit import CoverageAuditError, _trace_tool_data, build_coverage_audit, write_coverage_audit
from decisionops.workflow_eval import summarize_results
from decisionops.workflow_scenarios import SCENARIO_FILE, load_scenarios


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "workflow-model-comparison-20260927"


class _TwoStepPolicy:
    name = "illustrative"
    load_seconds = 0.0

    def __init__(self):
        self.states = []

    def propose(self, state, eligible):
        self.states.append(state.as_dict())
        action = "check_database" if len(self.states) == 1 else "diagnose_database_failure"
        return Proposal(action)


class WorkflowCoverageAuditTests(unittest.TestCase):
    def test_coverage_accounting_uses_trace_and_existing_evaluator_outcomes(self):
        audit = build_coverage_audit(REPORT, SCENARIO_FILE)
        self.assertEqual(audit["episode_count"], 144)
        self.assertEqual(len(audit["episodes"]), 144)
        partial = [row for row in audit["episodes"] if not row["tools"]["all_four_current_success"]]
        self.assertEqual(audit["summary"]["incomplete_coverage_episode_count"], len(partial))
        self.assertEqual(audit["summary"]["incomplete_coverage_failed_episode_count"], sum(row["evaluator_outcome"] == "failed_episodes" for row in partial))
        self.assertEqual(audit["summary"]["incomplete_coverage_incorrect_diagnosis_count"], 5)
        for policy in audit["policies"]:
            for split in audit["policies"][policy]:
                groups = audit["policies"][policy][split]
                self.assertEqual(sum(group["episode_denominator"] for group in groups.values()), 12)
                for coverage, group in groups.items():
                    self.assertEqual(group["all_four_current_coverage"], coverage == "all_four")
                    self.assertEqual(
                        sum(group["outcomes"][name]["count"] for name in (
                            "correct_diagnoses", "incorrect_diagnoses", "reviews", "failed_episodes", "other_terminal_outcomes",
                        )),
                        group["episode_denominator"],
                    )
                    self.assertEqual(group["classified_episode_count"], group["episode_denominator"])
        self.assertEqual(sum(audit["summary"]["outcome_counts"].values()), audit["episode_count"])
        self.assertEqual(audit["summary"]["classified_episode_count"], audit["episode_count"])
        premature = next(row for row in audit["episodes"] if (
            row["policy"] == "laya_evidence_masked" and row["split"] == "evaluation"
            and row["scenario_id"] == "eval-multiple-current-faults"
        ))
        self.assertEqual(premature["terminal"]["action"], "diagnose_database_failure")
        self.assertFalse(premature["tools"]["all_four_current_success"])
        self.assertEqual(premature["tools"]["never_attempted"], ["check_authentication", "check_storage", "check_service_health"])
        self.assertEqual(premature["evaluator_outcome"], "incorrect_diagnoses")
        hidden = premature["evaluator_only_hindsight"]["unrequested_structured_signals"]
        auth = next(signal for signal in hidden if signal["tool_name"] == "check_authentication")
        self.assertEqual(auth["facts"], [{"fact": "authentication_success", "equals": False}, {"fact": "credentials_rejected", "equals": True}])
        self.assertEqual(auth["relationship"], "additional_fault")
        self.assertNotIn("message", auth)

    def test_missing_observations_mean_no_tools_returned_current_success(self):
        audit = build_coverage_audit(REPORT, SCENARIO_FILE)
        episode = next(row for row in audit["episodes"] if (
            row["policy"] == "laya" and row["split"] == "development" and row["scenario_id"] == "dev-database-clear"
        ))
        self.assertEqual(episode["tools"]["attempted"], [])
        self.assertEqual(episode["tools"]["never_attempted"], ["check_database", "check_authentication", "check_storage", "check_service_health"])
        self.assertEqual(episode["tools"]["successful_current_observations"], [])
        self.assertFalse(episode["tools"]["all_four_current_success"])

    def test_historical_timeout_and_error_observations_are_distinguished(self):
        audit = build_coverage_audit(REPORT, SCENARIO_FILE)
        indexed = {(row["policy"], row["split"], row["scenario_id"]): row for row in audit["episodes"]}
        timeout = indexed[("fixed_order", "evaluation", "eval-authentication-timeout")]
        self.assertEqual(timeout["tools"]["timeout_observations"], ["check_authentication"])
        error = indexed[("fixed_order", "evaluation", "eval-storage-tool-error")]
        self.assertEqual(error["tools"]["error_observations"], ["check_storage"])
        self.assertNotIn("check_storage", error["tools"]["successful_current_observations"])

    def test_historical_success_is_listed_but_does_not_count_as_current_coverage(self):
        events = [{
            "visible_state_after": {"actions_attempted": ["check_database"]},
            "terminal_decision": {"action_id": "request_review", "reason": "review", "status": "review"},
            "tool_observation": {
                "tool_name": "check_database", "status": "success", "time_scope": "historical",
                "facts": {"connection_success": False},
            },
        }]
        tools, _terminal = _trace_tool_data(events)
        self.assertEqual(tools["historical_observations"], ["check_database"])
        self.assertEqual(tools["successful_current_observations"], [])
        self.assertFalse(tools["all_four_current_success"])

    def test_scenario_hash_mismatch_fails_before_joining_hidden_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "scenarios.jsonl"
            changed.write_bytes(SCENARIO_FILE.read_bytes() + b"\n")
            with self.assertRaisesRegex(CoverageAuditError, "scenario.*SHA-256"):
                build_coverage_audit(REPORT, changed)

    def test_evaluator_hindsight_is_separate_from_policy_visible_trace(self):
        audit = build_coverage_audit(REPORT, SCENARIO_FILE)
        row = next(row for row in audit["episodes"] if (
            row["policy"] == "laya_evidence_masked" and row["split"] == "evaluation"
            and row["scenario_id"] == "eval-multiple-current-faults"
        ))
        self.assertNotIn("gold_terminal_action", row["policy_visible_evidence"])
        self.assertNotIn("unrequested_structured_signals", row["policy_visible_evidence"])
        self.assertEqual(row["policy_visible_evidence"]["observations"][0]["tool_name"], "check_database")
        self.assertTrue(row["evaluator_only_hindsight"]["unrequested_structured_signals"])

    def test_two_hidden_worlds_have_identical_policy_state_but_different_evaluator_outcomes(self):
        scenarios = {item.scenario_id: item for item in load_scenarios()}
        db_world = scenarios["dev-database-clear"]
        multi_world = scenarios["eval-multiple-current-faults"]
        shared_report = "Requests are failing; inspect the database."
        visible_world = replace(db_world, initial_report=shared_report)
        hidden_observations = dict(visible_world.observations)
        hidden_observations["check_authentication"] = multi_world.observations["check_authentication"]
        hidden_world = replace(multi_world, initial_report=shared_report, observations=hidden_observations)
        self.assertEqual(
            visible_world.observations["check_database"], hidden_world.observations["check_database"],
        )
        for tool in ("check_storage", "check_service_health"):
            self.assertEqual(visible_world.observations[tool], hidden_world.observations[tool])
        self.assertIs(hidden_world.observations["check_authentication"]["facts"]["credentials_rejected"], True)
        for world in (visible_world, hidden_world):
            policy = _TwoStepPolicy()
            result = run_episode(world, policy, episode_id="illustrative")
            self.assertEqual(policy.states[1]["initial_report"], shared_report)
            self.assertEqual(policy.states[1]["observations"][0]["tool_name"], "check_database")
            if world is visible_world:
                visible_result, visible_state = result, policy.states[1]
            else:
                hidden_result, hidden_state = result, policy.states[1]
        self.assertEqual(visible_state, hidden_state)
        visible_metrics = summarize_results([visible_world], [visible_result])
        hidden_metrics = summarize_results([hidden_world], [hidden_result])
        self.assertEqual(visible_metrics["correct_supported_diagnoses"], 1)
        self.assertEqual(hidden_metrics["incorrect_diagnoses"], 1)

    def test_audit_writes_machine_and_markdown_outputs_with_trace_links(self):
        audit = build_coverage_audit(REPORT, SCENARIO_FILE)
        with tempfile.TemporaryDirectory() as directory:
            json_path, markdown_path = write_coverage_audit(audit, REPORT, Path(directory) / "audit")
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["episode_count"], 144)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("Evaluator-only hindsight", markdown)
            self.assertIn("traces/laya_evidence_masked/eva-007.jsonl", markdown)

    def test_completed_gold_diagnosis_without_gold_evidence_is_counted_as_residual_everywhere(self):
        with tempfile.TemporaryDirectory() as directory:
            report_copy = Path(directory) / "report"
            shutil.copytree(REPORT, report_copy)
            policy = "fixed_order"
            split = "development"
            scenario = "dev-database-clear"
            summary_path = report_copy / f"{policy}-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            row = next(item for item in summary["episodes"] if item["scenario_id"] == scenario and item["split"] == split)
            self.assertEqual(row["terminal_action"], row["gold_terminal_action"])
            self.assertEqual(row["terminal_reason"], "completed")
            row["gold_evidence_supported"] = False
            metrics = summary["metrics_by_split"][split]
            metrics["correct_supported_diagnoses"] -= 1
            metrics["correct_supported_diagnosis_rate"] = metrics["correct_supported_diagnoses"] / metrics["diagnosable_count"]
            summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

            all_summary_path = report_copy / "all-summary.json"
            all_summary = json.loads(all_summary_path.read_text(encoding="utf-8"))
            comparison = next(item for item in all_summary["comparison"] if item["policy"] == policy and item["split"] == split)
            comparison["correct_supported_diagnoses"] = metrics["correct_supported_diagnoses"]
            all_summary_path.write_text(json.dumps(all_summary, indent=2) + "\n", encoding="utf-8")

            audit = build_coverage_audit(report_copy, SCENARIO_FILE)
            group = audit["policies"][policy][split]["all_four"]
            self.assertEqual(group["outcomes"]["other_terminal_outcomes"]["count"], 1)
            self.assertEqual(group["classified_episode_count"], group["episode_denominator"])
            self.assertEqual(
                sum(bucket["count"] for bucket in group["outcomes"].values()),
                group["episode_denominator"],
            )
            self.assertEqual(audit["summary"]["outcome_counts"]["other_terminal_outcomes"], 1)
            self.assertEqual(audit["summary"]["classified_episode_count"], audit["episode_count"])
            self.assertEqual(group["outcomes"]["correct_diagnoses"]["count"], metrics["correct_supported_diagnoses"])
            self.assertEqual(group["outcomes"]["incorrect_diagnoses"]["count"], metrics["incorrect_diagnoses"])

            _json_path, markdown_path = write_coverage_audit(audit, report_copy, Path(directory) / "audit")
            output_json = json.loads(_json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertEqual(output_json["summary"]["outcome_counts"]["other_terminal_outcomes"], 1)
            self.assertEqual(sum(output_json["summary"]["outcome_counts"].values()), output_json["episode_count"])
            self.assertIn("Other / n", markdown)
            self.assertIn("1 episode was assigned to the residual outcome bucket", markdown)
            self.assertIn("| `fixed_order` | development | all four | 11 | 6 / 7 | 0 / 11 | 4 / 11 | 0 / 11 | 1 / 11 |", markdown)


if __name__ == "__main__":
    unittest.main()
