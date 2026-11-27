import tempfile
import unittest
from pathlib import Path

from decisionops import CANDIDATES, LABELS
from decisionops.backends import (
    InvalidModelOutput,
    build_gliclass_candidate_labels,
    build_laya_question,
    canonicalize_gliclass_scores,
    normalize_laya_result,
    offline_model_path,
    parse_revision_pins,
    validate_neural_prediction,
)
from decisionops.rules import predict_rules


class CandidateTests(unittest.TestCase):
    def test_gliclass_primary_labels_use_flat_human_readable_names(self):
        self.assertEqual(build_gliclass_candidate_labels(), tuple(candidate.name for candidate in CANDIDATES))

    def test_gliclass_mapping_supports_non_default_candidate_order(self):
        reordered = (CANDIDATES[3], CANDIDATES[2], CANDIDATES[0], CANDIDATES[1])
        model_labels = build_gliclass_candidate_labels(reordered)
        values = {model_labels[0]: 0.7, model_labels[1]: 0.1, model_labels[2]: 0.1, model_labels[3]: 0.1}
        mapped = canonicalize_gliclass_scores(values, reordered)
        self.assertEqual(tuple(mapped), tuple(candidate.id for candidate in reordered))
        self.assertEqual(mapped["healthy"], 0.7)

    def test_gliclass_hierarchical_scores_map_to_canonical_ids(self):
        labels = build_gliclass_candidate_labels()
        mapped = canonicalize_gliclass_scores({"incident": {f"incident.{label}": 0.25 for label in labels}})
        self.assertEqual(set(mapped), set(LABELS))

    def test_laya_question_uses_same_names_and_descriptions(self):
        reordered = (CANDIDATES[2], CANDIDATES[0])
        question = build_laya_question(reordered)
        self.assertEqual(list(question["incident"]["criteria"]), [candidate.name for candidate in reordered])
        self.assertEqual(question["incident"]["criteria"][reordered[0].name], reordered[0].description)


class ModelMappingTests(unittest.TestCase):
    def test_laya_nested_scores_map_names_to_ids_and_keep_native_fields_separate(self):
        result = normalize_laya_result({"answers": {"incident": {"choice": "Disk full", "probabilities": {"Healthy": 0.1, "Disk full": 0.7, "Database failure": 0.1, "Authentication failure": 0.1}, "confidence": 0.42, "answer_confidence": 0.7, "action": {"act_probability": 0.96}}}})
        self.assertEqual(result["selected_class"], "disk_full")
        self.assertEqual(result["scores"]["disk_full"], 0.7)
        self.assertEqual(result["confidence"], 0.42)
        self.assertEqual(result["answer_confidence"], 0.7)
        self.assertEqual(result["action_act_probability"], 0.96)

    def test_neural_output_validation_rejects_malformed_scores_and_class(self):
        valid = {label: 0.25 for label in LABELS}
        self.assertEqual(validate_neural_prediction("test", "healthy", valid)[0], "healthy")
        invalid_cases = [
            ("unknown", valid),
            ("healthy", {"healthy": 1.0}),
            ("healthy", {**valid, "healthy": float("nan")}),
            ("healthy", {**valid, "healthy": 1.2}),
            ("healthy", {"database_failure": 0.4, "authentication_failure": 0.2, "disk_full": 0.2, "healthy": 0.1}),
            ("database_failure", {"database_failure": 0.1, "authentication_failure": 0.2, "disk_full": 0.2, "healthy": 0.5}),
        ]
        for selected, scores in invalid_cases:
            with self.subTest(selected=selected, scores=scores), self.assertRaises(InvalidModelOutput):
                validate_neural_prediction("test", selected, scores)



class RulesTests(unittest.TestCase):
    def test_negated_health_without_diagnosis_abstains(self):
        self.assertIsNone(predict_rules("The service is not healthy.")["selected_class"])

    def test_negated_health_with_database_timeout_selects_database_failure(self):
        self.assertEqual(predict_rules("The service is not healthy: database connections time out.")["selected_class"], "database_failure")

    def test_affirmative_normal_operation_is_healthy(self):
        self.assertEqual(predict_rules("All health checks pass and the service is operating normally.")["selected_class"], "healthy")

    def test_negated_failure_with_successful_operation_is_healthy(self):
        self.assertEqual(predict_rules("Database connections are not failing; requests are succeeding.")["selected_class"], "healthy")

    def test_multiple_explicit_current_faults_abstain(self):
        self.assertIsNone(predict_rules("Database connections time out and disk is full.")["selected_class"])

    def test_common_failure_cues_and_historical_limitations(self):
        self.assertEqual(predict_rules("The application cannot connect to PostgreSQL; connection refused.")["selected_class"], "database_failure")
        self.assertEqual(predict_rules("Writes fail with no space left on the device.")["selected_class"], "disk_full")
        self.assertIsNone(predict_rules("Database timeouts happened yesterday but connections work now.")["selected_class"])


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
