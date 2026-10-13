"""Model-free proposal binding tests; no database packages needed."""
import copy
import unittest

from decisionops.commerce.eligibility import REQUIREMENTS
from decisionops.commerce.proposals import build_proposal, check_proposal, document_hash


class ProposalTests(unittest.TestCase):
    def assessment(self):
        return {
            "decision": {"status": "eligible_to_propose", "blockers": [], "unknowns": []},
            "request": {"order_id": "ORD-1", "shipment_id": "SHIP-1", "items": {"blue-M": 1}},
            "policy_id": "policy-v1", "scope_reasons": [],
            "read_tools": [{"requirement": name, "source_version": "version-" + name}
                           for name in REQUIREMENTS],
        }

    def test_bound_contents_do_not_change_when_input_changes(self):
        assessment = self.assessment()
        proposal = build_proposal(assessment)
        assessment["request"]["items"]["blue-M"] = 2
        self.assertEqual(proposal["request"]["items"], {"blue-M": 1})
        self.assertEqual(set(proposal["source_versions"]), set(REQUIREMENTS))
        self.assertEqual(proposal["policy_id"], "policy-v1")

    def test_only_eligible_supported_cases_produce_proposals(self):
        for status in ("ineligible", "needs_review"):
            assessment = self.assessment()
            assessment["decision"]["status"] = status
            self.assertIsNone(build_proposal(assessment))
        assessment = self.assessment()
        assessment["scope_reasons"] = ["partial_request"]
        self.assertIsNone(build_proposal(assessment))

    def test_changed_records_invalidate_even_if_still_eligible(self):
        assessment = self.assessment()
        proposal = build_proposal(assessment)
        assessment["read_tools"][0]["source_version"] = "changed"
        result = check_proposal(proposal, assessment)
        self.assertEqual(result["status"], "requires_reinvestigation")
        self.assertIn("paid", result["changed_requirements"])

    def test_expired_evidence_invalidates_without_version_change(self):
        assessment = self.assessment()
        proposal = build_proposal(assessment)
        assessment["decision"] = {"status": "needs_review", "blockers": [], "unknowns": ["loss_confirmed"]}
        result = check_proposal(proposal, assessment)
        self.assertEqual(result["changed_requirements"], [])
        self.assertEqual(result["status"], "requires_reinvestigation")
        self.assertFalse(result["execution_authorized"])

    def test_order_shipment_quantities_and_policy_changes_invalidate(self):
        original = self.assessment()
        proposal = build_proposal(original)
        for field in ("order_id", "shipment_id", "items", "policy_id"):
            assessment = copy.deepcopy(original)
            if field == "policy_id":
                assessment[field] = "policy-v2"
            else:
                assessment["request"][field] = {"blue-M": 2} if field == "items" else "other"
            self.assertEqual(check_proposal(proposal, assessment)["status"], "requires_reinvestigation")

    def test_hash_is_stable_and_valid_check_never_authorizes_execution(self):
        assessment = self.assessment()
        proposal = build_proposal(assessment)
        self.assertEqual(document_hash(proposal), document_hash(dict(reversed(list(proposal.items())))))
        self.assertEqual(check_proposal(proposal, assessment)["status"], "valid_for_review")
        self.assertFalse(check_proposal(proposal, assessment)["execution_authorized"])
