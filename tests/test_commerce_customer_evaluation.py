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

    def test_specialist_comparison_keeps_routing_and_source_inputs_matched(self):
        from decisionops.commerce.customer_evaluation import evaluate
        from decisionops.commerce.live_specialist_evaluation import EvaluationTracer
        from decisionops.commerce.specialist_contracts import MockSpecialist

        events=[]
        tracer=EvaluationTracer(enabled=True,sink=events.append,max_queue=2048)
        result=evaluate(os.environ['COMMERCE_TEST_DATABASE_URL'],specialist_adapter=MockSpecialist(),tracer=tracer)
        self.assertTrue(tracer.flush(timeout=3))
        self.assertEqual(tracer.dropped,0)
        self.assertFalse(any(event.get('reason')=='worker_error' for event in events))
        self.assertEqual(len(result['runs']),15)
        for case in result['population']:
            rows={row['mode']:row for row in result['runs'] if row['case']==case}
            self.assertEqual(set(rows),{'rules','mock_specialists','injected_specialists'})
            self.assertEqual(len({row['source_hash'] for row in rows.values()}),1)
            self.assertTrue(all(row['matches_expected'] for row in rows.values()),rows)
            baseline=rows['mock_specialists']
            injected=rows['injected_specialists']
            self.assertEqual(injected['tool_attempts'],baseline['tool_attempts'])
            if case in ('resolution','stale_evidence','carrier_outage'):
                self.assertTrue(injected['investigation_id'])
                self.assertTrue(any(event['investigation_id']==injected['investigation_id']
                    and event['event']=='stop' for event in events))
