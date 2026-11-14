"""API task integration on per-test PostgreSQL schemas; SDK HTTP is mocked."""
import importlib.util,json,os,unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
import test_commerce_adaptive_core as core

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL') and importlib.util.find_spec('openai'),'Requires isolated PostgreSQL and commerce-api SDK')
class APIAccountingTests(unittest.TestCase):
    setUp=core.AdaptiveCoreTests.setUp
    cleanup=core.AdaptiveCoreTests.cleanup
    case=core.AdaptiveCoreTests.case
    def setup_api(self,**changes):
        from decisionops.commerce.api_decisions import ApiConfig
        from decisionops.commerce.api_accounting import create_budget
        cfg=ApiConfig('API-TEST','https://api.openai.com/v1','gpt-5-mini-2025-08-07','openai-20261016','0.25','2',**changes)
        with self.engine.begin() as c:create_budget(c,cfg.record())
        return cfg
    def owned(self,cfg):
        from decisionops.commerce import adaptive_jobs as jobs
        job=jobs.enqueue(self.engine,self.case()['id'],'A lost shipment; investigate relevant evidence',api=cfg.record())
        owner=jobs.claim(self.engine,job_id=job['id']);return job,jobs.Fence(owner['id'],owner['token'])
    def adapter(self,handler):
        from decisionops.commerce.api_decisions import OpenAIAdapter
        import httpx
        return OpenAIAdapter(api_key='mock-only-secret',transport=httpx.MockTransport(handler))
    def response(self,index):
        import httpx
        return httpx.Response(200,json={'id':'resp_test','object':'response','created_at':1,'status':'completed','model':'gpt-5-mini-2025-08-07',
          'output':[{'type':'message','id':'msg','role':'assistant','status':'completed','content':[{'type':'output_text','text':json.dumps({'action_index':index}),'annotations':[]}]}],
          'usage':{'input_tokens':100,'output_tokens':10,'total_tokens':110}})
    def test_complete_mock_investigation_proposes_through_existing_safety_bridge(self):
        from decisionops.commerce.adaptive_runner import _run_until_pause
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api());seen=[]
        def handler(request):
            body=json.loads(request.content);features=json.loads(body['input']);seen.append(features)
            self.assertNotIn('ARUN-',body['input']);self.assertNotIn('ORD-',body['input'])
            # A separate transaction can lock the case while transport runs.
            with self.engine.begin() as c:
                c.exec_driver_sql("SET LOCAL lock_timeout='100ms'")
                c.execute(db.cases.select().with_for_update())
            actions=features['allowed_actions'];idx=next((i for i,a in enumerate(actions) if a['kind']=='propose'),None)
            if idx is None:idx=next(i for i,a in enumerate(actions) if a['kind']=='read')
            return self.response(idx)
        result=_run_until_pause(self.engine,fence,adapter=self.adapter(handler))
        self.assertEqual(result['state'],'proposed');self.assertEqual(len(seen),8)
        with self.engine.begin() as c:
            money=c.execute(db.provider_calls.select()).mappings().all();self.assertEqual(len(money),8)
            self.assertTrue(all(r['state']=='settled' and r['actual_cost_usd']>0 and r['dispatch_count']==1 for r in money))
            self.assertEqual(c.execute(db.operations.select()).all(),[]);self.assertEqual(c.execute(db.reviews.select()).all(),[])
    def test_timeout_retains_money_and_never_redispatches(self):
        import httpx
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api(max_requests=1));seen=[]
        def handler(r):seen.append(r);raise httpx.ReadTimeout('private server body',request=r)
        adapter=self.adapter(handler);result=tick(self.engine,fence,adapter=adapter)
        self.assertEqual(result['event'],'api_review');tick(self.engine,fence,adapter=adapter);self.assertEqual(len(seen),1)
        state=self.s.inspect(self.engine,job['run_id']);self.assertEqual(state['state'],'review');self.assertEqual(state['tool_attempts'],0)
        with self.engine.begin() as c:
            row=c.execute(db.provider_calls.select()).mappings().one();self.assertEqual(row['state'],'uncertain');self.assertIsNone(row['actual_cost_usd']);self.assertGreater(row['reserved_cost_usd'],0)
    def test_malformed_choice_settles_usage_but_reviews_without_rules(self):
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api());result=tick(self.engine,fence,adapter=self.adapter(lambda _:self.response(999)))
        self.assertEqual(result['event'],'api_review');self.assertEqual(self.s.inspect(self.engine,job['run_id'])['tool_attempts'],0)
        with self.engine.begin() as c:self.assertGreater(c.execute(db.provider_calls.select()).mappings().one()['actual_cost_usd'],0)
    def test_reservation_race_counts_shared_budget_atomically(self):
        from decisionops.commerce import adaptive_accounting as ledger,schema as db
        cfg=self.setup_api(max_requests=1);pairs=[self.owned(cfg),self.owned(cfg)];gate=Barrier(2)
        def reserve(pair):
            job,fence=pair;gate.wait(3)
            try:ledger.prepare(self.engine,job['run_id'],fence);return 'reserved'
            except ValueError:return 'denied'
        with ThreadPoolExecutor(2) as pool:self.assertCountEqual(list(pool.map(reserve,pairs)),['reserved','denied'])
        with self.engine.begin() as c:self.assertEqual(len(c.execute(db.provider_calls.select()).all()),1)
    def test_restart_after_dispatch_retains_uncertainty_no_sdk_call(self):
        from decisionops.commerce import adaptive_accounting as ledger
        from decisionops.commerce.adaptive_runner import tick
        job,fence=self.owned(self.setup_api());call=ledger.prepare(self.engine,job['run_id'],fence);ledger.claim(self.engine,call['id'],fence)
        result=tick(self.engine,fence,adapter=self.adapter(lambda _:self.fail('Uncertain call redispatched')))
        self.assertEqual(result['event'],'uncertain_decision')
    def test_staff_change_after_known_result_fences_application(self):
        from decisionops.commerce.adaptive_runner import tick,Interrupted
        from decisionops.commerce.cases import escalate_case
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api());adapter=self.adapter(lambda _:self.response(0))
        with self.assertRaises(Interrupted):tick(self.engine,fence,adapter=adapter,fault='after_result')
        with self.engine.begin() as c:
            run=self.s.row(c,job['run_id']);escalate_case(c,run['case_id'],'Staff took ownership')
        tick(self.engine,fence,adapter=self.adapter(lambda _:self.fail('Settled result redispatched')))
        self.assertEqual(self.s.inspect(self.engine,job['run_id'])['state'],'stale')
        with self.engine.begin() as c:self.assertEqual(c.execute(db.cases.select()).mappings().one()['status'],'escalated')
    def test_stale_deadline_after_result_cannot_apply_or_redispatch(self):
        from unittest.mock import patch
        from datetime import timedelta
        from decisionops.commerce import adaptive_runner as runner,adaptive_accounting as ledger
        job,fence=self.owned(self.setup_api());adapter=self.adapter(lambda _:self.response(0))
        with self.assertRaises(runner.Interrupted):runner.tick(self.engine,fence,adapter=adapter,fault='after_result')
        with self.engine.begin() as c:call=ledger.latest(c,job['run_id'])
        with patch.object(runner,'datetime') as clock:
            clock.now.return_value=call['deadline']+timedelta(seconds=1)
            result=runner.tick(self.engine,fence,adapter=self.adapter(lambda _:self.fail('Late result redispatched')))
        self.assertEqual(result['event'],'api_review');self.assertEqual(self.s.inspect(self.engine,job['run_id'])['tool_attempts'],0)
    def test_monetary_exhaustion_reviews_without_transport(self):
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api(max_cost_usd='0.001'))
        self.assertEqual(tick(self.engine,fence,adapter=self.adapter(lambda _:self.fail('Exhausted budget dispatched')))['event'],'api_review')
        with self.engine.begin() as c:self.assertEqual(c.execute(db.provider_calls.select()).all(),[])
    def test_staff_change_during_transport_cancels_and_preserves_staff_state(self):
        import asyncio
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce.cases import escalate_case
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api())
        async def handler(request):
            with self.engine.begin() as c:
                run=self.s.row(c,job['run_id']);escalate_case(c,run['case_id'],'Staff takeover during API')
            await asyncio.sleep(.3)
            return self.response(0)
        tick(self.engine,fence,adapter=self.adapter(handler))
        with self.engine.begin() as c:
            self.assertEqual(c.execute(db.cases.select()).mappings().one()['status'],'escalated')
            self.assertEqual(c.execute(db.provider_calls.select()).mappings().one()['state'],'uncertain')
