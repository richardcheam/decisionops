import json
import shutil
import tempfile
import unittest
from pathlib import Path

from decisionops.workflow_report import (
    ReportLoadError,
    _available_guided_examples,
    export_report,
    load_report,
    render_html,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "workflow-model-comparison-20260927"
DEVELOPMENT_REPORT = ROOT / "reports" / "workflow-model-comparison-development-final-20260927"
POLICIES = (
    "fixed_order", "rules", "gliclass", "gliclass_evidence_masked",
    "laya", "laya_evidence_masked",
)


class WorkflowReportTests(unittest.TestCase):
    def test_loaded_comparison_matches_policy_summary_sources(self):
        report = load_report(REPORT)
        self.assertEqual(report["evaluation_execution_status"], "completed")
        self.assertEqual(tuple(report["policies"]), POLICIES)
        for name in POLICIES:
            for split in ("development", "evaluation"):
                metrics = report["policies"][name]["metrics_by_split"][split]
                self.assertEqual(metrics["episode_count"], 12)
                row = next(item for item in report["comparison"] if item["policy"] == name and item["split"] == split)
                self.assertEqual(row["correct_supported_diagnoses"], metrics["correct_supported_diagnoses"])
                self.assertEqual(row["diagnosable_count"], metrics["diagnosable_count"])

    def test_gold_outcomes_are_separate_from_policy_trace_data(self):
        report = load_report(REPORT)
        policy_episode = report["policies"]["laya"]["episodes"]["development"]["dev-database-clear"]
        self.assertNotIn("gold_terminal_action", policy_episode)
        self.assertNotIn("scenario_id", policy_episode)
        self.assertEqual(
            report["evaluator"]["development"]["dev-database-clear"]["gold"]["gold_terminal_action"],
            "diagnose_database_failure",
        )

    def test_development_only_report_omits_evaluation_guided_example(self):
        report = load_report(DEVELOPMENT_REPORT)
        self.assertEqual({row["split"] for row in report["comparison"]}, {"development"})
        self.assertEqual({example["id"] for example in report["guided_examples"]}, {"blocked", "masked"})
        self.assertTrue(all(example["split"] == "development" for example in report["guided_examples"]))

    def test_premature_diagnosis_example_matches_recorded_trace(self):
        report = load_report(REPORT)
        scenario = "eval-multiple-current-faults"
        laya = report["policies"]["laya_evidence_masked"]["episodes"]["evaluation"][scenario]["events"]
        decisions = [event for event in laya if event["event_type"] == "decision"]
        self.assertEqual([event["proposal"]["action_id"] for event in decisions], [
            "check_database", "diagnose_database_failure",
        ])
        self.assertEqual(
            [obs["tool_name"] for obs in decisions[1]["visible_state_before"]["observations"]],
            ["check_database"],
        )
        self.assertTrue(decisions[1]["acceptance"]["accepted"])

        fixed = report["policies"]["fixed_order"]["episodes"]["evaluation"][scenario]["events"]
        fixed_decisions = [event for event in fixed if event["event_type"] == "decision"]
        self.assertEqual([event["proposal"]["action_id"] for event in fixed_decisions], [
            "check_database", "check_authentication", "check_storage", "check_service_health", "request_review",
        ])
        self.assertEqual(
            report["evaluator"]["evaluation"][scenario]["gold"]["gold_terminal_action"],
            "request_review",
        )

    def test_guides_require_the_selected_and_comparison_traces(self):
        report = load_report(REPORT)
        del report["policies"]["laya"]["episodes"]["development"]["dev-database-clear"]
        del report["policies"]["fixed_order"]["episodes"]["evaluation"]["eval-multiple-current-faults"]
        available = _available_guided_examples(report["policies"])
        self.assertEqual({example["id"] for example in available}, {"masked"})

    def test_missing_report_summary_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ReportLoadError, "all-summary.json"):
                load_report(Path(directory))

    def test_malformed_report_summary_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "all-summary.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ReportLoadError, "all-summary.json"):
                load_report(Path(directory))

    def test_rejects_trace_path_that_escapes_report_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            report_dir = Path(directory) / "report"
            report_dir.mkdir()
            shutil.copy(REPORT / "all-summary.json", report_dir / "all-summary.json")
            shutil.copy(REPORT / "run-status.json", report_dir / "run-status.json")
            shutil.copy(REPORT / "provenance.json", report_dir / "provenance.json")
            for policy in POLICIES:
                shutil.copy(REPORT / f"{policy}-summary.json", report_dir / f"{policy}-summary.json")
            summary_path = report_dir / "fixed_order-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["episodes"][0]["trace"] = "../../README.md"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ReportLoadError, "outside the report directory"):
                load_report(report_dir)

    def test_export_embeds_untrusted_report_text_as_json_data(self):
        report = load_report(REPORT)
        report["provenance"]["git_head"] = "</script><script>alert(1)</script>"
        page = render_html(report)
        self.assertIn(r"\u003c/script\u003e\u003cscript\u003e", page)
        self.assertNotIn("</script><script>alert(1)</script>", page)
        self.assertIn("textContent", page)

    def test_export_writes_html_outside_the_source_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "viewer.html"
            self.assertEqual(export_report(REPORT, output), output)
            page = output.read_text(encoding="utf-8")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn('id="evaluator-data" type="application/json"', page)
        self.assertNotIn("https://", page)

    def test_export_refuses_to_write_into_the_source_report(self):
        with self.assertRaisesRegex(ReportLoadError, "outside the source report"):
            export_report(REPORT, REPORT / "viewer.html")

    def test_comparison_metric_must_match_policy_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            report_dir = Path(directory) / "report"
            report_dir.mkdir()
            shutil.copy(REPORT / "all-summary.json", report_dir / "all-summary.json")
            shutil.copy(REPORT / "run-status.json", report_dir / "run-status.json")
            shutil.copy(REPORT / "provenance.json", report_dir / "provenance.json")
            for policy in POLICIES:
                shutil.copy(REPORT / f"{policy}-summary.json", report_dir / f"{policy}-summary.json")
            path = report_dir / "all-summary.json"
            summary = json.loads(path.read_text(encoding="utf-8"))
            summary["comparison"][0]["correct_supported_diagnoses"] += 1
            path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ReportLoadError, "disagrees with its policy summary"):
                load_report(report_dir)


if __name__ == "__main__":
    unittest.main()
