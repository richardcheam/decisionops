"""Real PostgreSQL graph authority/recovery acceptance; no model endpoints."""
import os
import unittest
from unittest.mock import patch
import test_commerce_adaptive_core as core


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'PostgreSQL integration is opt-in')
class SpecialistAcceptanceTests(unittest.TestCase):
    setUp = core.AdaptiveCoreTests.setUp
    cleanup = core.AdaptiveCoreTests.cleanup
    case = core.AdaptiveCoreTests.case

    def owned(self, case=None):
        from decisionops.commerce import multi_agent as multi, adaptive_jobs as jobs
        run = multi.start(self.engine, (case or self.case())['id'], 'Lost parcel')
        job = jobs.claim(self.engine, job_id=run['job']['id'], action=jobs.SPECIALIST_ACTION)
        return run, jobs.Fence(job['id'], job['token'])

    def test_branches_have_bound_prerequisites_and_correct_read_ownership(self):
        from decisionops.commerce import multi_agent as multi, multi_agent_workflow as graph
        from decisionops.commerce.specialist_contracts import MockSpecialist
        test = self
        class Checked(MockSpecialist):
            def choose(self, request, cancel=None):
                saved = test.s.inspect(test.engine, request.run_id)
                tools = {o['tool'] for o in saved['observations']}
                test.assertTrue({'order_manifest', 'replacement_policy'} <= tools)
                return super().choose(request, cancel)
        run, fence = self.owned()
        result = graph.run(self.engine, fence, adapters={'order': Checked(), 'shipment': Checked()})
        self.assertEqual(result['state'], 'proposed')
        with self.engine.begin() as c:
            calls = multi.calls(c, run['id'])
        self.assertEqual({r['tool'] for r in calls if r['specialist'] == 'order'}, {'payment', 'compensation_history'})
        self.assertEqual({r['tool'] for r in calls if r['specialist'] == 'shipment'}, {'fulfilment', 'carrier_loss'})
        self.assertEqual(result['tool_attempts'], 7)
        self.assertEqual(len(result['observations']), 7)

    def test_restart_after_committed_branch_reuses_results_and_execution_is_once(self):
        from decisionops.commerce import multi_agent as multi, multi_agent_workflow as graph, adaptive_jobs as jobs
        from decisionops.commerce.cases import show_case, review_case
        from decisionops.commerce.execution import execute, reconcile
        run, fence = self.owned()
        class Restart(RuntimeError): pass
        def crash(name, saved):
            if name == 'order': raise Restart('Process exited after committed order branch')
        with self.assertRaises(Restart): graph.run(self.engine, fence, after_node=crash)
        saved = self.s.inspect(self.engine, run['id'])
        order_ids = {o['id'] for o in saved['observations'] if o['tool'] in ('payment', 'compensation_history')}
        self.assertEqual(len(order_ids), 2)
        with self.engine.begin() as c:
            c.exec_driver_sql("UPDATE commerce_adaptive_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (fence.job_id,))
        owned = jobs.claim(self.engine, job_id=fence.job_id, action=jobs.SPECIALIST_ACTION)
        new_fence = jobs.Fence(owned['id'], owned['token'])
        class NoRepeat:
            def choose(self, request, cancel): raise AssertionError('Committed order branch redispatched')
        result = graph.run(self.engine, new_fence, adapters={'order': NoRepeat()})
        self.assertEqual(result['state'], 'proposed')
        self.assertEqual(result['tool_attempts'], 7)
        self.assertEqual(order_ids, {o['id'] for o in result['observations'] if o['tool'] in ('payment', 'compensation_history')})
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
            case = show_case(c, run['case_id'])
            approved = review_case(c, case['id'], case['generation'], case['proposal_id'], case['proposal']['content_hash'], 'approve')
            operation_id = approved['approval']['operation_id']
            first = execute(c, case['id'], operation_id)
            second = execute(c, case['id'], operation_id)
            recovered = reconcile(c, operation_id)
            self.assertEqual([first['status'], second['status'], recovered['status']], ['verified'] * 3)
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_proposals').scalar_one(), 1)
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one(), 1)
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_reservations').scalar_one(), 1)

    def test_final_join_rejects_foreign_evidence_inserted_through_actual_storage(self):
        from decisionops.commerce import multi_agent as multi, schema as db
        from decisionops.commerce.adaptive_evidence import Observation, canonical
        import json
        from decisionops.commerce import adaptive_jobs as jobs
        run = multi.start(self.engine, self.case()['id'], 'Lost parcel', staff_ui=True)
        job = jobs.claim(self.engine, job_id=run['job']['id'], action=jobs.SPECIALIST_ACTION)
        fence = jobs.Fence(job['id'], job['token'])
        multi.support(self.engine, fence)
        multi.branch(self.engine, fence, 'order')
        multi.branch(self.engine, fence, 'shipment')
        with self.s.guarded(self.engine, run['id'], fence) as (c, saved, case):
            history = self.s.snapshot(c, saved)[0]
            content = json.loads(history.select('payment', __import__('datetime').datetime.now(__import__('datetime').timezone.utc)).content)
            content['request']['order_id'] = 'OTHER-ORDER'
            original = history.active('payment')[0]
            foreign = Observation('FOREIGN-PAYMENT', canonical(content), original.observed_at, original.expires_at)
            saved = self.s.step(c, saved, 'storage_test_insert', {})
            c.execute(db.adaptive_observations.insert().values(id=foreign.id, run_id=run['id'],
                      step_sequence=saved['context_version'], record=foreign.record(), applied=True))
            c.execute(db.adaptive_active.update().where((db.adaptive_active.c.run_id == run['id']) &
                      (db.adaptive_active.c.tool == 'payment')).values(observation_id=foreign.id))
        result = multi.join(self.engine, fence)
        self.assertEqual(result['state'], 'review')
        self.assertEqual(result['terminal']['reason'], 'invalid_committed_evidence')
        trace = multi.trace(self.engine, run['id'])
        self.assertEqual(trace['evidence'], [])
        self.assertEqual(trace['evidence_error'], 'invalid_committed_evidence')
        with self.engine.begin() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_proposals').scalar_one(), 0)
            self.assertEqual(c.exec_driver_sql('SELECT status FROM commerce_cases WHERE id=%s', (run['case_id'],)).scalar_one(), 'needs_review')
            from decisionops.commerce.conversations import status
            case=c.execute(db.cases.select().where(db.cases.c.id==run['case_id'])).mappings().one()
            followup=status(c,case)
            self.assertFalse(followup['evidence_current'])
            self.assertIn('requires staff review',followup['text'])
            self.assertEqual(followup['investigation']['reason'],'invalid_committed_evidence')

    def test_actual_conflicting_carrier_events_force_review_at_join(self):
        from datetime import datetime, timezone
        from decisionops.commerce import delivery_seed, delivery, multi_agent_workflow as graph
        from decisionops.commerce.cases import open_case
        from decisionops.commerce.read_tools import AssessmentRequest
        delivery_seed.seed(self.engine, now=datetime.now(timezone.utc))
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
            timeline = delivery.timeline(c, 'demo-store', 'PARCEL-DEMO-CONFLICT')
            self.assertTrue({'lost', 'delivered'} <= {r['status'] for r in timeline})
            case = open_case(c, AssessmentRequest('DEMO-CONFLICT', 'PARCEL-DEMO-CONFLICT', {'demo-tote': 1}))
        run, fence = self.owned(case)
        result = graph.run(self.engine, fence)
        self.assertEqual(result['state'], 'review')
        self.assertIsNone(result['assessment']['facts']['loss_confirmed'])
        with self.engine.begin() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_proposals').scalar_one(), 0)

    def test_bounded_model_transport_runs_graph_with_explicit_trace_label(self):
        from decisionops.commerce import multi_agent as multi, multi_agent_workflow as graph
        from decisionops.commerce.specialist_contracts import ModelDirectedSpecialist
        def local_transport(payload, *, timeout_ms, cancel):
            self.assertLessEqual(timeout_ms, 5000)
            action = next(a for a in payload['features']['allowed_actions'] if a['kind'] == 'read')
            return {**payload['binding'], 'action': action}
        adapter = ModelDirectedSpecialist(local_transport, enabled=True)
        run, fence = self.owned()
        result = graph.run(self.engine, fence, adapters={'order': adapter, 'shipment': adapter})
        self.assertEqual(result['state'], 'proposed')
        self.assertEqual(result['tool_attempts'], 7)
        trace = multi.trace(self.engine, run['id'])
        self.assertEqual(trace['mode'], 'model-directed-choices')
        self.assertEqual(trace['api_charge_usd'], 'unmeasured')

    def test_transient_carrier_read_retries_once_without_repeating_sibling_work(self):
        import sqlalchemy as sa
        from decisionops.commerce import multi_agent as multi, multi_agent_workflow as graph, schema as db
        failed = []
        def outage_once(connection, clause, *args):
            if (not failed and isinstance(clause, sa.sql.Select)
                    and any(col.table is db.shipments and col.name == 'carrier_status' for col in clause.selected_columns)):
                failed.append(True)
                raise sa.exc.SQLAlchemyError('Simulated one-shot carrier outage')
        sa.event.listen(self.engine, 'before_execute', outage_once)
        self.addCleanup(sa.event.remove, self.engine, 'before_execute', outage_once)
        run, fence = self.owned()
        result = graph.run(self.engine, fence)
        self.assertEqual(result['state'], 'proposed')
        self.assertEqual(result['tool_attempts'], 8)
        self.assertEqual(result['tool_counts']['carrier_loss'], 2)
        self.assertEqual(result['tool_counts']['payment'], 1)
        self.assertEqual(result['tool_counts']['compensation_history'], 1)
        with self.engine.begin() as c:
            shipment_calls = multi.calls(c, run['id'], 'shipment')
        self.assertEqual(len(shipment_calls), 3)
        self.assertTrue(all(r['dispatch_count'] == 1 for r in shipment_calls))
