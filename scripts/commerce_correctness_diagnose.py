"""Capture original/corrected boundaries without changing dispatch/ownership behavior."""
import json,os,sys,time,unittest
from dataclasses import asdict,is_dataclass
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from decisionops.commerce.database import database_engine
from sqlalchemy.engine import make_url
url=make_url(os.environ['COMMERCE_TEST_DATABASE_URL'])
if (url.host,url.port,url.database,url.username)!=('127.0.0.1',55443,'commerce_stage5_correction','commerce_correction'):raise ValueError('Use only verified correction test environment')
admin=database_engine(url)
with admin.connect() as c:
    identity=tuple(c.exec_driver_sql('SELECT current_database(),current_user,inet_server_port()').one())
if identity!=('commerce_stage5_correction','commerce_correction',5432):raise ValueError('Wrong database')
admin.dispose()
from decisionops.commerce import provider_budget,adaptive_accounting,adaptive_recommendations,adaptive_jobs,adaptive_workflow
import test_commerce_execution as fixtures
import test_commerce_adaptive_jobs as adaptive_tests
import test_commerce_adaptive_core as core_tests
records=[]
def observed(module,name):
    original=getattr(module,name)
    def wrapped(*args,**kwargs):
        before=datetime.now(timezone.utc).isoformat();start=time.monotonic()
        try:
            row=original(*args,**kwargs)
            records.append({'boundary':module.__name__+'.'+name,'before':before,'after':datetime.now(timezone.utc).isoformat(),'seconds':time.monotonic()-start,'returned':asdict(row) if is_dataclass(row) else dict(row) if isinstance(row,Mapping) else str(row) if row is not None else None})
            return row
        except Exception as e:
            records.append({'boundary':module.__name__+'.'+name,'before':before,'after':datetime.now(timezone.utc).isoformat(),'seconds':time.monotonic()-start,'error':type(e).__name__+':'+str(e)});raise
    return wrapped
original_saver=adaptive_workflow.checkpoint_saver
@contextmanager
def observed_saver(url,end):
    records.append({'boundary':'checkpoint_saver_enter','at':datetime.now(timezone.utc).isoformat(),
                    'monotonic_deadline':end,'remaining_seconds':end-time.monotonic()})
    try:
        with original_saver(url,end) as saver:yield saver
    except Exception as error:
        records.append({'boundary':'checkpoint_saver_error','at':datetime.now(timezone.utc).isoformat(),'error':type(error).__name__+':'+str(error)})
        raise
original_cleanup=fixtures.ExecutionRaceTests.cleanup_schema
original_adaptive_cleanup=adaptive_tests.AdaptiveJobTests.cleanup
output=Path(os.environ.get('COMMERCE_DIAG_OUTPUT','runs/correction-verification/diagnosis-original.json'))
def cleanup(self):
    try:
        import sqlalchemy as sa
        from decisionops.commerce import schema as db
        with self.engine.connect() as c:
            c.exec_driver_sql("SET LOCAL statement_timeout='1s'")
            snapshot={'database_time':c.exec_driver_sql('SELECT clock_timestamp()').scalar_one(),'tables':{t.name:[dict(r) for r in c.execute(sa.select(t)).mappings()] for t in (db.provider_calls,db.provider_budgets,db.adaptive_calls,db.adaptive_call_events,db.adaptive_jobs,db.adaptive_runs,db.adaptive_observations,db.adaptive_steps,db.cases)}}
        records.append({'boundary':'before_schema_cleanup','test':self.id(),'durable':snapshot})
    finally:
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({'identity':identity,'records':records},indent=2,default=str)+'\n');(original_adaptive_cleanup if self.id().startswith('test_commerce_adaptive_') else original_cleanup)(self)
names=['test_commerce_provider_postgres.ProviderDatabaseTests.test_real_deadline_returns_before_delayed_fake_finishes','test_commerce_adaptive_jobs.AdaptiveJobTests.test_checkpoint_lock_is_bounded_after_domain_commit_and_recovery_does_not_repeat','test_commerce_adaptive_jobs.AdaptiveJobTests.test_staff_approval_execution_is_preserved_during_cancelled_recommendation','test_commerce_adaptive_jobs.AdaptiveJobTests.test_terminal_graph_resume_repairs_job_after_lease_expiry']
if '--extra-boundaries' in sys.argv:
    names=['test_commerce_adaptive_core.AdaptiveCoreTests.test_expiry_cannot_be_filled_by_safety_reads','test_commerce_adaptive_jobs.AdaptiveJobTests.test_cancellation_during_decision_keeps_uncertain_reservation','test_commerce_adaptive_jobs.AdaptiveJobTests.test_checkpoint_write_timeout_preserves_committed_publication']
if '--include-admission' in sys.argv:
    names+=['test_commerce_provider_postgres.ProviderDatabaseTests.test_expired_before_dispatch_is_known_zero_work','test_commerce_adaptive_jobs.AdaptiveJobTests.test_staff_change_before_dispatch_rejects_without_adapter_work']
with patch.object(core_tests.AdaptiveCoreTests,'cleanup',cleanup),patch.object(adaptive_workflow,'checkpoint_saver',observed_saver),patch.object(adaptive_tests.AdaptiveJobTests,'cleanup',cleanup),patch.object(fixtures.ExecutionRaceTests,'cleanup_schema',cleanup),patch.object(provider_budget,'claim',observed(provider_budget,'claim')),patch.object(adaptive_accounting,'claim',observed(adaptive_accounting,'claim')),patch.object(adaptive_recommendations.FakeAdapter,'choose',observed(adaptive_recommendations.FakeAdapter,'choose')),patch.object(adaptive_jobs,'renew',observed(adaptive_jobs,'renew')):
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromNames(names))
sys.exit(not result.wasSuccessful())
