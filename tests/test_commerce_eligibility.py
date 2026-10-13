import unittest

from decisionops.commerce.eligibility import REQUIREMENTS, evaluate_eligibility


class EligibilityTests(unittest.TestCase):
    def test_all_requirements_true_allows_proposal(self):
        facts = dict.fromkeys(REQUIREMENTS, True)
        self.assertEqual(evaluate_eligibility(facts), {
            "status": "eligible_to_propose", "blockers": [], "unknowns": [],
        })

    def test_each_false_requirement_blocks_proposal(self):
        for requirement in REQUIREMENTS:
            with self.subTest(requirement=requirement):
                facts = dict.fromkeys(REQUIREMENTS, True)
                facts[requirement] = False
                self.assertEqual(evaluate_eligibility(facts), {
                    "status": "ineligible", "blockers": [requirement], "unknowns": [],
                })

    def test_blockers_take_precedence_but_unknowns_remain_visible(self):
        facts = dict.fromkeys(REQUIREMENTS, True)
        facts["stock_available"] = False
        facts["paid"] = False
        facts["loss_confirmed"] = None
        self.assertEqual(evaluate_eligibility(facts), {
            "status": "ineligible",
            "blockers": ["paid", "stock_available"],
            "unknowns": ["loss_confirmed"],
        })

    def test_missing_or_explicit_unknown_loss_requires_review(self):
        for include_key in (False, True):
            with self.subTest(include_key=include_key):
                facts = dict.fromkeys(REQUIREMENTS, True)
                del facts["loss_confirmed"]
                if include_key:
                    facts["loss_confirmed"] = None
                self.assertEqual(evaluate_eligibility(facts), {
                    "status": "needs_review", "blockers": [],
                    "unknowns": ["loss_confirmed"],
                })

    def test_empty_evidence_requires_review_for_every_requirement(self):
        self.assertEqual(evaluate_eligibility({}), {
            "status": "needs_review", "blockers": [],
            "unknowns": list(REQUIREMENTS),
        })

    def test_malformed_values_are_rejected_instead_of_authorizing_proposal(self):
        for value in ("false", "true", 0, 1, [], {}):
            with self.subTest(value=value):
                facts = dict.fromkeys(REQUIREMENTS, True)
                facts["loss_confirmed"] = value
                with self.assertRaisesRegex(ValueError, "loss_confirmed"):
                    evaluate_eligibility(facts)


if __name__ == "__main__":
    unittest.main()
