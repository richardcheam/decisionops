from datetime import datetime, timezone
import unittest

from decisionops.commerce.eligibility import REQUIREMENTS
from decisionops.commerce.evidence import assess_evidence


NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
SOURCES = {name: "demo-store" for name in REQUIREMENTS}


def record(name, **changes):
    result = {
        "requirement": name, "value": True, "status": "success",
        "source_id": "demo-store", "source_version": "v1",
        "order_id": "ORD-1042", "observed_at": "2026-10-12T11:00:00Z",
    }
    result.update(changes)
    return result


def assess(records, **changes):
    arguments = dict(order_id="ORD-1042", supported_case=True, now=NOW,
                     trusted_sources=SOURCES, max_age_seconds=86400)
    arguments.update(changes)
    return assess_evidence(records, **arguments)


class EvidenceTests(unittest.TestCase):
    def test_complete_current_evidence_allows_proposal_with_provenance(self):
        result = assess([record(name) for name in REQUIREMENTS])
        self.assertEqual(result["decision"]["status"], "eligible_to_propose")
        self.assertEqual(result["evidence"]["loss_confirmed"][0]["source_version"], "v1")

    def test_unusable_records_leave_requirement_unknown_with_reason(self):
        for changes, reason in (
            ({"observed_at": "2026-10-10T11:00:00Z"}, "stale"),
            ({"observed_at": "2026-10-13T11:00:00Z"}, "future_timestamp"),
            ({"status": "unavailable", "value": None}, "unavailable"),
            ({"order_id": "ORD-OTHER"}, "wrong_order"),
            ({"source_id": "customer-message"}, "untrusted_source"),
        ):
            with self.subTest(changes=changes):
                records = [record(name, **changes) if name == "loss_confirmed"
                           else record(name) for name in REQUIREMENTS]
                result = assess(records)
                self.assertEqual(result["decision"]["status"], "needs_review")
                self.assertIsNone(result["facts"]["loss_confirmed"])
                self.assertIn(reason, result["issues"]["loss_confirmed"])

    def test_conflicting_current_versions_are_not_silently_resolved(self):
        records = [record(name) for name in REQUIREMENTS]
        records.append(record("loss_confirmed", value=False, source_version="v2"))
        result = assess(records)
        self.assertEqual(result["issues"]["loss_confirmed"], ["contradictory"])
        self.assertEqual(result["decision"]["status"], "needs_review")

    def test_missing_compensation_history_is_not_empty_history(self):
        result = assess([record(name) for name in REQUIREMENTS
                         if name != "no_previous_compensation"])
        self.assertEqual(result["decision"]["unknowns"], ["no_previous_compensation"])
        self.assertEqual(result["issues"]["no_previous_compensation"], ["missing"])

    def test_blocker_remains_visible_with_missing_evidence(self):
        records = [record(name, value=False) if name == "stock_available"
                   else record(name) for name in REQUIREMENTS if name != "loss_confirmed"]
        result = assess(records)
        self.assertEqual(result["decision"], {
            "status": "ineligible", "blockers": ["stock_available"],
            "unknowns": ["loss_confirmed"],
        })

    def test_unsupported_scope_routes_to_review_even_with_all_true(self):
        result = assess([record(name) for name in REQUIREMENTS], supported_case=False)
        self.assertEqual(result["decision"]["status"], "needs_review")
        self.assertEqual(result["scope_issue"], "unsupported_case")

    def test_malformed_records_and_configuration_raise(self):
        for changes in ({"value": "false"}, {"value": 0},
                        {"observed_at": "2026-10-12T11:00:00"},
                        {"source_version": ""}, {"requirement": "unknown"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    assess([record("loss_confirmed", **changes)])
        with self.assertRaises(ValueError):
            assess([], max_age_seconds=0)


if __name__ == "__main__":
    unittest.main()
