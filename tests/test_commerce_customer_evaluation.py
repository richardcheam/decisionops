"""Frozen synthetic public-flow comparison; never invokes a paid model."""
from importlib.util import find_spec
import os
import unittest
from test_commerce_local_llm import model_server


@unittest.skipUnless(find_spec('sqlalchemy'), 'Requires commerce dependencies')
class LocalBenchmarkTransportTests(unittest.TestCase):
    def test_cap_stops_real_http_requests_and_invalid_output_is_counted(self):
        from decisionops.commerce.customer_evaluation import LocalBenchmarkModel
        from decisionops.commerce.role_actions import ModelActionAdapter, ModelUnavailable

        received = []

        def choose(path, payload):
            received.append(path)
            return {'kind': 'help' if len(received) == 1 else 'approve'}

        with model_server(choose) as env:
            model = LocalBenchmarkModel('local-test:latest', env['COMMERCE_OLLAMA_URL'], 2)
            model.case = 'cap-test'
            router = ModelActionAdapter(model.route, fallback=False).staff()
            self.assertEqual(router.choose('hello').kind, 'help')
            with self.assertRaises(ModelUnavailable):
                router.choose('investigate this case')
            with self.assertRaises(ModelUnavailable):
                router.choose('which parcels are late?')
        self.assertEqual(received, ['/api/chat', '/api/chat'])
        self.assertEqual([call['status'] for call in model.calls], ['valid', 'invalid'])
        self.assertEqual(model.blocked, {'cap': 1, 'uncertain': 0, 'cancelled': 0})

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
