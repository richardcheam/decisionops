"""PostgreSQL specialist ownership, evidence admission, and restart contracts."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import test_commerce_adaptive_core as core


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),
                     'PostgreSQL integration is opt-in')
class SpecialistTests(unittest.TestCase):
    setUp = core.AdaptiveCoreTests.setUp
    cleanup = core.AdaptiveCoreTests.cleanup
    case = core.AdaptiveCoreTests.case

    def owned(self, case=None):
        from decisionops.commerce import multi_agent as multi, adaptive_jobs as jobs
        run = multi.start(self.engine, (case or self.case())['id'], 'Lost parcel')
        owned = jobs.claim(self.engine, job_id=run['job']['id'],
                           action=jobs.SPECIALIST_ACTION)
        self.assertIsNotNone(owned)
        return run, jobs.Fence(owned['id'], owned['token'])

    def saved(self, run):
        return self.s.inspect(self.engine, run['id'])

    def test_seven_facts_publish_existing_proposal_and_require_exact_approval(self):
        from decisionops.commerce import multi_agent_workflow as workflow
        from decisionops.commerce.cases import show_case, review_case
        from decisionops.commerce.execution import execute, reconcile
        run, fence = self.owned()
        workflow.run(self.engine, fence)
        saved = self.saved(run)
        self.assertEqual(saved['state'], 'proposed')
        self.assertEqual(saved['tool_attempts'], 7)
        self.assertEqual(len(saved['observations']), 7)
        self.assertTrue(all(value is True for value in saved['assessment']['facts'].values()))
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
            case = show_case(c, run['case_id'])
            self.assertEqual(case['status'], 'awaiting_review')
            self.assertIsNone(case['approval_id'])
            self.assertEqual(case['proposal']['document']['schema_version'], 1)
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one(), 0)
            approved = review_case(c, case['id'], case['generation'], case['proposal_id'],
                                   case['proposal']['content_hash'], 'approve')
            operation = approved['approval']['operation_id']
            self.assertEqual(execute(c, case['id'], operation)['status'], 'verified')
            self.assertEqual(reconcile(c, operation)['status'], 'verified')

    def test_legacy_claims_cannot_take_specialist_job_even_by_id(self):
        from decisionops.commerce import multi_agent as multi, adaptive_jobs as jobs
        run = multi.start(self.engine, self.case()['id'], 'Lost parcel')
        for staff_only in (False, True):
            self.assertIsNone(jobs.claim(self.engine, job_id=run['job']['id'],
                                         staff_only=staff_only))
        self.assertIsNotNone(jobs.claim(self.engine, job_id=run['job']['id'],
                                        action=jobs.SPECIALIST_ACTION))

    def test_completed_order_branch_is_not_dispatched_again_on_graph_resume(self):
        from decisionops.commerce import multi_agent as multi, multi_agent_workflow as workflow
        run, fence = self.owned()
        multi.support(self.engine, fence)
        multi.branch(self.engine, fence, 'order')
        before = self.saved(run)
        order_ids = {o['id'] for o in before['observations']
                     if o['tool'] in ('payment', 'compensation_history')}
        self.assertEqual(len(order_ids), 2)
        class NoRedispatch:
            def choose(self, request, cancel):
                raise AssertionError('Completed order specialist was dispatched again')
        workflow.run(self.engine, fence, adapters={'order': NoRedispatch()})
        after = self.saved(run)
        self.assertEqual(after['state'], 'proposed')
        self.assertEqual(order_ids, {o['id'] for o in after['observations']
                                    if o['tool'] in ('payment', 'compensation_history')})
        self.assertEqual(after['tool_attempts'], 7)

    def test_sibling_context_update_does_not_discard_bound_order_result(self):
        from decisionops.commerce import multi_agent as multi
        run, fence = self.owned()
        multi.support(self.engine, fence)
        entered, release = Event(), Event()
        original = multi.read_tool
        def held(connection, tool, *args, **kwargs):
            if tool == 'payment':
                entered.set()
                if not release.wait(8):
                    raise AssertionError('Payment result was never released')
            return original(connection, tool, *args, **kwargs)
        with ThreadPoolExecutor(1) as pool, patch.object(multi, 'read_tool', side_effect=held):
            pending = pool.submit(multi.branch, self.engine, fence, 'order')
            try:
                self.assertTrue(entered.wait(3), 'Order read did not reach dispatch boundary')
                old_context = self.saved(run)['context_version']
                multi.support(self.engine, fence, tools=('compensation_history', 'inventory'))
                self.assertGreater(self.saved(run)['context_version'], old_context)
            finally:
                release.set()
            pending.result(5)
        saved = self.saved(run)
        self.assertTrue(saved['assessment']['facts']['paid'])
        self.assertTrue(saved['assessment']['facts']['no_previous_compensation'])
        self.assertTrue(saved['assessment']['facts']['stock_available'])

    def test_wrong_request_observation_cannot_supply_payment_fact(self):
        from decisionops.commerce import multi_agent as multi
        from decisionops.commerce.adaptive_evidence import Observation, canonical
        run, fence = self.owned()
        multi.support(self.engine, fence)
        original = multi.read_tool
        def foreign(*args, **kwargs):
            obs = original(*args, **kwargs)
            if obs.record()['tool'] != 'payment':
                return obs
            import json
            content = json.loads(obs.content)
            content['request']['order_id'] = 'ORD-OTHER-CASE'
            return Observation(obs.id, canonical(content), obs.observed_at, obs.expires_at)
        with patch.object(multi, 'read_tool', side_effect=foreign):
            try:
                multi.branch(self.engine, fence, 'order')
            except ValueError:
                pass  # Rejecting before admission is an acceptable failure disposition.
        saved = self.saved(run)
        self.assertIsNone(saved['assessment']['facts']['paid'])
        self.assertNotEqual(saved['state'], 'proposed')
        with self.engine.begin() as c:
            history = self.s.snapshot(c, saved)[0]
            self.assertFalse(any(o.record()['tool'] == 'payment' and o.value is True
                                 for o in history.active()))

    def test_case_change_during_read_discards_late_result(self):
        from decisionops.commerce import multi_agent as multi
        from decisionops.commerce.cases import escalate_case, show_case
        run, fence = self.owned()
        multi.support(self.engine, fence)
        entered, release = Event(), Event()
        original = multi.read_tool
        def held(connection, tool, *args, **kwargs):
            if tool == 'payment':
                entered.set()
                if not release.wait(8):
                    raise AssertionError('Stale read was never released')
            return original(connection, tool, *args, **kwargs)
        with ThreadPoolExecutor(1) as pool, patch.object(multi, 'read_tool', side_effect=held):
            pending = pool.submit(multi.branch, self.engine, fence, 'order')
            try:
                self.assertTrue(entered.wait(3))
                with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
                    escalate_case(c, run['case_id'], 'Staff escalation')
            finally:
                release.set()
            pending.result(5)
        saved = self.saved(run)
        self.assertIsNone(saved['assessment']['facts']['paid'])
        self.assertNotEqual(saved['state'], 'proposed')
        with self.engine.begin() as c:
            case = show_case(c, run['case_id'])
            self.assertEqual(case['status'], 'escalated')
            self.assertIsNone(case['proposal_id'])

    def test_execute_choice_is_rejected_without_business_execution(self):
        from decisionops.commerce import multi_agent as multi
        run, fence = self.owned()
        multi.support(self.engine, fence)
        class Malicious:
            def choose(self, request, cancel):
                return {'kind': 'execute', 'tool': 'payment', 'override': True}
        multi.branch(self.engine, fence, 'order', adapter=Malicious())
        saved = self.saved(run)
        self.assertIsNone(saved['assessment']['facts']['paid'])
        self.assertNotEqual(saved['state'], 'proposed')
        with self.engine.begin() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one(), 0)
            calls = c.exec_driver_sql('SELECT state,dispatch_count FROM commerce_specialist_calls WHERE run_id=%s',
                                      (run['id'],)).all()
        self.assertTrue(calls)
        self.assertTrue(all(count == 1 for state, count in calls))

    def test_cancelled_decision_keeps_sibling_evidence_and_never_redispatches(self):
        from decisionops.commerce import multi_agent as multi
        run, fence = self.owned()
        multi.support(self.engine, fence)
        multi.branch(self.engine, fence, 'order')
        before = self.saved(run)
        retained = {o['id'] for o in before['observations']}
        entered, cancelled = Event(), Event()
        class Held:
            def choose(self, request, cancel):
                entered.set()
                if not cancel.wait(5):
                    raise AssertionError('Specialist did not receive cancellation')
                raise RuntimeError('Cooperative cancellation')
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(multi.branch, self.engine, fence, 'shipment',
                                  adapter=Held(), cancel=cancelled)
            self.assertTrue(entered.wait(3))
            cancelled.set()
            pending.result(4)
        partial = self.saved(run)
        self.assertTrue(retained <= {o['id'] for o in partial['observations']})
        self.assertTrue(partial['assessment']['facts']['paid'])
        self.assertTrue(partial['assessment']['facts']['no_previous_compensation'])
        self.assertIsNone(partial['assessment']['facts']['loss_confirmed'])
        with self.engine.begin() as c:
            before_calls = c.exec_driver_sql('SELECT id,state,dispatch_count FROM commerce_specialist_calls WHERE run_id=%s ORDER BY id',
                                             (run['id'],)).all()
        self.assertTrue(any(state == 'uncertain' for _, state, _ in before_calls))
        multi.recover(self.engine, fence)
        class NoRedispatch:
            def choose(self, request, cancel):
                raise AssertionError('Uncertain decision was redispatched')
        multi.branch(self.engine, fence, 'shipment', adapter=NoRedispatch())
        with self.engine.begin() as c:
            after_calls = c.exec_driver_sql('SELECT id,state,dispatch_count FROM commerce_specialist_calls WHERE run_id=%s ORDER BY id',
                                            (run['id'],)).all()
        self.assertEqual(before_calls, after_calls)

    def test_wrong_tool_and_missing_dependencies_are_discarded_without_pointer_corruption(self):
        import json
        from decisionops.commerce import multi_agent as multi
        from decisionops.commerce.adaptive_evidence import Observation, canonical
        from decisionops.commerce.adaptive_policies import Action
        class PaymentFirst:
            def choose(self, request, cancel):
                return Action('read', 'payment')
        for tamper in ('tool', 'dependencies'):
            with self.subTest(tamper=tamper):
                run, fence = self.owned()
                multi.support(self.engine, fence)
                original = multi.read_tool
                def malformed(*args, **kwargs):
                    obs = original(*args, **kwargs)
                    content = json.loads(obs.content)
                    if tamper == 'tool':
                        content['tool'] = 'inventory'
                    else:
                        content['dependencies'] = []
                    return Observation(obs.id, canonical(content), obs.observed_at, obs.expires_at)
                with patch.object(multi, 'read_tool', side_effect=malformed):
                    multi.branch(self.engine, fence, 'order', adapter=PaymentFirst())
                saved = self.saved(run)  # Includes the immutable-history/active-pointer consistency check.
                self.assertIsNone(saved['assessment']['facts']['paid'])
                self.assertIsNone(saved['assessment']['facts']['stock_available'])
                with self.engine.begin() as c:
                    rows = c.exec_driver_sql('SELECT applied FROM commerce_adaptive_observations WHERE run_id=%s ORDER BY step_sequence',
                                              (run['id'],)).scalars().all()
                    calls = multi.calls(c, run['id'], 'order')
                self.assertEqual(rows, [True, True, False])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['disposition'], 'discarded')

    def test_late_interrupted_read_is_audited_once_without_reactivating_evidence(self):
        from decisionops.commerce import multi_agent as multi
        from decisionops.commerce.adaptive_policies import Action
        class PaymentFirst:
            def choose(self, request, cancel):
                return Action('read', 'payment')
        run, fence = self.owned()
        multi.support(self.engine, fence)
        entered, release = Event(), Event()
        original = multi.read_tool
        def held(connection, tool, *args, **kwargs):
            self.assertEqual(tool, 'payment')
            entered.set()
            if not release.wait(8):
                raise AssertionError('Interrupted read was never released')
            return original(connection, tool, *args, **kwargs)
        with ThreadPoolExecutor(1) as pool, patch.object(multi, 'read_tool', side_effect=held):
            pending = pool.submit(multi.branch, self.engine, fence, 'order', adapter=PaymentFirst())
            try:
                self.assertTrue(entered.wait(3))
                multi.recover(self.engine, fence)
            finally:
                release.set()
            pending.result(5)
        saved = self.saved(run)
        self.assertIsNone(saved['assessment']['facts']['paid'])
        with self.engine.begin() as c:
            calls = multi.calls(c, run['id'], 'order')
            observations = c.exec_driver_sql("SELECT applied FROM commerce_adaptive_observations WHERE run_id=%s AND record->>'tool'='payment'",
                                             (run['id'],)).scalars().all()
        self.assertEqual(observations, [False])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['tool_state'], 'interrupted')
        self.assertEqual(calls[0]['disposition'], 'discarded')
        self.assertEqual(calls[0]['dispatch_count'], 1)

    def test_trace_redacts_report_from_coordinator_decision_features(self):
        from decisionops.commerce import multi_agent as multi, adaptive_jobs as jobs
        from decisionops.commerce.adaptive_evidence import canonical
        sentinel = 'PRIVATE-REPORT-SENTINEL-830af4'
        run = multi.start(self.engine, self.case()['id'], sentinel)
        owned = jobs.claim(self.engine, job_id=run['job']['id'], action=jobs.SPECIALIST_ACTION)
        fence = jobs.Fence(owned['id'], owned['token'])
        multi.support(self.engine, fence)
        self.assertTrue(any(s['kind'] == 'decision_reserved' for s in self.saved(run)['steps']))
        trace = multi.trace(self.engine, run['id'])
        self.assertNotIn(sentinel, canonical(trace))
        self.assertTrue(trace['steps'])
        self.assertTrue(trace['evidence'])

    def test_reclaimed_coordinator_reservation_recovers_before_graph_advancement(self):
        from decisionops.commerce import multi_agent as multi, multi_agent_workflow as workflow, adaptive_jobs as jobs
        run, fence = self.owned()
        with patch.object(self.s, 'read_tool', side_effect=RuntimeError('Process died after read reservation')):
            with self.assertRaisesRegex(RuntimeError, 'Process died'):
                multi.support(self.engine, fence)
        interrupted = self.saved(run)
        self.assertIsNotNone(interrupted['pending_token'])
        self.assertEqual(interrupted['tool_attempts'], 1)
        with self.engine.begin() as c:
            c.exec_driver_sql("UPDATE commerce_adaptive_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s AND token=%s",
                              (fence.job_id, fence.token))
        reclaimed = jobs.claim(self.engine, job_id=fence.job_id, action=jobs.SPECIALIST_ACTION)
        self.assertIsNotNone(reclaimed)
        self.assertNotEqual(reclaimed['token'], fence.token)
        resumed = jobs.Fence(reclaimed['id'], reclaimed['token'])
        workflow.run(self.engine, resumed)
        saved = self.saved(run)
        self.assertIsNone(saved['pending_token'])
        self.assertEqual(saved['state'], 'proposed')
        self.assertEqual(saved['tool_attempts'], 8)  # The abandoned read remains charged.
        self.assertEqual(saved['tool_counts']['order_manifest'], 2)
        self.assertTrue(any(s['kind'] == 'read_interrupted' for s in saved['steps']))

    def test_specialist_staff_requests_replay_coalesce_and_reject_changed_identity(self):
        from decisionops.commerce import staff_investigations as staff
        case = self.case()
        def enqueue(request_id, generation=None, report='Lost parcel', mode='mock-specialists'):
            with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
                return staff.enqueue(c, self.engine, case['id'], report, request_id,
                                     case['generation'] if generation is None else generation, mode=mode)
        first = enqueue('SPECIALIST-A')
        self.assertEqual(enqueue('SPECIALIST-A')['id'], first['id'])
        self.assertEqual(enqueue('SPECIALIST-B')['id'], first['id'])
        for kwargs in ({'report': 'Changed report'}, {'mode': 'rules'},
                       {'generation': first['generation']+1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                enqueue('SPECIALIST-A', **kwargs)
        with self.assertRaises(ValueError):
            enqueue('STALE-NEW-IDENTITY', generation=first['generation']+1)
        with self.engine.begin() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_adaptive_runs WHERE case_id=%s',
                                               (case['id'],)).scalar_one(), 1)

    def test_conflicting_authority_and_expired_tracking_do_not_pass_join(self):
        from datetime import timedelta
        from decisionops.commerce import multi_agent as multi, multi_agent_workflow as workflow
        from decisionops.commerce.adaptive_evidence import Observation, canonical
        import json
        for mode in ('conflicting', 'expired'):
            with self.subTest(mode=mode):
                run,fence=self.owned()
                original=multi.read_tool
                def invalid(*args,**kwargs):
                    obs=original(*args,**kwargs)
                    if obs.record()['tool']!='carrier_loss':return obs
                    content=json.loads(obs.content)
                    if mode=='conflicting':
                        content.update(value=None,status='success',reason='conflicting_records')
                        return Observation(obs.id,canonical(content),obs.observed_at,obs.expires_at)
                    from datetime import datetime
                    return Observation(obs.id,obs.content,obs.observed_at,(datetime.fromisoformat(obs.observed_at)-timedelta(seconds=1)).isoformat())
                with patch.object(multi,'read_tool',side_effect=invalid):workflow.run(self.engine,fence)
                saved=self.saved(run)
                self.assertEqual(saved['state'],'review')
                self.assertIsNone(saved['assessment']['facts']['loss_confirmed'])
                self.assertIsNone(saved['terminal'].get('proposal_id'))
                self.assertTrue(saved['assessment']['facts']['paid'])

    def test_successful_model_result_after_decision_deadline_is_discarded(self):
        from decisionops.commerce import multi_agent as multi
        from decisionops.commerce.specialist_contracts import MockSpecialist
        run,fence=self.owned();multi.support(self.engine,fence)
        from contextlib import contextmanager
        import time
        original=multi.service.guarded
        @contextmanager
        def wait_before_admission(engine,run_id,owner):
            with multi.service.transaction(engine,readonly=True) as c:
                rows=multi.calls(c,run_id,'order')
            if rows and rows[-1]['state']=='dispatching':
                from datetime import datetime,timezone
                time.sleep(max(0,(rows[-1]['deadline']-datetime.now(timezone.utc)).total_seconds())+.02)
            with original(engine,run_id,owner) as context:yield context
        with patch.object(multi.service,'guarded',side_effect=wait_before_admission):
            multi.branch(self.engine,fence,'order',adapter=MockSpecialist())
        saved=self.saved(run)
        self.assertIsNone(saved['assessment']['facts']['paid'])
        self.assertIsNone(saved['assessment']['facts']['shipped'])
        with self.engine.begin() as c:row=multi.calls(c,run['id'],'order')[0]
        self.assertEqual(row['dispatch_count'],1);self.assertEqual(row['disposition'],'discarded')

    def test_parallel_reservation_and_dispatch_claim_have_one_effect(self):
        from decisionops.commerce import multi_agent as multi
        from decisionops.commerce.specialist_contracts import MockSpecialist
        from threading import Lock
        run,fence=self.owned();multi.support(self.engine,fence)
        with ThreadPoolExecutor(2) as pool:
            rows=list(pool.map(lambda _:multi.reserve(self.engine,fence,'order'),range(2)))
        self.assertEqual(rows[0]['id'],rows[1]['id'])
        class Counted(MockSpecialist):
            count=0
            lock=Lock()
            def choose(self,request,cancel):
                with self.lock:self.count+=1
                return super().choose(request,cancel)
        adapter=Counted()
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _:multi.choose(self.engine,fence,rows[0],adapter),range(2)))
        self.assertEqual(adapter.count,1)
        with self.engine.begin() as c:row=multi.calls(c,run['id'],'order')[0]
        multi.read(self.engine,fence,row);multi.read(self.engine,fence,row)
        saved=self.saved(run)
        self.assertEqual(saved['tool_attempts'],3)
        self.assertEqual(saved['decision_attempts'],3)
        self.assertEqual(len(saved['observations']),3)

    def test_actual_graph_interrupt_after_order_commit_replays_no_effects(self):
        from decisionops.commerce import multi_agent as multi,multi_agent_workflow as graph
        run,fence=self.owned()
        def interrupt(name,current):
            if name=='order':raise RuntimeError('Injected graph interruption after domain commit')
        with self.assertRaisesRegex(RuntimeError,'graph interruption'):
            graph.run(self.engine,fence,after_node=interrupt)
        with self.engine.begin() as c:
            before={r['id'] for r in multi.calls(c,run['id'],'order')}
        self.assertEqual(len(before),2)
        class NoOrderReplay:
            def choose(self,request,cancel):raise AssertionError('Replayed order dispatch')
        graph.run(self.engine,fence,adapters={'order':NoOrderReplay()})
        self.assertEqual(self.saved(run)['state'],'proposed')
        with self.engine.begin() as c:
            self.assertEqual(before,{r['id'] for r in multi.calls(c,run['id'],'order')})
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_proposals').scalar_one(),1)
        graph.run(self.engine,fence,adapters={'order':NoOrderReplay()})
        self.assertEqual(self.saved(run)['tool_attempts'],7)

    def test_existing_parent_caps_stop_without_new_specialist_dispatch(self):
        from decisionops.commerce import multi_agent as multi,multi_agent_workflow as graph
        run,fence=self.owned()
        with self.s.guarded(self.engine,run['id'],fence) as (c,current,case):
            self.s.step(c,current,'test_budget_boundary',{},decision_attempts=16)
        graph.run(self.engine,fence)
        saved=self.saved(run)
        self.assertEqual(saved['state'],'review')
        self.assertEqual(saved['tool_attempts'],0)
        self.assertEqual(saved['decision_attempts'],16)
        with self.engine.begin() as c:self.assertEqual(multi.calls(c,run['id']),[])
