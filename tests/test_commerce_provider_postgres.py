"""Actual budget races, restart recovery and consumed fake recommendations."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import test_commerce_execution as fixtures
from test_commerce_providers import request


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'PostgreSQL integration is opt-in')
class ProviderDatabaseTests(unittest.TestCase):
    def setUp(self):
        fixtures.ExecutionRaceTests.setUp(self)
        with self.engine.begin() as c:c.exec_driver_sql('UPDATE shipments SET carrier_observed_at=clock_timestamp()')

    def cleanup_schema(self):fixtures.ExecutionRaceTests.cleanup_schema(self)

    def opened(self,order='ORD-1042'):
        from decisionops.commerce.cases import open_case
        from decisionops.commerce.read_tools import AssessmentRequest
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            return open_case(c,AssessmentRequest(order,'SHIP-'+order.removeprefix('ORD-'),{'shirt-blue-M':1}))

    def budget(self,limits=None):
        from decisionops.commerce.providers import Limits,Pricing
        from decisionops.commerce.provider_budget import create_budget
        limits=limits or Limits()
        with self.engine.begin() as c:create_budget(c,'BUDGET-1',limits,Pricing())
        return limits

    def route(self,case,run='RUN-1',scenario='success',**kwargs):
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.provider_service import recommend
        return recommend(self.engine,case['id'],run,'BUDGET-1',ProviderConfig(scenario=scenario),**kwargs)

    def test_success_and_review_recommendations_change_the_real_case_path(self):
        self.budget();case=self.opened();result=self.route(case)
        self.assertEqual(result['case']['status'],'awaiting_review')
        self.assertEqual(result['trace']['effective_choice'],'present_replacement')
        self.assertIsNone(result['case']['approval'])
        other=self.opened();review=self.route(other,'RUN-2','review')
        self.assertEqual(review['case']['status'],'escalated')
        self.assertEqual(review['trace']['effective_choice'],'staff_review')
        with self.engine.connect() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one(),0)
            self.assertEqual(c.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(),1)

    def test_rules_default_never_dispatches_or_reserves_budget(self):
        from decisionops.commerce.provider_service import recommend
        case=self.opened();result=recommend(self.engine,case['id'],'RULES-1')
        self.assertEqual(result['case']['status'],'awaiting_review')
        self.assertEqual(result['mode'],'rules')
        with self.engine.connect() as c:self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_provider_calls').scalar_one(),0)

    def test_known_usage_settles_exact_decimal_and_keeps_pricing_version(self):
        self.budget();result=self.route(self.opened());trace=result['trace']
        self.assertEqual(trace['state'],'settled')
        self.assertEqual(Decimal(trace['actual_cost_usd']),Decimal('0.00012000'))
        self.assertEqual(trace['request']['pricing']['version'],'simulated-v1')
        self.assertTrue(trace['result']['simulated'])

    def test_faults_fallback_without_inventing_facts(self):
        from decisionops.commerce.providers import Limits
        self.budget(Limits(max_requests=10,max_cost_usd='1'))
        for index,scenario in enumerate(('unavailable','refused','invalid_choice','instruction_override','malformed')):
            with self.subTest(scenario=scenario):
                result=self.route(self.opened(),'RUN-'+str(index),scenario)
                self.assertEqual(result['case']['status'],'escalated')
                self.assertEqual(result['trace']['effective_choice'],'staff_review')
                self.assertNotEqual(result['trace']['result']['status'],'success')
                self.assertIsNone(result['case']['approval'])

    def test_incomplete_history_cannot_offer_or_compensate(self):
        self.budget();result=self.route(self.opened('ORD-HISTORY'))
        self.assertEqual(result['trace']['effective_choice'],'staff_review')
        self.assertEqual(result['case']['status'],'needs_review')
        self.assertIsNone(result['case']['proposal'])
        self.assertIsNone(result['trace']['request']['facts']['no_previous_compensation'])

    def test_timeout_retains_cost_and_repeat_does_not_redispatch(self):
        self.budget();case=self.opened()
        first=self.route(case,scenario='timeout')
        second=self.route(case,scenario='timeout')
        self.assertEqual(first['trace']['state'],'uncertain')
        self.assertEqual(first['trace']['reserved_cost_usd'],second['trace']['reserved_cost_usd'])
        self.assertEqual(second['trace']['dispatch_count'],1)
        self.assertEqual(first['case']['generation'],second['case']['generation'])

    def test_real_deadline_returns_before_delayed_fake_finishes(self):
        import time
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.provider_service import recommend
        self.budget();case=self.opened();start=time.monotonic()
        result=recommend(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig(delay_ms=400),deadline_seconds=0.05)
        self.assertEqual(result['trace']['state'],'uncertain')
        self.assertLess(time.monotonic()-start,0.35)
        time.sleep(0.45)
        from decisionops.commerce.provider_service import recover
        self.assertEqual(recover(self.engine,'RUN-1')['trace']['dispatch_count'],1)

    def test_budget_request_race_reserves_once(self):
        from decisionops.commerce.providers import Limits
        from decisionops.commerce.provider_budget import reserve
        limits=self.budget(Limits(max_requests=1,max_cost_usd='1'))
        cases=[self.opened(),self.opened()];gate=Barrier(2)
        def reserve_one(index):
            req=request(case_id=cases[index]['id'],run_id='RACE-'+str(index),limits=limits,
                        deadline=datetime.now(timezone.utc)+timedelta(seconds=5))
            with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
                gate.wait(5);return reserve(c,'BUDGET-1',req)['state']
        with ThreadPoolExecutor(max_workers=2) as pool:states=list(pool.map(reserve_one,range(2)))
        self.assertCountEqual(states,['reserved','denied'])

    def test_budget_cost_race_and_uncertain_commitment_block_new_request(self):
        from decisionops.commerce.providers import Limits
        from decisionops.commerce.provider_budget import reserve,summary
        limits=self.budget(Limits(max_requests=10,max_cost_usd='0.00260000'))
        cases=[self.opened(),self.opened()];gate=Barrier(2)
        def reserve_one(index):
            req=request(case_id=cases[index]['id'],run_id='COST-'+str(index),limits=limits,
                        deadline=datetime.now(timezone.utc)+timedelta(seconds=5))
            with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
                gate.wait(5);return reserve(c,'BUDGET-1',req)['state']
        with ThreadPoolExecutor(max_workers=2) as pool:states=list(pool.map(reserve_one,range(2)))
        self.assertCountEqual(states,['reserved','denied'])
        with self.engine.connect() as c:self.assertEqual(summary(c,'BUDGET-1')['committed_cost_usd'],'0.00260000')

    def test_stale_evidence_is_not_applied_and_wait_holds_no_business_locks(self):
        from decisionops.commerce.providers import FakeProvider
        self.budget();case=self.opened();engine=self.engine
        class ChangingFake(FakeProvider):
            def choose(self,req):
                with engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
                    c.exec_driver_sql("SET LOCAL lock_timeout='100ms'")
                    c.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
                return super().choose(req)
        result=self.route(case,provider=ChangingFake())
        self.assertEqual(result['trace']['application_status'],'stale')
        self.assertEqual(result['case']['status'],'needs_review')
        self.assertIsNone(result['case']['approval'])

    def test_later_case_generation_or_approval_is_not_overwritten(self):
        from decisionops.commerce.providers import FakeProvider
        from decisionops.commerce.cases import investigate_case,review_case
        self.budget();case=self.opened();engine=self.engine
        class ApprovingFake(FakeProvider):
            def choose(self,req):
                with engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
                    current=investigate_case(c,req.case_id)
                    review_case(c,req.case_id,current['generation'],current['proposal_id'],current['proposal']['content_hash'],'approve')
                return super().choose(req)
        result=self.route(case,provider=ApprovingFake())
        self.assertEqual(result['case']['status'],'approved')
        self.assertEqual(result['trace']['application_status'],'stale')

    def test_restart_reserved_dispatches_once_and_settled_apply_recovers(self):
        from decisionops.commerce.providers import ProviderConfig,FakeProvider
        from decisionops.commerce.provider_service import prepare,dispatch,apply
        self.budget();case=self.opened()
        prepare(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig())
        dispatch(self.engine,'RUN-1',FakeProvider())
        result=apply(self.engine,'RUN-1')
        repeated=self.route(case)
        self.assertEqual(result['trace']['effective_choice'],'present_replacement')
        self.assertEqual(repeated['trace']['dispatch_count'],1)
        self.assertEqual(repeated['case']['generation'],1)
        self.assertEqual(len([e for e in repeated['case']['events'] if e['kind']=='provider_routed']),1)

    def test_restart_inflight_call_is_not_automatically_redispatched(self):
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.provider_service import prepare
        from decisionops.commerce.provider_budget import claim
        self.budget();case=self.opened()
        prepare(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig(),deadline_seconds=0.2)
        with self.engine.begin() as c:claim(c,'RUN-1')
        result=self.route(case)
        self.assertEqual(result['trace']['dispatch_count'],1)
        self.assertEqual(result['trace']['state'],'dispatching')
        import time
        time.sleep(0.25)
        result=self.route(case)
        self.assertEqual(result['trace']['state'],'uncertain')
        self.assertEqual(result['case']['status'],'escalated')

    def test_duplicate_concurrent_dispatch_claim_is_fenced(self):
        from decisionops.commerce.providers import ProviderConfig,FakeProvider
        from decisionops.commerce.provider_service import prepare,dispatch,apply
        self.budget();case=self.opened();prepare(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig())
        entered=Event();release=Event();calls=[]
        class BlockingFake(FakeProvider):
            def choose(self,req):calls.append(req.run_id);entered.set();release.wait(2);return super().choose(req)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(dispatch,self.engine,'RUN-1',BlockingFake());self.assertTrue(entered.wait(2))
            second=dispatch(self.engine,'RUN-1',BlockingFake());release.set();first.result(5)
        self.assertEqual(calls,['RUN-1'])
        self.assertEqual(apply(self.engine,'RUN-1')['trace']['dispatch_count'],1)

    def test_exhaustion_is_explicit_review_without_dispatch(self):
        from decisionops.commerce.providers import Limits
        self.budget(Limits(max_requests=1,max_cost_usd='1'))
        self.route(self.opened());result=self.route(self.opened(),'RUN-2')
        self.assertEqual(result['trace']['state'],'denied')
        self.assertEqual(result['trace']['dispatch_count'],0)
        self.assertEqual(result['case']['status'],'escalated')

    def test_run_identity_and_pricing_config_cannot_change_on_retry(self):
        self.budget();case=self.opened();self.route(case)
        with self.assertRaises(ValueError):self.route(self.opened())
        from decisionops.commerce.provider_budget import create_budget
        from decisionops.commerce.providers import Limits,Pricing
        with self.engine.begin() as c:
            with self.assertRaises(ValueError):create_budget(c,'BUDGET-1',Limits(),Pricing(version='other'))

    def test_provider_never_replaces_staff_approval_or_execution_recheck(self):
        from decisionops.commerce.execution import execute
        from decisionops.commerce.cases import review_case
        self.budget();result=self.route(self.opened());case=result['case']
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            with self.assertRaises(ValueError):execute(c,case['id'],'OP-invented')
            approved=review_case(c,case['id'],case['generation'],case['proposal_id'],case['proposal']['content_hash'],'approve')
            c.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
            self.assertEqual(execute(c,case['id'],approved['approval']['operation_id'])['status'],'requires_reinvestigation')

    def test_cli_trace_survives_process_restart_and_labels_simulated_usage(self):
        import json,subprocess,sys
        self.budget();case=self.opened()
        env=dict(os.environ,COMMERCE_DATABASE_URL=self.engine.url.render_as_string(hide_password=False))
        def cli(*args,expected=0):
            completed=subprocess.run([sys.executable,'-B','-m','decisionops.commerce.provider_demo',*args],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(completed.returncode,expected,completed.stderr)
            return json.loads(completed.stdout)
        initial=cli('investigate','--mode','fake','--case',case['id'],'--run','CLI-1','--budget','BUDGET-1','--scenario','timeout',expected=4)
        repeated=cli('recover','--run','CLI-1',expected=4)
        self.assertTrue(initial['simulated'])
        self.assertEqual(repeated['trace']['dispatch_count'],1)
        self.assertEqual(cli('show','--run','CLI-1')['trace']['state'],'uncertain')

    def test_immutable_budget_and_request_bindings_are_guarded(self):
        from sqlalchemy.exc import DBAPIError
        self.budget();self.route(self.opened())
        for statement in ("UPDATE commerce_provider_budgets SET pricing='{}'", "UPDATE commerce_provider_calls SET request='{}'", "DELETE FROM commerce_provider_calls"):
            with self.engine.begin() as c:
                with self.assertRaises(DBAPIError):c.exec_driver_sql(statement)

    def test_apply_waits_for_business_before_locking_provider_call(self):
        from sqlalchemy import event
        from decisionops.commerce.providers import ProviderConfig,FakeProvider
        from decisionops.commerce.provider_service import prepare,dispatch,apply
        self.budget();case=self.opened();prepare(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig())
        dispatch(self.engine,'RUN-1',FakeProvider())
        waiting=Event()
        def observe(connection,cursor,statement,parameters,context,executemany):
            if 'FROM orders' in statement and 'FOR UPDATE' in statement:waiting.set()
        blocker=self.engine.connect().execution_options(isolation_level='READ COMMITTED')
        transaction=blocker.begin()
        blocker.exec_driver_sql("SELECT id FROM orders WHERE id='ORD-1042' FOR UPDATE")
        event.listen(self.engine,'before_cursor_execute',observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                running=pool.submit(apply,self.engine,'RUN-1')
                try:
                    self.assertTrue(waiting.wait(2))
                    with self.engine.begin() as probe:
                        probe.exec_driver_sql("SELECT run_id FROM commerce_provider_calls WHERE run_id='RUN-1' FOR UPDATE NOWAIT")
                finally:transaction.rollback()
                self.assertEqual(running.result(5)['trace']['application_status'],'applied')
        finally:
            event.remove(self.engine,'before_cursor_execute',observe)
            if transaction.is_active:transaction.rollback()
            blocker.close()

    def test_long_run_identifier_can_settle_or_fallback(self):
        self.budget()
        self.assertEqual(self.route(self.opened(),run='R'*128)['trace']['state'],'settled')
        self.assertEqual(self.route(self.opened(),run='T'*128,scenario='timeout')['trace']['state'],'uncertain')

    def test_late_known_usage_settles_but_cannot_present_replacement(self):
        from decisionops.commerce.providers import ProviderConfig,FakeProvider,ProviderRequest
        from decisionops.commerce.provider_service import prepare,apply
        from decisionops.commerce.provider_budget import claim,settle
        self.budget();case=self.opened();prepared=prepare(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig())
        req=ProviderRequest.from_record(prepared['request'])
        with self.engine.begin() as c:claim(c,'RUN-1')
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            settled=settle(c,'RUN-1',FakeProvider().choose(req),req.deadline+timedelta(seconds=1))
        self.assertEqual(settled['state'],'settled')
        self.assertEqual(settled['actual_cost_usd'],Decimal('0.00012000'))
        self.assertEqual(apply(self.engine,'RUN-1')['case']['status'],'escalated')

    def test_expired_reserved_call_is_known_zero_usage_without_dispatch(self):
        import time
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.provider_service import prepare,recover
        self.budget();case=self.opened()
        prepare(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig(),deadline_seconds=0.1)
        time.sleep(0.2)
        result=recover(self.engine,'RUN-1')
        self.assertEqual(result['trace']['state'],'settled')
        self.assertEqual(result['trace']['dispatch_count'],0)
        self.assertEqual(Decimal(result['trace']['actual_cost_usd']),Decimal('0'))

    def test_carrier_age_expiry_rejects_result_with_unchanged_versions(self):
        import time
        from decisionops.commerce.providers import ProviderConfig,FakeProvider
        from decisionops.commerce.provider_service import prepare,dispatch,apply
        self.budget();case=self.opened()
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE shipments SET carrier_observed_at=clock_timestamp()-interval '86399 seconds'")
        prepare(self.engine,case['id'],'RUN-1','BUDGET-1',ProviderConfig())
        dispatch(self.engine,'RUN-1',FakeProvider());time.sleep(1.1)
        result=apply(self.engine,'RUN-1')
        self.assertEqual(result['trace']['application_status'],'stale')
        self.assertEqual(result['case']['status'],'needs_review')

    def local_budget(self):
        from decisionops.commerce.provider_budget import create_budget
        from decisionops.commerce.providers import Limits,Pricing
        with self.engine.begin() as c:create_budget(c,'LOCAL-BUDGET',Limits(max_cost_usd='0'),Pricing.local())

    def test_local_forced_review_skips_dispatch_and_has_no_fake_usage(self):
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.provider_service import recommend,recover
        self.local_budget();case=self.opened('ORD-HISTORY')
        result=recommend(self.engine,case['id'],'LOCAL-FORCED','LOCAL-BUDGET',ProviderConfig(mode='laya'))
        trace=result['trace'];self.assertEqual(trace['dispatch_count'],0)
        self.assertTrue(trace['result']['metadata']['forced_choice']);self.assertFalse(trace['result']['simulated'])
        self.assertIsNone(trace['result']['input_tokens']);self.assertEqual(trace['actual_cost_usd'],'0E-8')
        self.assertEqual(trace['state'],'settled');self.assertEqual(result['case']['status'],'needs_review')
        self.assertEqual(recover(self.engine,'LOCAL-FORCED')['trace']['dispatch_count'],0)

    def test_local_subprocess_recommendation_is_consumed_without_approval(self):
        import json,sys,tempfile
        from pathlib import Path
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.local_provider import LocalProvider
        from decisionops.commerce.provider_service import recommend,recover
        self.local_budget();case=self.opened();config=ProviderConfig(mode='gliclass')
        output={'status':'success','choice':'staff_review','metadata':{'model_revision':config.model_revision,
            'forced_choice':False,'scores':{'present_replacement':.1,'staff_review':.9},'score_meaning':'test-double probabilities',
            'load_seconds':.1,'inference_seconds':.1,'peak_rss_kib':1000}}
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'fake_worker.py';worker.write_text('print('+repr(json.dumps(output))+')')
            result=recommend(self.engine,case['id'],'LOCAL-ROUTE','LOCAL-BUDGET',config,
                provider=LocalProvider(python=sys.executable,worker=worker))
        self.assertEqual(result['case']['status'],'escalated');self.assertIsNone(result['case']['approval'])
        self.assertEqual(result['trace']['state'],'settled');self.assertEqual(result['trace']['dispatch_count'],1)
        self.assertFalse(result['trace']['result']['simulated']);self.assertIsNone(result['trace']['result']['input_tokens'])
        self.assertEqual(result['budget']['committed_cost_usd'],'0.00000000')
        self.assertEqual(recover(self.engine,'LOCAL-ROUTE')['trace']['dispatch_count'],1)

    def test_local_timeout_retains_request_and_cannot_redispatch(self):
        import sys,tempfile
        from pathlib import Path
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.local_provider import LocalProvider
        from decisionops.commerce.provider_service import recommend,recover
        self.local_budget();case=self.opened()
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'slow.py';worker.write_text('import time;time.sleep(30)')
            r=recommend(self.engine,case['id'],'LOCAL-TIMEOUT','LOCAL-BUDGET',ProviderConfig(mode='laya'),
                deadline_seconds=.2,provider=LocalProvider(python=sys.executable,worker=worker))
        self.assertEqual(r['trace']['state'],'uncertain');self.assertEqual(r['case']['status'],'escalated')
        self.assertTrue(r['trace']['result']['metadata']['process_reaped'])
        self.assertEqual(recover(self.engine,'LOCAL-TIMEOUT')['trace']['dispatch_count'],1)

    def test_local_wait_releases_business_locks_and_stale_result_is_rejected(self):
        from decisionops.commerce.local_provider import LocalProvider,local_result,diagnostics
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.provider_service import recommend
        started=Event();finish=Event()
        class WaitingLocal(LocalProvider):
            def choose(self,request):
                started.set();finish.wait(3)
                return local_result(request,'present_replacement',metadata=diagnostics(request,
                    scores={'present_replacement':.8,'staff_review':.2},score_meaning='test-double probabilities',
                    load_seconds=0,inference_seconds=0,peak_rss_kib=0))
        self.local_budget();case=self.opened()
        with ThreadPoolExecutor(max_workers=1) as pool:
            job=pool.submit(recommend,self.engine,case['id'],'LOCAL-STALE','LOCAL-BUDGET',ProviderConfig(mode='gliclass'),provider=WaitingLocal())
            try:
                self.assertTrue(started.wait(3))
                with self.engine.begin() as c:
                    c.exec_driver_sql("SELECT * FROM inventory WHERE variant_id='shirt-blue-M' FOR UPDATE NOWAIT")
                    c.exec_driver_sql("UPDATE inventory SET on_hand=11 WHERE variant_id='shirt-blue-M'")
            finally:finish.set()
            r=job.result(timeout=5)
        self.assertEqual(r['trace']['application_status'],'stale');self.assertEqual(r['case']['status'],'needs_review')
        self.assertIsNone(r['case']['approval'])

    def test_historical_local_inspection_and_settled_recovery_ignore_rotated_pins(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from decisionops.commerce import providers
        from decisionops.commerce.local_provider import LocalProvider,local_result,diagnostics
        from decisionops.commerce.provider_service import recommend,inspect,recover
        class RecordedLocal(LocalProvider):
            def choose(self,req):
                return local_result(req,'staff_review',metadata=diagnostics(req,scores={'present_replacement':.1,'staff_review':.9},
                    score_meaning='model-free double',load_seconds=0,inference_seconds=0,peak_rss_kib=0))
        self.local_budget()
        with tempfile.TemporaryDirectory() as root:
            pins=Path(root)/'pins.env';pins.write_text('GLICLASS_REV='+'a'*40+'\nLAYA_REV='+'c'*40+'\n')
            with patch.object(providers,'REVISION_FILE',pins):
                result=recommend(self.engine,self.opened()['id'],'HISTORY-A','LOCAL-BUDGET',providers.ProviderConfig(mode='gliclass'),provider=RecordedLocal())
                saved=result['trace']['request'];pins.write_text('GLICLASS_REV='+'b'*40+'\nLAYA_REV='+'d'*40+'\n')
                with patch.object(providers,'configured_revision',side_effect=AssertionError('no pin consultation')),patch('subprocess.Popen',side_effect=AssertionError('no worker')):
                    seen=inspect(self.engine,'HISTORY-A');recovered=recover(self.engine,'HISTORY-A')
                for r in (seen,recovered):
                    self.assertEqual(r['trace']['request'],saved)
                    self.assertEqual(r['trace']['result']['metadata']['model_revision'],'a'*40)
                    self.assertEqual(r['trace']['dispatch_count'],1)

    def test_reserved_old_checkpoint_is_controlled_no_dispatch_after_rotation(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from decisionops.commerce import providers
        from decisionops.commerce.provider_service import prepare,inspect,recover
        self.local_budget()
        with tempfile.TemporaryDirectory() as root:
            pins=Path(root)/'pins.env';pins.write_text('GLICLASS_REV='+'a'*40+'\nLAYA_REV='+'c'*40+'\n')
            with patch.object(providers,'REVISION_FILE',pins):
                prepare(self.engine,self.opened()['id'],'RESERVED-A','LOCAL-BUDGET',providers.ProviderConfig(mode='gliclass'),deadline_seconds=30)
                saved=inspect(self.engine,'RESERVED-A')['trace']['request']
                pins.write_text('GLICLASS_REV='+'b'*40+'\nLAYA_REV='+'d'*40+'\n')
                with patch('subprocess.Popen',side_effect=AssertionError('old checkpoint must not dispatch')):
                    result=recover(self.engine,'RESERVED-A')
                self.assertEqual(result['trace']['request'],saved)
                self.assertEqual(result['trace']['result']['metadata']['model_revision'],'a'*40)
                self.assertEqual(result['trace']['dispatch_count'],0)
                self.assertEqual(result['trace']['result']['error_kind'],'checkpoint_policy_changed')
                self.assertEqual(result['trace']['state'],'settled')
                self.assertEqual(result['trace']['application_status'],'fallback')
                self.assertEqual(result['case']['status'],'escalated')
                prepare(self.engine,self.opened()['id'],'NEW-B','LOCAL-BUDGET',providers.ProviderConfig(mode='gliclass'),deadline_seconds=30)
                self.assertEqual(inspect(self.engine,'NEW-B')['trace']['request']['config']['model_revision'],'b'*40)

    def test_inflight_recovery_and_forced_history_remain_pin_independent(self):
        import tempfile,time
        from pathlib import Path
        from unittest.mock import patch
        from decisionops.commerce import providers,provider_budget as ledger
        from decisionops.commerce.provider_service import prepare,recover
        self.local_budget()
        with tempfile.TemporaryDirectory() as root:
            pins=Path(root)/'pins.env';pins.write_text('GLICLASS_REV='+'a'*40+'\nLAYA_REV='+'c'*40+'\n')
            with patch.object(providers,'REVISION_FILE',pins):
                config=providers.ProviderConfig(mode='gliclass')
                prepare(self.engine,self.opened('ORD-HISTORY')['id'],'FORCED-A','LOCAL-BUDGET',config,deadline_seconds=30)
                prepare(self.engine,self.opened()['id'],'INFLIGHT-A','LOCAL-BUDGET',config,deadline_seconds=.1)
                with self.engine.begin() as c:self.assertEqual(ledger.claim(c,'INFLIGHT-A')['dispatch_count'],1)
                pins.write_text('GLICLASS_REV='+'b'*40+'\nLAYA_REV='+'d'*40+'\n');time.sleep(.15)
                with patch.object(providers,'configured_revision',side_effect=AssertionError('no pin consultation')),patch('subprocess.Popen',side_effect=AssertionError('no worker')):
                    forced=recover(self.engine,'FORCED-A');uncertain=recover(self.engine,'INFLIGHT-A')
                self.assertTrue(forced['trace']['result']['metadata']['forced_choice'])
                self.assertEqual(forced['trace']['dispatch_count'],0)
                self.assertEqual(uncertain['trace']['state'],'uncertain')
                self.assertEqual(uncertain['trace']['dispatch_count'],1)
                self.assertEqual(uncertain['trace']['result']['metadata']['model_revision'],'a'*40)

    def test_output_overflow_falls_back_with_bounded_persisted_diagnostics(self):
        import sys,tempfile
        from pathlib import Path
        from decisionops.commerce.providers import ProviderConfig
        from decisionops.commerce.local_provider import LocalProvider
        from decisionops.commerce.provider_service import recommend,recover
        self.local_budget()
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'noisy.py';worker.write_text('import os,time\nos.write(2,b"x"*80000);time.sleep(30)\n')
            result=recommend(self.engine,self.opened()['id'],'OVERFLOW','LOCAL-BUDGET',ProviderConfig(mode='gliclass'),
                provider=LocalProvider(python=sys.executable,worker=worker))
        trace=result['trace'];metadata=trace['result']['metadata']
        self.assertEqual(trace['result']['error_kind'],'worker_output_overflow')
        self.assertEqual(trace['state'],'settled');self.assertEqual(trace['application_status'],'fallback')
        self.assertEqual(result['case']['status'],'escalated');self.assertIsNone(result['case']['approval'])
        self.assertEqual(metadata['stream_bytes_consumed']['stderr'],65537)
        self.assertEqual(len(metadata['stream_diagnostics']['stderr']),1024)
        self.assertTrue(metadata['process_reaped'])
        self.assertEqual(recover(self.engine,'OVERFLOW')['trace']['dispatch_count'],1)
