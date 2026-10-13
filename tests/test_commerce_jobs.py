"""Real job lease/fencing and LangGraph checkpoint recovery tests."""
import os
import unittest

import test_commerce_execution as execution_fixtures


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'PostgreSQL integration is opt-in')
class JobTests(unittest.TestCase):
    def setUp(self):
        execution_fixtures.ExecutionRaceTests.setUp(self)
        # Only this disposable schema gets freshly observed fictional tracking.
        with self.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE shipments SET carrier_observed_at=clock_timestamp()")

    def cleanup_schema(self):
        # Worker tests also own their separate checkpoint namespace, if setup ran.
        from decisionops.commerce.workflow import graph_schema
        with self.admin.begin() as connection:
            namespace = graph_schema(self.schema)
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{namespace}" CASCADE')
        execution_fixtures.ExecutionRaceTests.cleanup_schema(self)

    def opened(self):
        from decisionops.commerce.cases import open_case
        from decisionops.commerce.read_tools import AssessmentRequest
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            return open_case(connection, AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))

    def queued(self, case=None, action='investigate', operation=None):
        from decisionops.commerce.jobs import enqueue
        case = case or self.opened()
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            return enqueue(connection, case['id'], action, operation)

    def claim(self, seconds=30):
        from decisionops.commerce.jobs import claim
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            return claim(connection, seconds)

    def test_claim_and_fence_reclaimed_lease(self):
        from decisionops.commerce.jobs import complete, LeaseLost
        job = self.queued()
        old = self.claim()
        self.assertIsNone(self.claim())
        with self.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE commerce_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job['id'],))
        new = self.claim()
        self.assertNotEqual(old['token'], new['token'])
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            with self.assertRaises(LeaseLost):
                complete(connection, job['id'], old['token'])
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            self.assertEqual(complete(connection, job['id'], new['token'])['status'], 'awaiting_review')

    def test_same_case_has_one_inflight_job_and_attempt_limit(self):
        from decisionops.commerce.jobs import get_job
        case = self.opened()
        first, second = self.queued(case), self.queued(case)
        self.assertEqual(first['id'], second['id'])
        for _ in range(3):
            owned = self.claim()
            self.assertIsNotNone(owned)
            with self.engine.begin() as connection:
                connection.exec_driver_sql("UPDATE commerce_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (first['id'],))
        self.assertIsNone(self.claim())
        with self.engine.connect() as connection:
            self.assertEqual(get_job(connection, first['id'])['status'], 'failed')

    def test_checkpoint_failure_after_commit_replays_without_new_investigation(self):
        from unittest.mock import patch
        from decisionops.commerce.workflow import setup_checkpoints, run_graph
        from decisionops.commerce.jobs import get_job
        setup_checkpoints(self.engine)
        job = self.queued()
        owned = self.claim()
        from langgraph.checkpoint.postgres import PostgresSaver
        original = PostgresSaver.put
        def fail_after_commit(saver, *args, **kwargs):
            with self.engine.connect() as connection:
                done = get_job(connection, job['id'])['status'] == 'completed'
            if done:
                raise RuntimeError('simulated checkpoint outage after business commit')
            return original(saver,*args,**kwargs)
        with patch.object(PostgresSaver,'put',fail_after_commit):
            with self.assertRaises(RuntimeError):
                run_graph(self.engine, job['id'], owned['token'])
        repaired = run_graph(self.engine, job['id'], owned['token'])
        self.assertEqual(repaired['phase'],'awaiting_review')
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_investigations').scalar_one(),1)

    def test_durable_review_interrupt_resumes_only_after_real_approval(self):
        from decisionops.commerce.workflow import setup_checkpoints, run_graph, resume_graph, inspect_graph
        from decisionops.commerce.cases import show_case, review_case
        setup_checkpoints(self.engine)
        job=self.queued()
        owned=self.claim()
        self.assertEqual(run_graph(self.engine,job['id'],owned['token'])['phase'],'awaiting_review')
        # New saver connection reads a durable checkpoint; no in-memory state.
        self.assertEqual(inspect_graph(self.engine,job['id'])['next'], ['review_gate'])
        with self.assertRaises(ValueError):
            resume_graph(self.engine,job['id'])
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection,connection.begin():
            case=show_case(connection,job['case_id'])
            approved=review_case(connection,case['id'],case['generation'],case['proposal']['id'],case['proposal']['content_hash'],'approve')
        self.assertEqual(resume_graph(self.engine,job['id'])['phase'],'approved')
        execution=self.queued(approved,'execute',approved['approval']['operation_id'])
        owned=self.claim()
        self.assertEqual(run_graph(self.engine,execution['id'],owned['token'])['phase'],'verified')

    def test_expired_lease_during_business_work_rolls_back(self):
        from unittest.mock import patch
        from datetime import timedelta
        from decisionops.commerce import jobs
        owned_job=self.queued()
        owned=self.claim()
        real=jobs.clock
        calls=0
        def expiry(connection):
            nonlocal calls
            calls+=1
            now=real(connection)
            return now+timedelta(minutes=10) if calls>1 else now
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection:
            with self.assertRaises(jobs.LeaseLost):
                with connection.begin(),patch.object(jobs,'clock',side_effect=expiry):
                    jobs.complete(connection,owned_job['id'],owned['token'])
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_investigations').scalar_one(),0)

    def test_worker_cli_restart_inspects_persisted_interrupt(self):
        import json
        import subprocess
        import sys
        from decisionops.commerce.workflow import setup_checkpoints
        setup_checkpoints(self.engine)
        job=self.queued()
        env=dict(os.environ,COMMERCE_DATABASE_URL=self.engine.url.render_as_string(hide_password=False))
        def cli(*args):
            result=subprocess.run([sys.executable,'-B','-m','decisionops.commerce.worker',*args],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(cli('once')['phase'],'awaiting_review')
        shown=cli('show','--job',job['id'])
        self.assertEqual(shown['job']['status'],'completed')
        self.assertEqual(shown['graph']['next'],['review_gate'])
        self.assertEqual(cli('once')['event'],'idle')
