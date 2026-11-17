"""Frozen synthetic public-flow comparison; never invokes a paid model."""
import os
import unittest

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class CustomerEvaluationTests(unittest.TestCase):
    def test_same_five_sources_rules_and_simulated_adapter_keep_business_boundaries(self):
        from decisionops.commerce.customer_evaluation import evaluate
        result=evaluate(os.environ['COMMERCE_TEST_DATABASE_URL'],simulate_adapter=True)
        self.assertEqual(len(result['runs']),10)
        self.assertEqual(result['paid_model_calls'],0)
        self.assertIsNone(result['live_model_quality']);self.assertIsNone(result['live_model_cost_usd'])
        for case in ('resolution','ambiguity','wrong_owner','stale_evidence','carrier_outage'):
            rows=[r for r in result['runs'] if r['case']==case]
            self.assertEqual(len({r['source_hash'] for r in rows}),1)
            self.assertTrue(all(r['matches_expected'] for r in rows),rows)
