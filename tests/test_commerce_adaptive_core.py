"""Stage 2 PostgreSQL service tests; every test owns a disposable schema."""
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import unittest
import uuid

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'PostgreSQL integration is opt-in')
class AdaptiveCoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('decisionops.commerce.adaptive_investigations'),
                             'Stage 2 services are not implemented')
        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        from decisionops.commerce.seed import seed
        from decisionops.commerce import adaptive_investigations as service
        self.s=service
        self.schema='test_adaptive_core_'+uuid.uuid4().hex
        self.admin=database_engine(os.environ['COMMERCE_TEST_DATABASE_URL'])
        with self.admin.begin() as c: c.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.addCleanup(self.cleanup)
        self.engine=database_engine(make_url(os.environ['COMMERCE_TEST_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+self.schema}))
        config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
        with self.engine.begin() as c:
            config.attributes['connection']=c;command.upgrade(config,'head')
        seed(self.engine,observed_at=datetime.now(timezone.utc))

    def cleanup(self):
        self.engine.dispose()
        with self.admin.begin() as c: c.exec_driver_sql(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.dispose()

    def case(self, suffix='1042', items=None, approve=False):
        from decisionops.commerce.cases import open_case,investigate_case,review_case
        from decisionops.commerce.read_tools import AssessmentRequest
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            case=open_case(c,AssessmentRequest('ORD-'+suffix,'SHIP-'+suffix,items or {'shirt-blue-M':1}))
            if approve:
                case=investigate_case(c,case['id'])
                case=review_case(c,case['id'],case['generation'],case['proposal_id'],case['proposal']['content_hash'],'approve')
            return case

    def begin(self,case=None,**kwargs):
        return self.s.start(self.engine,(case or self.case())['id'],'Customer reports a lost shipment',**kwargs)

    def advance(self,run,action):
        return self.s.advance(self.engine,run['id'],action,expected_context=run['context_version'])

    def read_all(self,run):
        for tool in ('order_manifest','replacement_policy','payment','fulfilment','carrier_loss','compensation_history','inventory'):
            run=self.advance(run,{'kind':'read','tool':tool})
        return run

    def test_success_has_durable_steps_legacy_proposal_and_no_business_writes(self):
        case=self.case(); run=self.begin(case); run=self.s.drive(self.engine,run['id'])
        self.assertEqual(run['state'],'proposed');self.assertEqual(run['tool_attempts'],7)
        self.assertEqual(run['assessment']['decision']['status'],'eligible_to_propose')
        self.assertEqual(run['terminal']['case_status'],'awaiting_review')
        self.assertEqual(len(run['observations']),7)
        from decisionops.commerce.cases import show_case,review_case
        from decisionops.commerce.execution import execute,reconcile
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            saved=show_case(c,case['id'])
            self.assertEqual(saved['proposal']['document']['schema_version'],1)
            self.assertEqual(c.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(),1)
            approved=review_case(c,case['id'],saved['generation'],saved['proposal_id'],saved['proposal']['content_hash'],'approve')
            result=execute(c,case['id'],approved['approval']['operation_id'])
            self.assertEqual(result['status'],'verified')
            self.assertEqual(reconcile(c,approved['approval']['operation_id'])['status'],'verified')

    def test_start_captures_resulting_revision_and_revokes_approval(self):
        case=self.case(approve=True); run=self.begin(case)
        with self.engine.begin() as c:
            row=c.exec_driver_sql('SELECT case_revision,approval_id,generation FROM commerce_cases WHERE id=%s',(case['id'],)).one()
        self.assertEqual(run['case_revision'],row[0]);self.assertIsNone(row[1])
        self.assertEqual(run['generation'],case['generation']+1)
        from decisionops.commerce.execution import execute
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            with self.assertRaises(ValueError):execute(c,case['id'],case['approval']['operation_id'])

    def test_incomplete_propose_has_no_safety_reads(self):
        from unittest.mock import patch
        run=self.begin()
        with patch.object(self.s,'safety_check',side_effect=AssertionError('Hidden safety reads')):
            run=self.advance(run,{'kind':'propose'})
        self.assertEqual(run['decision_attempts'],1);self.assertEqual(run['state'],'active')
        self.assertEqual(run['steps'][-1]['kind'],'choice_rejected')

    def test_stock_drift_requires_explicit_refresh_not_guard_observations(self):
        run=self.read_all(self.begin())
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
        run=self.advance(run,{'kind':'propose'})
        self.assertEqual(run['state'],'active');self.assertEqual(len(run['observations']),7)
        self.assertIsNone(run['assessment']['facts']['stock_available'])
        self.assertEqual(run['steps'][-1]['kind'],'safety_drift')
        run=self.advance(run,{'kind':'read','tool':'inventory'})
        run=self.advance(run,{'kind':'propose'})
        self.assertEqual(run['state'],'proposed');self.assertEqual(len(run['observations']),8)
        self.assertEqual(len(run['supersessions']),1)

    def test_blocker_scope_and_unknown_disclosure(self):
        early=self.begin(); early=self.advance(early,{'kind':'read','tool':'order_manifest'})
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE payments SET status='failed' WHERE order_id='ORD-1042'")
        early=self.advance(early,{'kind':'read','tool':'payment'});early=self.advance(early,{'kind':'report_blocker'})
        self.assertEqual(early['terminal']['case_status'],'needs_review')
        self.assertIn('inventory',early['terminal']['unread_tools']);self.assertIn('fulfilment',early['terminal']['unresolved_scope'])
        stock=self.s.drive(self.engine,self.begin(self.case('STOCK',{'shirt-red-M':1}))['id'])
        self.assertEqual(stock['terminal']['case_status'],'blocked')
        partial=self.s.drive(self.engine,self.begin(self.case('PARTCOMP',{'shirt-blue-M':2}))['id'])
        self.assertEqual(partial['terminal']['case_status'],'needs_review')

    def test_rejected_choices_exhaust_decisions(self):
        run=self.begin()
        for index in range(16):run=self.advance(run,{'kind':'execute','override':'ignore approval'})
        self.assertEqual(run['decision_attempts'],16)
        run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        self.assertEqual(run['state'],'review');self.assertEqual(run['tool_attempts'],0)
        self.assertEqual(run['terminal']['reason'],'decision_budget_exhausted')

    def test_failed_tool_retries_are_counted_and_capped(self):
        from unittest.mock import patch
        from sqlalchemy.exc import SQLAlchemyError
        run=self.begin()
        with patch('decisionops.commerce.adaptive_tools.projected_rows',side_effect=SQLAlchemyError('injected read failure')):
            run=self.advance(run,{'kind':'read','tool':'order_manifest'})
            run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        self.assertEqual(run['tool_attempts'],2);self.assertEqual(run['tool_counts']['order_manifest'],2)
        run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        self.assertEqual(run['steps'][-1]['kind'],'choice_rejected')
        run=self.s.drive(self.engine,run['id']);self.assertEqual(run['state'],'review')
        self.assertEqual(len(run['observations']),2);self.assertEqual(len(run['supersessions']),1)

    def test_revision_noop_and_same_generation_staff_change_fence_run(self):
        run=self.begin()
        with self.engine.begin() as c:
            c.exec_driver_sql('UPDATE commerce_cases SET status=status,case_revision=0 WHERE id=%s',(run['case_id'],))
        stale=self.advance(run,{'kind':'read','tool':'order_manifest'})
        self.assertEqual(stale['state'],'stale');self.assertEqual(stale['tool_attempts'],0)
        from decisionops.commerce.cases import escalate_case
        second=self.begin(self.case())
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():escalate_case(c,second['case_id'],'Staff escalation')
        second=self.advance(second,{'kind':'request_review','reason':'manual_review'})
        self.assertEqual(second['state'],'stale')
        with self.engine.begin() as c:self.assertEqual(c.exec_driver_sql('SELECT status FROM commerce_cases WHERE id=%s',(second['case_id'],)).scalar_one(),'escalated')

    def test_concurrent_starts_and_advancement(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        case=self.case();barrier=threading.Barrier(2)
        def start():
            barrier.wait()
            try:return self.begin(case)
            except ValueError:return None
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:start(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1);run=next(r for r in results if r)
        barrier=threading.Barrier(2)
        def advance():
            barrier.wait()
            try:return self.advance(run,{'kind':'read','tool':'order_manifest'})
            except ValueError:return None
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:advance(),range(2)))
        result=self.s.inspect(self.engine,run['id']);self.assertEqual(result['tool_attempts'],1)

    def test_query_deadline_cancels_real_lock_wait(self):
        import time
        run=self.begin(deadline_seconds=0.5)
        locker=self.engine.connect();txn=locker.begin()
        locker.exec_driver_sql('LOCK TABLE orders IN ACCESS EXCLUSIVE MODE')
        began=time.monotonic()
        try:run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        finally:txn.rollback();locker.close()
        self.assertLess(time.monotonic()-began,2)
        self.assertEqual(run['state'],'review')
        self.assertIsNone(run['assessment']['facts']['quantities_valid'])

    def test_audit_binding_and_counters_cannot_be_rewritten(self):
        from sqlalchemy.exc import DBAPIError
        run=self.advance(self.begin(),{'kind':'read','tool':'order_manifest'})
        for statement in ("UPDATE commerce_adaptive_steps SET kind='tampered'",'DELETE FROM commerce_adaptive_observations',
                          "UPDATE commerce_adaptive_runs SET report='changed'",'UPDATE commerce_adaptive_runs SET decision_attempts=0,context_version=context_version+1'):
            with self.engine.connect() as c,c.begin():
                with self.assertRaises(DBAPIError):c.exec_driver_sql(statement)

    def test_late_result_is_audited_without_overwriting_newer_terminal_run(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        run=self.begin();entered=Event();release=Event();original=self.s.read_tool
        def pause(*args,**kwargs):
            if not entered.is_set():
                entered.set();self.assertTrue(release.wait(8))
            return original(*args,**kwargs)
        with ThreadPoolExecutor(1) as pool,patch.object(self.s,'read_tool',side_effect=pause):
            future=pool.submit(self.advance,run,{'kind':'read','tool':'order_manifest'})
            self.assertTrue(entered.wait(3))
            pending=self.s.inspect(self.engine,run['id'])
            resumed=self.s.recover(self.engine,run['id'],expected_context=pending['context_version'])
            completed=self.s.drive(self.engine,resumed['id'])
            self.assertEqual(completed['state'],'proposed')
            release.set();late=future.result(5)
        self.assertEqual(late['state'],'proposed')
        self.assertEqual(len(late['observations']),8)
        self.assertEqual(late['steps'][-1]['kind'],'tool_result_discarded')
        self.assertEqual(late['tool_attempts'],8)

    def test_newer_approval_and_stale_publication_are_preserved(self):
        from decisionops.commerce.cases import investigate_case,review_case,show_case
        from unittest.mock import patch
        case=self.case();run=self.read_all(self.begin(case))
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            latest=investigate_case(c,case['id'])
            approved=review_case(c,case['id'],latest['generation'],latest['proposal_id'],latest['proposal']['content_hash'],'approve')
        with patch.object(self.s,'safety_check',side_effect=AssertionError('Stale publication performed safety reads')):
            stale=self.advance(run,{'kind':'propose'})
        self.assertEqual(stale['state'],'stale')
        with self.engine.begin() as c:
            saved=show_case(c,case['id']);self.assertEqual(saved['approval_id'],approved['approval_id'])
            self.assertEqual(saved['status'],'approved')

    def test_expiry_cannot_be_filled_by_safety_reads(self):
        import time
        from unittest.mock import patch
        with self.engine.begin() as c:
            c.exec_driver_sql("INSERT INTO policy_versions VALUES ('expiry-policy','demo-store',3,true,10,30)")
            c.exec_driver_sql("UPDATE orders SET policy_id='expiry-policy' WHERE id='ORD-1042'")
            c.exec_driver_sql("UPDATE shipments SET carrier_observed_at=clock_timestamp() WHERE id='SHIP-1042'")
        run=self.read_all(self.begin())
        self.assertTrue(run['assessment']['facts']['loss_confirmed'])
        from datetime import timedelta
        from decisionops.commerce.evidence import utc_timestamp
        carrier=next(o for o in run['observations'] if o['tool']=='carrier_loss')
        expired=utc_timestamp(carrier['expires_at'])+timedelta(milliseconds=1)
        self.assertLess(expired,run['deadline'])
        # Explicit test clock transition after proving complete valid collection.
        # No production lifetime is raised and no immutable observation is edited.
        with patch.object(self.s,'clock',return_value=expired),patch.object(self.s,'safety_check',side_effect=AssertionError('Expired collection invoked safety reads')):
            rejected=self.advance(run,{'kind':'propose'})
        self.assertIsNone(rejected['assessment']['facts']['loss_confirmed'])
        self.assertEqual(rejected['steps'][-1]['kind'],'choice_rejected')

    def test_report_and_projection_caps_are_controlled(self):
        case=self.case()
        with self.assertRaises(ValueError):self.s.start(self.engine,case['id'],'é'*1001)
        huge=self.case(items={'x'*9000:1});run=self.begin(huge)
        finished=self.s.drive(self.engine,run['id'])
        self.assertEqual(finished['state'],'review');self.assertEqual(finished['terminal']['reason'],'policy_context_too_large')

    def test_legacy_revision_coverage_execution_and_provider_paths(self):
        from decisionops.commerce.cases import investigate_case,review_case,show_case
        from decisionops.commerce.execution import execute
        from decisionops.commerce.providers import Limits,Pricing,ProviderConfig
        from decisionops.commerce.provider_budget import create_budget
        from decisionops.commerce.provider_service import recommend
        case=self.case()
        self.assertEqual(case['case_revision'],0)
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            investigated=investigate_case(c,case['id']);self.assertEqual(investigated['case_revision'],1)
            approved=review_case(c,case['id'],investigated['generation'],investigated['proposal_id'],investigated['proposal']['content_hash'],'approve')
            self.assertEqual(approved['case_revision'],2)
            repeated=review_case(c,case['id'],approved['generation'],approved['proposal_id'],approved['proposal']['content_hash'],'approve')
            self.assertEqual(repeated['case_revision'],2)
            execute(c,case['id'],approved['approval']['operation_id']);self.assertEqual(show_case(c,case['id'])['case_revision'],3)
            execute(c,case['id'],approved['approval']['operation_id']);self.assertEqual(show_case(c,case['id'])['case_revision'],3)
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE orders SET policy_id='demo-policy-v1' WHERE id='ORD-POLICY'")
        other=self.case('POLICY')
        with self.engine.begin() as c:create_budget(c,'B',Limits(),Pricing())
        # Existing fake provider routing remains compatible; no model is involved.
        result=recommend(self.engine,other['id'],'revision-provider','B',ProviderConfig(scenario='review'))
        self.assertEqual(result['case']['case_revision'],2)
        self.assertEqual(result['case']['status'],'escalated')

    def test_total_tool_budget_counts_refreshes_and_stops_at_twelve(self):
        run=self.read_all(self.begin())
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
        run=self.advance(run,{'kind':'propose'});run=self.advance(run,{'kind':'read','tool':'inventory'})
        with self.engine.begin() as c:
            c.exec_driver_sql("UPDATE order_lines SET unit_price_minor=2600 WHERE order_id='ORD-1042'")
            c.exec_driver_sql("UPDATE payments SET amount_minor=2600 WHERE order_id='ORD-1042'")
        run=self.advance(run,{'kind':'propose'})
        for tool in ('order_manifest','replacement_policy','payment','fulfilment'):
            run=self.advance(run,{'kind':'read','tool':tool})
        self.assertEqual(run['tool_attempts'],12)
        run=self.advance(run,{'kind':'read','tool':'carrier_loss'})
        self.assertEqual(run['state'],'review');self.assertEqual(run['terminal']['reason'],'tool_budget_exhausted')
        self.assertEqual(run['tool_attempts'],12)

    def test_old_late_audit_does_not_invalidate_new_pending_read(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event,Lock
        from unittest.mock import patch
        run=self.begin();entered=[Event(),Event()];release=[Event(),Event()];mutex=Lock();calls=[]
        original=self.s.read_tool
        def pause(*args,**kwargs):
            with mutex:index=len(calls);calls.append(index)
            entered[index].set();self.assertTrue(release[index].wait(8))
            return original(*args,**kwargs)
        with ThreadPoolExecutor(2) as pool,patch.object(self.s,'read_tool',side_effect=pause):
            first=pool.submit(self.advance,run,{'kind':'read','tool':'order_manifest'})
            self.assertTrue(entered[0].wait(3))
            pending=self.s.inspect(self.engine,run['id'])
            recovered=self.s.recover(self.engine,run['id'],expected_context=pending['context_version'])
            second=pool.submit(self.advance,recovered,{'kind':'read','tool':'order_manifest'})
            self.assertTrue(entered[1].wait(3));release[0].set();first.result(4)
            release[1].set();result=second.result(4)
        self.assertIsNone(result['pending_token']);self.assertTrue(result['assessment']['facts']['quantities_valid'])
        self.assertEqual(result['tool_attempts'],2)

    def test_case_order_and_request_mismatch_is_rejected_at_start(self):
        case=self.case()
        with self.engine.begin() as c:
            c.exec_driver_sql("INSERT INTO commerce_cases(id,order_id,request,status,generation,created_at,updated_at) SELECT 'CASE-BAD','ORD-STOCK',request,'open',0,clock_timestamp(),clock_timestamp() FROM commerce_cases WHERE id=%s",(case['id'],))
        with self.assertRaises(ValueError):self.s.start(self.engine,'CASE-BAD','lost shipment')
        with self.engine.begin() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_adaptive_runs').scalar_one(),0)


    def test_case_lock_is_bounded_by_remaining_deadline(self):
        import time
        from sqlalchemy.exc import SQLAlchemyError
        run=self.begin(deadline_seconds=0.5)
        locker=self.engine.connect();txn=locker.begin()
        locker.exec_driver_sql('SELECT id FROM commerce_cases WHERE id=%s FOR UPDATE',(run['case_id'],))
        started=time.monotonic()
        try:
            with self.assertRaises(SQLAlchemyError):
                self.advance(run,{'kind':'read','tool':'order_manifest'})
        finally:txn.rollback();locker.close()
        self.assertLess(time.monotonic()-started,1.5)
        current=self.s.inspect(self.engine,run['id'])
        self.assertEqual(current['tool_attempts'],0)
        current=self.advance(current,{'kind':'request_review','reason':'manual_review'})
        self.assertEqual(current['terminal']['reason'],'run_deadline')

    def test_cue_and_adversarial_policies_have_recorded_effects(self):
        run=self.s.start(self.engine,self.case('STOCK',{'shirt-red-M':1})['id'],'No stock available',policy='cue')
        run=self.s.drive(self.engine,run['id'])
        self.assertEqual(run['terminal']['case_status'],'needs_review')
        selected=[s['data']['action']['tool'] for s in run['steps'] if s['kind']=='decision_reserved' and s['data']['action']['kind']=='read']
        self.assertEqual(selected,['order_manifest','inventory'])
        for mode in ('fake-override','fake-invalid','fake-unavailable'):
            run=self.begin(policy=mode);run=self.s.drive(self.engine,run['id'])
            self.assertEqual(run['state'],'proposed')
            self.assertEqual(run['decision_attempts'],9)
            self.assertTrue(any(s['kind']=='choice_rejected' for s in run['steps']))
            self.assertTrue(any(s['data'].get('fallback') for s in run['steps']))
        run=self.begin(policy='fake-refuse');run=self.s.drive(self.engine,run['id'])
        self.assertEqual(run['state'],'review');self.assertEqual(run['tool_attempts'],0)

    def test_blocker_expires_between_choice_and_finish(self):
        import time
        from datetime import timedelta
        from unittest.mock import patch
        from decisionops.commerce.adaptive_evidence import Observation
        original_read=self.s.read_tool
        def short(*args,**kwargs):
            obs=original_read(*args,**kwargs)
            if args[1]=='inventory':
                obs=Observation(obs.id,obs.content,obs.observed_at,(datetime.now(timezone.utc)+timedelta(seconds=.2)).isoformat())
            return obs
        run=self.begin(self.case('STOCK',{'shirt-red-M':1}))
        run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        with patch.object(self.s,'read_tool',side_effect=short):
            run=self.advance(run,{'kind':'read','tool':'inventory'})
        original_finish=self.s.finish
        def delayed(*args,**kwargs):
            time.sleep(.3);return original_finish(*args,**kwargs)
        with patch.object(self.s,'finish',side_effect=delayed):
            run=self.advance(run,{'kind':'report_blocker'})
        self.assertNotEqual((run['terminal'] or {}).get('outcome'),'observed_blocker')
        self.assertNotEqual((run['terminal'] or {}).get('case_status'),'blocked')
        self.assertEqual(run['assessment']['decision']['blockers'],[])
        self.assertTrue(any(s['kind']=='safety_drift' for s in run['steps']))

    def test_blocker_source_drift_refresh_and_no_unrequested_validation(self):
        from sqlalchemy import event
        run=self.begin();run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE payments SET status='failed' WHERE order_id='ORD-1042'")
        run=self.advance(run,{'kind':'read','tool':'payment'})
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE payments SET status='paid' WHERE order_id='ORD-1042'")
        sql=[]
        def spy(c,cur,statement,*args):sql.append(statement)
        event.listen(self.engine,'before_cursor_execute',spy)
        try:run=self.advance(run,{'kind':'report_blocker'})
        finally:event.remove(self.engine,'before_cursor_execute',spy)
        self.assertEqual(run['state'],'active');self.assertIsNone(run['assessment']['facts']['paid'])
        self.assertEqual(len(run['observations']),2)
        for table in ('inventory','resolutions','shipments','policy_versions'):
            self.assertFalse(any('FROM '+table in q for q in sql),table)
        run=self.advance(run,{'kind':'read','tool':'payment'})
        self.assertTrue(run['assessment']['facts']['paid'])
        run=self.advance(run,{'kind':'request_review','reason':'manual_review'})
        self.assertEqual(run['terminal']['outcome'],'review')

    def test_supported_scope_drift_requires_refresh_not_blocked(self):
        run=self.read_all(self.begin(self.case('STOCK',{'shirt-red-M':1})))
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE shipment_lines SET quantity=2 WHERE shipment_id='SHIP-STOCK'")
        run=self.advance(run,{'kind':'report_blocker'})
        self.assertEqual(run['state'],'active');self.assertFalse(run['assessment']['scope_complete'])
        self.assertEqual(len(run['observations']),7)
        run=self.advance(run,{'kind':'read','tool':'fulfilment'})
        run=self.advance(run,{'kind':'report_blocker'})
        self.assertEqual(run['terminal']['case_status'],'needs_review')
        self.assertTrue(run['terminal']['decision']['blockers'])
        self.assertTrue(run['terminal']['scope_reasons'])

    def test_budget_blocker_drift_publishes_review(self):
        run=self.read_all(self.begin(self.case('STOCK',{'shirt-red-M':1})))
        for _ in range(9):run=self.advance(run,{'kind':'execute'})
        with self.engine.begin() as c:c.exec_driver_sql("UPDATE inventory SET on_hand=10 WHERE variant_id='shirt-red-M'")
        run=self.advance(run,{'kind':'report_blocker'})
        self.assertEqual(run['state'],'review')
        self.assertEqual(run['terminal']['outcome'],'review')
        self.assertEqual(run['terminal']['decision']['blockers'],[])
        self.assertEqual(run['terminal']['case_status'],'needs_review')
        self.assertEqual(run['decision_attempts'],16)
        self.assertEqual(len(run['observations']),7)

    def test_successful_result_after_deadline_is_unapplied(self):
        import time
        from unittest.mock import patch
        from decisionops.commerce import schema as db
        original=self.s.read_tool
        def delayed(*args,**kwargs):
            obs=original(*args,**kwargs);time.sleep(.6);return obs
        run=self.begin(deadline_seconds=.5)
        with patch.object(self.s,'read_tool',side_effect=delayed):
            run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        self.assertEqual(run['state'],'review');self.assertEqual(run['terminal']['reason'],'run_deadline')
        self.assertEqual(run['tool_attempts'],1);self.assertEqual(len(run['observations']),1)
        self.assertEqual(run['observations'][0]['status'],'success')
        self.assertIsNone(run['assessment']['facts']['quantities_valid'])
        with self.engine.begin() as c:
            self.assertFalse(c.execute(db.adaptive_observations.select()).mappings().one()['applied'])
            self.assertEqual(c.execute(db.adaptive_active.select()).all(),[])

    def test_expired_old_result_preserves_newer_pending_token(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event,Lock
        from unittest.mock import patch
        run=self.begin(deadline_seconds=1);entered=[Event(),Event()];release=[Event(),Event()];mutex=Lock();calls=[]
        original=self.s.read_tool
        def pause(*args,**kwargs):
            obs=original(*args,**kwargs)
            with mutex:index=len(calls);calls.append(index)
            entered[index].set();self.assertTrue(release[index].wait(8));return obs
        with ThreadPoolExecutor(2) as pool,patch.object(self.s,'read_tool',side_effect=pause):
            first=pool.submit(self.advance,run,{'kind':'read','tool':'order_manifest'})
            self.assertTrue(entered[0].wait(3));pending=self.s.inspect(self.engine,run['id'])
            recovered=self.s.recover(self.engine,run['id'],expected_context=pending['context_version'])
            second=pool.submit(self.advance,recovered,{'kind':'read','tool':'order_manifest'})
            self.assertTrue(entered[1].wait(3));new=self.s.inspect(self.engine,run['id'])
            time.sleep(1.1);release[0].set();old=first.result(4)
            try:
                self.assertEqual(old['pending_token'],new['pending_token'])
                self.assertEqual(old['state'],'active')
                self.assertIsNone(old['assessment']['facts']['quantities_valid'])
            finally:release[1].set()
            result=second.result(4)
        self.assertEqual(result['state'],'review');self.assertIsNone(result['pending_token'])
        self.assertIsNone(result['assessment']['facts']['quantities_valid'])

    def test_blocker_expires_while_private_validation_waits_for_lock(self):
        import time
        from datetime import timedelta
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from decisionops.commerce.adaptive_evidence import Observation
        original=self.s.read_tool
        def short(*args,**kwargs):
            obs=original(*args,**kwargs)
            if args[1]=='inventory':
                obs=Observation(obs.id,obs.content,obs.observed_at,(datetime.now(timezone.utc)+timedelta(seconds=.35)).isoformat())
            return obs
        run=self.begin(self.case('STOCK',{'shirt-red-M':1}))
        run=self.advance(run,{'kind':'read','tool':'order_manifest'})
        with patch.object(self.s,'read_tool',side_effect=short):run=self.advance(run,{'kind':'read','tool':'inventory'})
        locker=self.engine.connect();txn=locker.begin()
        locker.exec_driver_sql("SELECT variant_id FROM inventory WHERE variant_id='shirt-red-M' FOR UPDATE")
        try:
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(self.advance,run,{'kind':'report_blocker'})
                time.sleep(.5);txn.rollback();result=future.result(4)
        finally:
            if txn.is_active:txn.rollback()
            locker.close()
        self.assertEqual(result['state'],'active')
        self.assertEqual(result['assessment']['decision']['blockers'],[])
        self.assertEqual(len(result['observations']),2)
        self.assertEqual(result['steps'][-1]['kind'],'safety_drift')

if __name__=='__main__':unittest.main()
