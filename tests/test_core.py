import json
import tempfile
import unittest
from pathlib import Path

from decisionops.backends import canonicalize_gliclass_scores, normalize_laya_result, offline_model_path, parse_revision_pins
from decisionops.dataset import load_dataset, validate_dataset
from decisionops.metrics import summarize_classifications
from decisionops.rules import predict_rules
from decisionops.runner import prediction_record


class DatasetTests(unittest.TestCase):
    def test_development_data_has_balanced_core_and_reviewable_challenges(self):
        cases = load_dataset(Path(__file__).parents[1] / "data" / "incidents.jsonl")
        self.assertEqual(len(cases), 48)
        counts = {label: 0 for label in ("database_failure", "authentication_failure", "disk_full", "healthy")}
        for case in cases[:32]:
            counts[case["expected_label"]] += 1
            self.assertFalse(case["needs_review"])
        self.assertEqual(set(counts.values()), {8})
        self.assertEqual(sum(case["needs_review"] for case in cases[32:]), 9)

    def test_dataset_rejects_duplicate_ids_and_missing_rationales(self):
        cases = [
            {"id": "x", "text": "Database down", "tags": [], "expected_label": "database_failure", "needs_review": False, "rationale": ""},
            {"id": "x", "text": "Disk full", "tags": [], "expected_label": "disk_full", "needs_review": False, "rationale": "ok"},
        ]
        with self.assertRaises(ValueError):
            validate_dataset(cases)


class MappingAndMetricsTests(unittest.TestCase):
    def test_laya_nested_native_scores_and_confidence_are_preserved(self):
        result = normalize_laya_result({"answers": {"incident": {"choice": "disk_full", "probabilities": {"healthy": 0.1, "disk_full": 0.7, "database_failure": 0.1, "authentication_failure": 0.1}, "confidence": 0.42, "answer_confidence": 0.7, "action": {"act_probability": 0.96}}}})
        self.assertEqual(result["selected_class"], "disk_full")
        self.assertEqual(result["scores"]["disk_full"], 0.7)
        self.assertEqual(result["confidence"], 0.42)
        self.assertEqual(result["answer_confidence"], 0.7)
        self.assertEqual(result["action_act_probability"], 0.96)

    def test_gliclass_canonical_ids_map_in_candidate_order(self):
        self.assertEqual(
            canonicalize_gliclass_scores({"disk_full": 0.1, "healthy": 0.2, "authentication_failure": 0.3, "database_failure": 0.4}),
            {"database_failure": 0.4, "authentication_failure": 0.3, "disk_full": 0.1, "healthy": 0.2},
        )

    def test_abstention_fails_overall_accuracy_but_counts_coverage(self):
        summary = summarize_classifications(
            [
                {"expected_label": "database_failure", "selected_class": None},
                {"expected_label": "healthy", "selected_class": "healthy"},
            ],
            ("database_failure", "authentication_failure", "disk_full", "healthy"),
        )
        self.assertEqual(summary["accuracy"], 0.5)
        self.assertEqual(summary["coverage"], 0.5)
        self.assertEqual(summary["confusion_matrix"]["database_failure"]["abstain"], 1)


class PredictionRecordTests(unittest.TestCase):
    def test_worker_record_keeps_laya_action_probability_distinct(self):
        row = prediction_record(
            {"id": "x", "text": "sample", "tags": ["unambiguous"], "expected_label": "healthy", "needs_review": False, "rationale": "test"},
            "laya",
            {"selected_class": "healthy", "scores": {"healthy": 0.8}, "inference_seconds": 0.1, "confidence": 0.5, "answer_confidence": 0.8, "action_act_probability": 0.99},
        )
        self.assertEqual(row["scores"], {"healthy": 0.8})
        self.assertEqual(row["action_act_probability"], 0.99)


class RulesTests(unittest.TestCase):
    def test_rules_cover_common_connection_auth_space_and_health_phrasings(self):
        examples = {
            "The application cannot connect to PostgreSQL; connection refused.": "database_failure",
            "Users cannot sign in because their passwords are rejected.": "authentication_failure",
            "Writes fail with no space left on the device.": "disk_full",
            "Monitoring reports normal operation across all components.": "healthy",
            "All endpoints respond successfully; no incidents are active.": "healthy",
            "The service is not healthy: database connections time out.": "database_failure",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(predict_rules(text)["selected_class"], expected)

    def test_rules_classify_current_health_and_abstain_on_conflict(self):
        self.assertEqual(predict_rules("All health checks pass and the service is operating normally.")["selected_class"], "healthy")
        self.assertEqual(predict_rules("Database connections time out and disk is full.")["selected_class"], None)
        self.assertEqual(predict_rules("Database connections are not failing; requests are succeeding.")["selected_class"], "healthy")
        self.assertIsNone(predict_rules("Database timeouts happened yesterday but connections work now.")["selected_class"])
        self.assertEqual(predict_rules("We saw an issue earlier.")["selected_class"], None)


class OfflinePathTests(unittest.TestCase):
    def test_revision_pin_parser_does_not_execute_env_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pins.env"
            path.write_text("GLICLASS_REV=abc123\nLAYA_REV=def456\n", encoding="utf-8")
            self.assertEqual(parse_revision_pins(path), {"GLICLASS_REV": "abc123", "LAYA_REV": "def456"})

    def test_offline_model_path_uses_weight_parent_without_resolving(self):
        weight_path = Path("/cache/snapshots/revision/model.safetensors")
        self.assertEqual(offline_model_path(lambda **kwargs: str(weight_path), "repo", "rev"), weight_path.parent)


if __name__ == "__main__":
    unittest.main()
