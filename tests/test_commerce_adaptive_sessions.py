"""Stage 4 isolated PostgreSQL/fake-child integration; no cached model loads."""
import importlib.util
import os
import time
import unittest
from unittest.mock import patch
import test_commerce_adaptive_core as core

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'PostgreSQL integration is opt-in')
class AdaptiveSessionTests(unittest.TestCase):
    setUp=core.AdaptiveCoreTests.setUp
    cleanup=core.AdaptiveCoreTests.cleanup
    case=core.AdaptiveCoreTests.case
    def queued(self,behavior='normal',preload_ms=120000):
        self.assertIsNotNone(importlib.util.find_spec('decisionops.commerce.adaptive_sessions'),'Durable session service missing')
        from decisionops.commerce import adaptive_jobs as j
        from decisionops.commerce.session_protocol import Config
        return j.enqueue(self.engine,self.case()['id'],'Lost parcel',session=Config('fake','fake-v1',behavior=behavior,preload_ms=preload_ms).record())
    def own(self,job,seconds=30):
        from decisionops.commerce import adaptive_jobs as j
        saved=j.claim(self.engine,job_id=job['id'],lease_seconds=seconds)
        return j.Fence(saved['id'],saved['token'])
    def test_success_has_one_persisted_preload_and_many_decisions(self):
        from decisionops.commerce import adaptive_sessions as m,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import run_until_pause
        job=self.queued();f=self.own(job);r=run_until_pause(self.engine,f)
        self.assertEqual(r['state'],'proposed');self.assertEqual(r['decision_attempts'],8);self.assertEqual(r['tool_attempts'],7)
        with self.engine.begin() as c:
            rows=m.records(c,job['run_id']);self.assertEqual(len(rows),1);row=rows[0]
            self.assertEqual(row['state'],'closed');self.assertIsNotNone(row['actual_charge_ms']);self.assertTrue(row['diagnostics']['process_reaped'])
            self.assertEqual(row['api_charge_usd'],0);self.assertEqual(a.latest(c,job['run_id'])['result']['metadata']['session_id'],row['id'])
    def test_unknown_preload_requires_recovery_and_reservation_survives_restart(self):
        from decisionops.commerce import adaptive_sessions as m,adaptive_jobs as j
        job=self.queued();f=self.own(job)
        first=m.reserve(self.engine,f)
        with self.assertRaises(ValueError):m.reserve(self.engine,f)
        j.recover(self.engine,f)
        with self.engine.begin() as c:
            row=m.records(c,job['run_id'])[0];self.assertEqual(row['state'],'uncertain');self.assertTrue(row['retired']);self.assertIsNone(row['actual_charge_ms'])
            self.assertEqual(row['reserved_ms'],150000)
        second=m.reserve(self.engine,f);self.assertEqual(second['ordinal'],2);self.assertLessEqual(second['reserved_ms'],90000)
    def test_mismatched_decision_is_uncertain_and_never_redispatched(self):
        from decisionops.commerce import adaptive_sessions as m,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import run_until_pause
        job=self.queued('wrong-request');f=self.own(job);first=run_until_pause(self.engine,f)
        self.assertEqual(first['event'],'uncertain_decision')
        second=run_until_pause(self.engine,f);self.assertEqual(second['event'],'uncertain_decision')
        with self.engine.begin() as c:
            self.assertEqual(len(m.records(c,job['run_id'])),1);call=a.latest(c,job['run_id'])
            self.assertEqual(call['dispatch_count'],1);self.assertIsNone(call['actual_ms'])
    def test_restart_applies_known_result_without_load_or_redispatch(self):
        from decisionops.commerce import adaptive_sessions as m
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        job=self.queued();f=self.own(job)
        with m.scope(self.engine,f) as adapter:
            with self.assertRaises(Interrupted):tick(self.engine,f,adapter=adapter,fault='after_result')
        with m.scope(self.engine,f) as adapter:
            with patch.object(adapter,'ensure_ready',side_effect=AssertionError('Known result caused reload')):tick(self.engine,f,adapter=adapter)
        run=self.s.inspect(self.engine,job['run_id']);self.assertEqual(run['tool_attempts'],1);self.assertEqual(run['decision_attempts'],1)
        with self.engine.begin() as c:self.assertEqual(len(m.records(c,job['run_id'])),1)
    def test_actual_plain_resume_sigterm_during_preload_preserves_uncertainty(self):
        import signal,subprocess,sys,json
        from decisionops.commerce import adaptive_workflow as w,adaptive_sessions as m,adaptive_jobs as j
        job=self.queued('preload-timeout');w.setup_checkpoints(self.engine)
        env={**os.environ,'COMMERCE_DATABASE_URL':self.engine.url.render_as_string(hide_password=False)}
        child=subprocess.Popen([sys.executable,'-B','-m','decisionops.commerce.adaptive_worker','resume','--job',job['id']],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            end=time.monotonic()+6;rows=[]
            while time.monotonic()<end and child.poll() is None:
                with self.engine.begin() as c:rows=m.records(c,job['run_id'])
                if rows and rows[0]['state']=='loading' and rows[0]['diagnostics'].get('process_pid'):break
                time.sleep(.02)
            self.assertTrue(rows);child.send_signal(signal.SIGTERM);out,err=child.communicate(timeout=4)
            self.assertEqual(child.returncode,0,err);self.assertEqual(json.loads(out)['event'],'worker_stopped')
            with self.engine.begin() as c:
                row=m.records(c,job['run_id'])[0];self.assertEqual(row['state'],'uncertain');self.assertTrue(row['diagnostics']['process_reaped'])
                self.assertIsNotNone(j.get(c,job['id'])['token'])
            self.assertEqual(self.s.inspect(self.engine,job['run_id'])['decision_attempts'],0)
        finally:
            if child.poll() is None:child.kill();child.communicate()
    def test_lease_loss_kills_child_without_mutating_new_token(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import adaptive_sessions as m,adaptive_jobs as j
        from decisionops.commerce.adaptive_runner import run_until_pause
        job=self.queued('preload-timeout');f=self.own(job)
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(run_until_pause,self.engine,f)
            end=time.monotonic()+4
            while time.monotonic()<end:
                with self.engine.begin() as c:rows=m.records(c,job['run_id'])
                if rows and rows[0]['state']=='loading' and rows[0]['diagnostics'].get('process_pid'):break
                time.sleep(.02)
            with self.engine.begin() as c:c.exec_driver_sql('UPDATE commerce_adaptive_jobs SET token=%s WHERE id=%s',('NEW-OWNER',job['id']))
            try:pending.result(4)
            except ValueError:pass
        with self.engine.begin() as c:
            self.assertEqual(j.get(c,job['id'])['token'],'NEW-OWNER');self.assertTrue(m.records(c,job['run_id'])[0]['diagnostics']['process_reaped'])
        self.assertEqual(self.s.inspect(self.engine,job['run_id'])['decision_attempts'],0)

    def test_phase_and_decision_resources_share_atomic_cap(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import adaptive_sessions as m,adaptive_accounting as a,adaptive_jobs as j
        job=self.queued();f=self.own(job)
        def attempt(_):
            try:return m.reserve(self.engine,f)
            except m.RecoveryRequired:return None
        with ThreadPoolExecutor(2) as pool:result=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(r is not None for r in result),1)
        call=a.prepare(self.engine,job['run_id'],f);self.assertEqual(call['reserved_ms'],20000)
        j.recover(self.engine,f)
        second=m.reserve(self.engine,f);self.assertEqual(second['reserved_ms'],70000)
        j.recover(self.engine,f)
        with self.assertRaises(ValueError):m.reserve(self.engine,f)
        with self.engine.begin() as c:self.assertEqual(m.phase_charge(c,job['run_id']),220000)
        self.assertEqual(self.s.inspect(self.engine,job['run_id'])['decision_attempts'],1)

    def test_known_preload_error_falls_back_without_uncertain_phase(self):
        from decisionops.commerce import adaptive_sessions as m,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import run_until_pause
        job=self.queued('preload-error');f=self.own(job);result=run_until_pause(self.engine,f)
        self.assertEqual(result['state'],'proposed');self.assertEqual(result['decision_attempts'],9)
        with self.engine.begin() as c:
            row=m.records(c,job['run_id'])[0];self.assertEqual(row['state'],'failed');self.assertIsNotNone(row['actual_charge_ms'])
            self.assertTrue(row['diagnostics']['process_reaped']);self.assertEqual(row['api_charge_usd'],0)
            self.assertEqual(a.latest(c,job['run_id'])['request']['configuration']['source'],'rules')

    def test_forced_action_does_not_admit_load_or_reserve_model_phase(self):
        from datetime import datetime,timezone
        from decisionops.commerce import adaptive_sessions as m,adaptive_recommendations as r
        from decisionops.commerce.adaptive_policies import PolicyRequest,Action
        job=self.queued();f=self.own(job)
        policy=PolicyRequest('run',0,'',{},(Action('request_review',reason='manual_review'),),(),{},())
        req=r.Request('CALL','run',1,1,policy,'fixed',1000,session={'config':{'family':'fake','revision':'fake-v1'},'session_id':None},deadline=datetime.now(timezone.utc))
        with m.scope(self.engine,f) as adapter:
            with patch.object(type(adapter.config),'admit',side_effect=AssertionError('forced choice consulted pins')):
                result=adapter.choose(req,None)
        self.assertTrue(result.metadata['forced']);self.assertEqual(result.elapsed_ms,0)
        with self.engine.begin() as c:self.assertEqual(m.records(c,job['run_id']),[])

    def test_actual_once_and_token_resume_sigterm_during_decision(self):
        import signal,subprocess,sys,json
        from decisionops.commerce import adaptive_workflow as w,adaptive_sessions as m,adaptive_jobs as j,adaptive_accounting as a
        for command in ('once','token'):
            with self.subTest(command=command):
                job=self.queued('decision-timeout');w.setup_checkpoints(self.engine)
                args=['once'] if command=='once' else ['resume','--job',job['id'],'--token',self.own(job).token]
                env={**os.environ,'COMMERCE_DATABASE_URL':self.engine.url.render_as_string(hide_password=False)}
                child=subprocess.Popen([sys.executable,'-B','-m','decisionops.commerce.adaptive_worker',*args],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    # Start-up/import + slot/preload precede decision dispatch.
                    # Synchronize on persisted phases, within their existing caps,
                    # instead of signalling after an unrelated six-second timer.
                    from datetime import datetime,timezone
                    from decisionops.commerce.session_protocol import Config
                    with self.engine.begin() as c:run=self.s.row(c,job['run_id'])
                    cfg=Config(**run['contracts']['session']);started=time.monotonic()
                    end=started+min((run['deadline']-datetime.now(timezone.utc)).total_seconds(),
                                    (cfg.slot_ms+cfg.preload_ms)/1000+20)
                    call=None;sessions=[]
                    while child.poll() is None and time.monotonic()<end:
                        with self.engine.begin() as c:
                            call=a.latest(c,job['run_id']);sessions=m.records(c,job['run_id'])
                        if call and call['state']=='dispatching':break
                        if call and call['state'] in ('settled','uncertain'):break
                        if sessions and sessions[-1]['state'] in ('failed','uncertain','closed'):break
                        time.sleep(.02)
                    if call is None or call['state']!='dispatching':
                        child.send_signal(signal.SIGTERM) if child.poll() is None else None
                        out,err=child.communicate(timeout=4)
                        with self.engine.begin() as c:
                            durable={'job':j.get(c,job['id']),'run':self.s.row(c,job['run_id']),'sessions':m.records(c,job['run_id']),'call':a.latest(c,job['run_id'])}
                        self.fail(repr({'boundary':'before_dispatch','stdout':out,'stderr':err,'durable':durable}))
                    self.assertEqual(call['dispatch_count'],1)
                    self.assertTrue(sessions);self.assertEqual(sessions[-1]['state'],'ready')
                    print({'boundary':'durable_decision_dispatch','command':command,
                           'setup_seconds':round(time.monotonic()-started,3),'call':call,
                           'run_deadline':run['deadline'],'session_created':sessions[-1]['created_at']},flush=True)
                    child.send_signal(signal.SIGTERM)
                    out,err=child.communicate(timeout=4);self.assertEqual(child.returncode,0,err);self.assertEqual(json.loads(out)['event'],'worker_stopped')
                    with self.engine.begin() as c:
                        call=a.latest(c,job['run_id']);self.assertEqual(call['state'],'uncertain');self.assertEqual(call['dispatch_count'],1);self.assertIsNone(call['actual_ms'])
                        self.assertTrue(m.records(c,job['run_id'])[0]['diagnostics']['process_reaped'])
                    self.assertEqual(self.s.inspect(self.engine,job['run_id'])['tool_attempts'],0)
                finally:
                    if child.poll() is None:child.kill();child.communicate()

    def test_restart_after_committed_step_records_a_counted_reload(self):
        from decisionops.commerce import adaptive_sessions as m,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import tick
        job=self.queued();f=self.own(job)
        for _ in range(2):
            with m.scope(self.engine,f) as adapter:tick(self.engine,f,adapter=adapter)
        with self.engine.begin() as c:
            rows=m.records(c,job['run_id']);self.assertEqual([r['ordinal'] for r in rows],[1,2])
            self.assertTrue(all(r['state']=='closed' and r['actual_charge_ms'] is not None for r in rows))
            self.assertEqual(a.latest(c,job['run_id'])['result']['metadata']['session_id'],rows[-1]['id'])
        self.assertEqual(self.s.inspect(self.engine,job['run_id'])['decision_attempts'],2)

    def test_historical_session_inspection_does_not_consult_current_pins(self):
        from decisionops.commerce import adaptive_sessions as m,adaptive_accounting as a
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce.session_protocol import Config
        job=self.queued();f=self.own(job)
        with m.scope(self.engine,f) as adapter:tick(self.engine,f,adapter=adapter)
        with patch.object(Config,'admit',side_effect=AssertionError('Historical inspection consulted current pins')):
            with self.engine.begin() as c:
                row=m.records(c,job['run_id'])[0];req=a.request_from(a.latest(c,job['run_id']))
                self.assertEqual(req.session['session_id'],row['id'])

    def test_plain_resume_preload_outlasts_original_lease_after_valid_renewal(self):
        from decisionops.commerce import adaptive_workflow as w,adaptive_jobs as j,adaptive_sessions as m
        job=self.queued('slow-preload');w.setup_checkpoints(self.engine);original=j.claim
        def short_initial_claim(engine,**kwargs):return original(engine,lease_seconds=1,**kwargs)
        with patch.object(j,'claim',side_effect=short_initial_claim):result=w.resume(self.engine,job['id'])
        self.assertEqual(result['phase'],'proposed')
        with self.engine.begin() as c:
            rows=m.records(c,job['run_id']);self.assertEqual(len(rows),1);self.assertGreater(rows[0]['load_ms'],1000)
        self.assertEqual(self.s.inspect(self.engine,job['run_id'])['decision_attempts'],8)

    def test_plain_resume_stops_and_exposes_unknown_preload(self):
        from decisionops.commerce import adaptive_workflow as w,adaptive_sessions as m
        job=self.queued('preload-timeout',preload_ms=80);w.setup_checkpoints(self.engine)
        result=w.resume(self.engine,job['id'])
        self.assertEqual(result.get('event'),'uncertain_session')
        self.assertEqual(result['phase'],'active')
        self.assertEqual(len(result['session_phases']),1);self.assertEqual(result['session_phases'][0]['state'],'uncertain')
        self.assertEqual(self.s.inspect(self.engine,job['run_id'])['decision_attempts'],0)
        with self.engine.begin() as c:self.assertEqual(len(m.records(c,job['run_id'])),1)

if __name__=='__main__':unittest.main()
