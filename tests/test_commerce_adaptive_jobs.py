"""Required PostgreSQL Stage 3 recovery; owned schemas, no models."""
import os
import time
import unittest
from unittest.mock import patch
import test_commerce_adaptive_core as core

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'PostgreSQL integration is opt-in')
class AdaptiveJobTests(unittest.TestCase):
    setUp=core.AdaptiveCoreTests.setUp
    cleanup=core.AdaptiveCoreTests.cleanup
    case=core.AdaptiveCoreTests.case
    def queued(self,policy='fixed',deadline=240):
        from decisionops.commerce import adaptive_jobs as jobs
        return jobs.enqueue(self.engine,self.case()['id'],'Lost parcel',policy=policy,deadline_seconds=deadline)
    def claim(self,job,seconds=30):
        from decisionops.commerce import adaptive_jobs as j
        return j.claim(self.engine,job_id=job['id'],lease_seconds=seconds)

    def test_legacy_partition_and_concurrent_claim(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import jobs
        j=self.queued()
        with self.engine.begin() as c:self.assertIsNone(jobs.claim(c))
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.claim(j),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_renew_fence_and_run_deadline(self):
        from decisionops.commerce import adaptive_jobs as j
        from decisionops.commerce.jobs import LeaseLost
        saved=self.queued(deadline=2);owned=self.claim(saved,1)
        renewed=j.renew(self.engine,owned['id'],owned['token'],30)
        run=self.s.inspect(self.engine,owned['run_id']);self.assertLessEqual(renewed['lease_until'],run['deadline'])
        with self.assertRaises(LeaseLost):j.renew(self.engine,owned['id'],'stale',30)
        with self.assertRaises(LeaseLost):self.s.advance(self.engine,run['id'],{'kind':'read','tool':'order_manifest'},expected_context=run['context_version'])

    def test_reserve_race_is_one_counted_request(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import adaptive_accounting as a,adaptive_jobs as j
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        with ThreadPoolExecutor(2) as p:calls=list(p.map(lambda _:a.prepare(self.engine,owned['run_id'],f),range(2)))
        self.assertEqual(calls[0]['id'],calls[1]['id'])
        run=self.s.inspect(self.engine,owned['run_id']);self.assertEqual(run['decision_attempts'],1)
        self.assertEqual(calls[0]['reserved_cost_usd'],0)

    def test_restart_reserved_and_settled_never_repeats_adapter(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        a.prepare(self.engine,owned['run_id'],f)
        with self.assertRaises(Interrupted):tick(self.engine,f,fault='after_result')
        with patch('decisionops.commerce.adaptive_recommendations.FakeAdapter.choose',side_effect=AssertionError('Redispatch')):
            tick(self.engine,f)
        run=self.s.inspect(self.engine,owned['run_id']);self.assertEqual(run['tool_attempts'],1)
        self.assertEqual(run['decision_attempts'],1)

    def test_unknown_dispatch_requires_explicit_recovery(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        with self.assertRaises(Interrupted):tick(self.engine,f,fault='after_dispatch')
        result=tick(self.engine,f);self.assertEqual(result['event'],'uncertain_decision')
        with self.engine.begin() as c:
            call=a.latest(c,owned['run_id']);self.assertEqual(call['state'],'dispatching')
            self.assertIsNone(call['actual_ms']);self.assertEqual(call['dispatch_count'],1)
        result=j.recover(self.engine,f)
        self.assertEqual(result['decision_attempts'],1)
        tick(self.engine,f)
        self.assertEqual(self.s.inspect(self.engine,owned['run_id'])['decision_attempts'],2)

    def test_checkpoint_loss_reconstructs_without_duplicate_publication(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_workflow as w
        from decisionops.commerce.adaptive_runner import run_until_pause
        from decisionops.commerce import schema as db
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        w.setup_checkpoints(self.engine)
        first=run_until_pause(self.engine,f);self.assertEqual(first['state'],'proposed')
        one=w.project(self.engine,owned['id']);namespace,url=w.checkpoint_url(self.engine)
        with self.engine.begin() as c:c.exec_driver_sql('DROP SCHEMA "'+namespace+'" CASCADE')
        w.setup_checkpoints(self.engine);two=w.resume(self.engine,owned['id'])
        self.assertEqual(one['context_version'],two['context_version'])
        with self.engine.begin() as c:self.assertEqual(c.execute(db.proposals.select()).all().__len__(),1)

    def test_cancellation_during_decision_keeps_uncertain_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce.adaptive_recommendations import FakeAdapter
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        with ThreadPoolExecutor(1) as p:
            pending=p.submit(tick,self.engine,f,adapter=FakeAdapter(delay=1))
            time.sleep(.2);j.cancel(self.engine,owned['id']);result=pending.result(3)
        self.assertEqual(result['event'],'uncertain_decision')
        run=self.s.inspect(self.engine,owned['run_id']);self.assertEqual(run['state'],'review')
        with self.engine.begin() as c:self.assertEqual(a.latest(c,owned['run_id'])['state'],'uncertain')

    def test_lease_expired_tool_result_is_unapplied_and_retry_counted(self):
        from decisionops.commerce import adaptive_jobs as j
        from decisionops.commerce import schema as db
        owned=self.claim(self.queued(),1);f=j.Fence(owned['id'],owned['token'])
        original=self.s.read_tool
        def slow(*args,**kwargs):
            result=original(*args,**kwargs);time.sleep(1.2);return result
        run=self.s.inspect(self.engine,owned['run_id'])
        with patch.object(self.s,'read_tool',side_effect=slow):
            self.s.advance(self.engine,run['id'],{'kind':'read','tool':'order_manifest'},expected_context=run['context_version'],fence=f)
        run=self.s.inspect(self.engine,run['id']);self.assertIsNotNone(run['pending_token'])
        with self.engine.begin() as c:
            self.assertFalse(c.execute(db.adaptive_observations.select()).mappings().one()['applied'])
        newer=self.claim(owned);nf=j.Fence(newer['id'],newer['token'])
        j.recover(self.engine,nf)
        run=self.s.inspect(self.engine,run['id'])
        result=self.s.advance(self.engine,run['id'],{'kind':'read','tool':'order_manifest'},expected_context=run['context_version'],fence=nf)
        self.assertEqual(result['tool_attempts'],2)
        self.assertTrue(result['assessment']['facts']['quantities_valid'])

    def test_expired_lease_rolls_back_publication_then_known_result_replays_once(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a,schema as db
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce.jobs import LeaseLost
        owned=self.claim(self.queued(),30);f=j.Fence(owned['id'],owned['token'])
        for _ in range(7):tick(self.engine,f)
        j.renew(self.engine,f.job_id,f.token,1)
        original=self.s.publish
        def expire(*args,**kwargs):
            result=original(*args,**kwargs);time.sleep(1.1);return result
        with patch.object(self.s,'publish',side_effect=expire):
            with self.assertRaises(LeaseLost):tick(self.engine,f)
        with self.engine.begin() as c:
            self.assertEqual(len(c.execute(db.proposals.select()).all()),0)
            self.assertEqual(a.latest(c,owned['run_id'])['application_status'],'pending')
        newer=self.claim(owned);nf=j.Fence(newer['id'],newer['token'])
        result=tick(self.engine,nf);self.assertEqual(result['state'],'proposed')
        tick(self.engine,nf)
        with self.engine.begin() as c:self.assertEqual(len(c.execute(db.proposals.select()).all()),1)

    def test_staff_approval_execution_is_preserved_during_cancelled_recommendation(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import adaptive_jobs as j
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce.adaptive_recommendations import FakeAdapter
        from decisionops.commerce.cases import investigate_case,review_case,show_case
        from decisionops.commerce.execution import execute
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        run=self.s.inspect(self.engine,owned['run_id'])
        with ThreadPoolExecutor(1) as p:
            active=p.submit(tick,self.engine,f,adapter=FakeAdapter(delay=1))
            time.sleep(.15)
            with self.engine.begin() as c:
                case=investigate_case(c,run['case_id'])
                approved=review_case(c,case['id'],case['generation'],case['proposal_id'],case['proposal']['content_hash'],'approve')
                self.assertEqual(execute(c,case['id'],approved['approval']['operation_id'])['status'],'verified')
            result=active.result(3)
        self.assertEqual(result['event'],'uncertain_decision')
        j.cancel(self.engine,f.job_id)
        with self.engine.begin() as c:self.assertEqual(show_case(c,run['case_id'])['status'],'executed')
        self.assertEqual(self.s.inspect(self.engine,run['id'])['state'],'stale')

    def test_unknown_resources_and_request_headers_cannot_reset(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a,schema as db
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        from sqlalchemy.exc import SQLAlchemyError
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        for _ in range(12):
            with self.assertRaises(Interrupted):tick(self.engine,f,fault='after_dispatch')
            j.recover(self.engine,f)
        result=tick(self.engine,f);self.assertEqual(result['event'],'review_budget')
        run=self.s.inspect(self.engine,owned['run_id']);self.assertEqual(run['state'],'review')
        self.assertLessEqual(run['decision_attempts'],16)
        with self.engine.begin() as c:
            calls=c.execute(db.adaptive_calls.select()).mappings().all()
            self.assertEqual(sum(r['reserved_ms'] for r in calls),240000)
            self.assertTrue(all(r['state']=='uncertain' and r['actual_ms'] is None for r in calls))
            call=a.latest(c,run['id'])
            with c.begin_nested() as guard:
                with self.assertRaises(SQLAlchemyError):c.exec_driver_sql("UPDATE commerce_adaptive_calls SET request='{}' WHERE id=%s",(call['id'],))
                guard.rollback()

    def test_restart_after_publication_does_not_repeat_settled_effect(self):
        from decisionops.commerce import adaptive_jobs as j,schema as db
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token'])
        for _ in range(7):tick(self.engine,f)
        with self.assertRaises(Interrupted):tick(self.engine,f,fault='after_application')
        result=tick(self.engine,f);self.assertEqual(result['state'],'proposed')
        with self.engine.begin() as c:self.assertEqual(len(c.execute(db.proposals.select()).all()),1)

    def short_call(self,owned):
        from datetime import timedelta
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a
        with patch.object(a,'timedelta',return_value=timedelta(milliseconds=100)):
            return a.prepare(self.engine,owned['run_id'],j.Fence(owned['id'],owned['token']))

    def test_shared_shutdown_event_is_not_set_by_normal_decisions(self):
        from threading import Event
        from decisionops.commerce import adaptive_jobs as j
        from decisionops.commerce.adaptive_runner import tick
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token']);stopped=Event()
        tick(self.engine,f,cancel=stopped);self.assertFalse(stopped.is_set())
        tick(self.engine,f,cancel=stopped)
        self.assertEqual(self.s.inspect(self.engine,owned['run_id'])['tool_attempts'],2)

    def test_stale_owner_cannot_mark_new_owners_dispatch_uncertain(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce.jobs import LeaseLost
        old=self.claim(self.queued(),1);time.sleep(1.1);new=self.claim(old)
        nf=j.Fence(new['id'],new['token']);call=a.prepare(self.engine,new['run_id'],nf);a.claim(self.engine,call['id'],nf)
        with self.assertRaises(LeaseLost):tick(self.engine,j.Fence(old['id'],old['token']))
        with self.engine.begin() as c:self.assertEqual(a.get(c,call['id'])['state'],'dispatching')

    def test_expired_undispatched_reservation_is_known_no_dispatch(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a
        owned=self.claim(self.queued());call=self.short_call(owned);time.sleep(.15)
        self.assertIsNone(a.claim(self.engine,call['id'],j.Fence(owned['id'],owned['token'])))
        with self.engine.begin() as c:
            saved=a.get(c,call['id']);self.assertEqual(saved['state'],'settled')
            self.assertEqual(saved['dispatch_count'],0);self.assertEqual(saved['actual_ms'],0)

    def test_expired_recommendation_is_rejected_under_application_lock(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_accounting as a
        from decisionops.commerce.adaptive_recommendations import Result
        owned=self.claim(self.queued());call=self.short_call(owned);f=j.Fence(owned['id'],owned['token'])
        a.claim(self.engine,call['id'],f)
        with self.engine.begin() as c:a.settle(c,call['id'],Result(call['id'],{'kind':'read','tool':'order_manifest'},0))
        time.sleep(.15);current=self.s.inspect(self.engine,owned['run_id'])
        with self.assertRaises(ValueError):self.s.advance(self.engine,owned['run_id'],None,
             expected_context=current['context_version'],fence=f,recommendation_id=call['id'])
        self.assertEqual(self.s.inspect(self.engine,owned['run_id'])['tool_attempts'],0)

    def test_terminal_graph_resume_repairs_job_after_lease_expiry(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_workflow as w
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token']);w.setup_checkpoints(self.engine)
        for _ in range(7):tick(self.engine,f)
        j.renew(self.engine,f.job_id,f.token,1)
        with self.assertRaises(Interrupted):tick(self.engine,f,fault='after_application')
        time.sleep(1.1);w.resume(self.engine,f.job_id)
        with self.engine.begin() as c:self.assertEqual(j.get(c,f.job_id)['status'],'completed')

    def test_remaining_lease_bounds_case_and_tool_lock_waits(self):
        from decisionops.commerce import adaptive_jobs as j
        from sqlalchemy.exc import SQLAlchemyError
        for kind in ('case','tool'):
            owned=self.claim(self.queued(),1);f=j.Fence(owned['id'],owned['token'])
            run=self.s.inspect(self.engine,owned['run_id']);locker=self.engine.connect();tx=locker.begin()
            if kind=='case':locker.exec_driver_sql('SELECT id FROM commerce_cases WHERE id=%s FOR UPDATE',(run['case_id'],))
            else:locker.exec_driver_sql('LOCK TABLE orders IN ACCESS EXCLUSIVE MODE')
            time.sleep(.75);started=time.monotonic()
            try:
                if kind=='case':
                    with self.assertRaises(SQLAlchemyError):self.s.advance(self.engine,run['id'],{'kind':'read','tool':'order_manifest'},expected_context=run['context_version'],fence=f)
                else:self.s.advance(self.engine,run['id'],{'kind':'read','tool':'order_manifest'},expected_context=run['context_version'],fence=f)
            finally:tx.rollback();locker.close()
            self.assertLess(time.monotonic()-started,.8,kind)

    def test_renewal_races_keep_token_and_reject_expired_renewal(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import adaptive_jobs as j
        from decisionops.commerce.jobs import LeaseLost
        owned=self.claim(self.queued(),30)
        with ThreadPoolExecutor(2) as p:
            renewals=list(p.map(lambda _:j.renew(self.engine,owned['id'],owned['token'],30),range(2)))
        self.assertTrue(all(r['token']==owned['token'] and r['claims']==1 for r in renewals))
        j.renew(self.engine,owned['id'],owned['token'],1);time.sleep(1.1)
        with self.assertRaises(LeaseLost):j.renew(self.engine,owned['id'],owned['token'],30)

    def test_graph_resume_pauses_unknown_dispatch_without_redispatch(self):
        from decisionops.commerce import adaptive_jobs as j,adaptive_workflow as w,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        owned=self.claim(self.queued(),1);f=j.Fence(owned['id'],owned['token']);w.setup_checkpoints(self.engine)
        with self.assertRaises(Interrupted):tick(self.engine,f,fault='after_dispatch')
        time.sleep(1.1);state=w.resume(self.engine,owned['id'])
        self.assertEqual(state['phase'],'active')
        with self.engine.begin() as c:
            call=a.latest(c,owned['run_id']);self.assertEqual(call['state'],'dispatching');self.assertEqual(call['dispatch_count'],1)
        self.assertEqual(self.s.inspect(self.engine,owned['run_id'])['decision_attempts'],1)

    def test_worker_shutdown_cannot_use_operator_cancellation_authority(self):
        from threading import Event
        from decisionops.commerce import adaptive_jobs as j
        from decisionops.commerce.adaptive_runner import tick
        owned=self.claim(self.queued());f=j.Fence(owned['id'],owned['token']);stopped=Event();stopped.set()
        with patch.object(j,'cancel',side_effect=AssertionError('Worker must not gain unfenced operator authority')):
            result=tick(self.engine,f,cancel=stopped)
        self.assertEqual(result['event'],'worker_stopped')
        run=self.s.inspect(self.engine,owned['run_id'])
        self.assertEqual(run['state'],'active');self.assertEqual(run['decision_attempts'],0)
        with self.engine.begin() as c:self.assertEqual(j.get(c,owned['id'])['token'],owned['token'])

if __name__=='__main__':unittest.main()
