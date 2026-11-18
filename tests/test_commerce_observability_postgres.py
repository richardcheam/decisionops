"""Actual graph restart/failure uses sanitized optional exporter only."""
import os
import unittest
from unittest.mock import patch
import test_commerce_specialists as fixtures

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class GraphTracingTests(unittest.TestCase):
    setUp=fixtures.SpecialistTests.setUp
    cleanup=fixtures.SpecialistTests.cleanup
    case=fixtures.SpecialistTests.case
    owned=fixtures.SpecialistTests.owned

    def test_graph_failure_resume_and_tool_events_are_correlated_and_redacted(self):
        from decisionops.commerce import multi_agent as multi,multi_agent_workflow as workflow,adaptive_jobs as jobs
        from decisionops.commerce.observability import SafeTracer
        events=[];trace=SafeTracer(enabled=True,sink=events.append)
        run,fence=self.owned()
        multi.support(self.engine,fence);multi.branch(self.engine,fence,'order')
        def crash(name,current):
            if name=='identity':raise RuntimeError('private-text-never-export')
        with self.assertRaisesRegex(RuntimeError,'private-text'):
            workflow.run(self.engine,fence,after_node=crash,tracer=trace)
        with self.engine.begin() as c:
            c.exec_driver_sql("UPDATE commerce_adaptive_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(fence.job_id,))
        claimed=jobs.claim(self.engine,job_id=fence.job_id,action=jobs.SPECIALIST_ACTION)
        saved=workflow.run(self.engine,jobs.Fence(claimed['id'],claimed['token']),tracer=trace)
        self.assertEqual(saved['state'],'proposed');self.assertTrue(trace.flush(2))
        self.assertTrue({'failure','resume','tool','stop'} <= {e['event'] for e in events})
        self.assertEqual({e['investigation_id'] for e in events},{run['id']})
        self.assertTrue(any(e.get('attempt')==2 for e in events))
        for secret in ('private-text','ORD-1042','SHIP-1042','report','items','shirt-blue'):
            self.assertNotIn(secret,str(events))
        self.assertEqual(saved['tool_counts']['payment'],1);self.assertEqual(saved['tool_counts']['compensation_history'],1)

    def test_exporter_outage_leaves_same_proposal_and_no_business_effects(self):
        from decisionops.commerce import multi_agent_workflow as workflow
        from decisionops.commerce.observability import SafeTracer
        def unavailable(_):raise RuntimeError('fictional-exporter-outage')
        trace=SafeTracer(enabled=True,sink=unavailable)
        run,fence=self.owned();saved=workflow.run(self.engine,fence,tracer=trace)
        self.assertEqual(saved['state'],'proposed');trace.flush(1);self.assertGreater(trace.errors,0)
        with self.engine.connect() as c:self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one(),0)
