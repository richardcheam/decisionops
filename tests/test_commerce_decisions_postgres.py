"""Decisions SDK transport/accounting against independently migrated test schemas."""
import os,importlib.util,json,unittest
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import test_commerce_api_accounting as legacy

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL') and importlib.util.find_spec('openai'),'Requires isolated PostgreSQL and optional SDK')
class DecisionsAccountingTests(legacy.APIAccountingTests):
    """Run every Responses accounting/fencing regression on Decisions as well."""
    def setup_api(self,**changes):
        from decisionops.commerce.openai_decisions import DecisionsConfig
        from decisionops.commerce.api_accounting import create_budget
        cfg=DecisionsConfig('DECISIONS-PG',**changes)
        with self.engine.begin() as c:create_budget(c,cfg.record())
        return cfg
    def adapter(self,handler):
        from decisionops.commerce.openai_decisions import DecisionsAdapter
        import httpx
        def wrapped(r):
            self.values=[x['value'] for x in json.loads(r.content)['questions'][0]['choices']]
            return handler(r)
        return DecisionsAdapter(api_key='mock-only-secret',transport=httpx.MockTransport(wrapped))
    def response(self,index):
        import httpx
        vals=self.values;chosen=vals[index] if 0<=index<len(vals) else 'unlisted'
        return httpx.Response(200,json={'model':'gpt-6-luna','answers':[{'type':'choice','name':'investigation_action','choice':chosen,'confidence':.9,'probabilities':[{'value':v,'probability':1 if v==chosen else 0} for v in vals]}],
            'usage':{'input_tokens':100,'output_tokens':0,'total_tokens':100}})
    def test_known_input_usage_is_charged_at_decisions_rate_only(self):
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api());tick(self.engine,fence,adapter=self.adapter(lambda _:self.response(0)))
        with self.engine.begin() as c:
            money=c.execute(db.provider_calls.select()).mappings().one()
            self.assertEqual(money['reserved_cost_usd'],Decimal('0.00245760'))
            self.assertEqual(money['actual_cost_usd'],Decimal('0.00001000'))
            budget=c.execute(db.provider_budgets.select()).mappings().one()
            self.assertNotIn('output_per_million',budget['pricing']);self.assertEqual(budget['pricing']['endpoint'],'/v1/decisions')
    def test_refusal_known_usage_settles_and_reviews_without_tool(self):
        import httpx
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api())
        result=tick(self.engine,fence,adapter=self.adapter(lambda _:httpx.Response(200,json={'model':'gpt-6-luna','answers':[{'type':'refusal','name':'investigation_action'}],'usage':{'input_tokens':100,'output_tokens':0,'total_tokens':100}})))
        self.assertEqual(result['event'],'api_review')
        with self.engine.begin() as c:
            row=c.execute(db.provider_calls.select()).mappings().one();self.assertEqual(row['state'],'settled');self.assertEqual(row['actual_cost_usd'],Decimal('0.00001000'))
        self.assertEqual(self.s.inspect(self.engine,job['run_id'])['tool_attempts'],0)
    def test_missing_usage_holds_reservation_and_no_retry(self):
        import httpx
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce import schema as db
        seen=[];job,fence=self.owned(self.setup_api())
        def handler(r):seen.append(r);return httpx.Response(200,json={'model':'gpt-6-luna','answers':[]})
        a=self.adapter(handler);tick(self.engine,fence,adapter=a);tick(self.engine,fence,adapter=a)
        self.assertEqual(len(seen),1)
        with self.engine.begin() as c:
            row=c.execute(db.provider_calls.select()).mappings().one();self.assertEqual(row['state'],'uncertain');self.assertIsNone(row['actual_cost_usd'])
    def test_default_worker_cannot_construct_or_dispatch_api(self):
        from decisionops.commerce.adaptive_runner import tick
        from decisionops.commerce import schema as db
        job,fence=self.owned(self.setup_api())
        with self.assertRaisesRegex(ValueError,'explicit OpenAI adapter'):tick(self.engine,fence)
        with self.engine.begin() as c:self.assertEqual(c.execute(db.provider_calls.select()).all(),[])
    def test_concurrent_money_limit_reserves_only_one(self):
        from decisionops.commerce import adaptive_accounting as ledger,schema as db
        cfg=self.setup_api(max_cost_usd='0.00245760');pairs=[self.owned(cfg),self.owned(cfg)];gate=Barrier(2)
        def reserve(pair):
            job,fence=pair;gate.wait(3)
            try:ledger.prepare(self.engine,job['run_id'],fence);return 'reserved'
            except ValueError:return 'denied'
        with ThreadPoolExecutor(2) as pool:self.assertCountEqual(list(pool.map(reserve,pairs)),['reserved','denied'])
        with self.engine.begin() as c:self.assertEqual(len(c.execute(db.provider_calls.select()).all()),1)
    def test_expired_before_dispatch_settles_known_zero(self):
        from datetime import timedelta
        from decisionops.commerce import adaptive_accounting as ledger,schema as db
        from decisionops.commerce.adaptive_recommendations import Result
        job,fence=self.owned(self.setup_api());row=ledger.prepare(self.engine,job['run_id'],fence)
        with self.engine.begin() as c:
            # Controlled future database clock; immutable deadline itself is unchanged.
            from unittest.mock import patch
            with patch.object(ledger,'clock',return_value=row['deadline']+timedelta(seconds=1)):
                ledger.expire_reserved(c,row['id'])
        with self.engine.begin() as c:
            row=c.execute(db.provider_calls.select()).mappings().one();self.assertEqual(row['state'],'settled');self.assertEqual(row['dispatch_count'],0);self.assertEqual(row['actual_cost_usd'],0)
    def test_operator_mock_factory_uses_decisions_contract(self):
        from decisionops.commerce.api_investigation import mock_transport,adapter_for
        from decisionops.commerce.openai_decisions import DecisionsAdapter,DecisionsConfig
        cfg=self.setup_api();job,fence=self.owned(cfg)
        from decisionops.commerce.adaptive_runner import _run_until_pause
        adapter=adapter_for(cfg)(api_key='mock-only',transport=mock_transport(cfg,'success'))
        self.assertIsInstance(adapter,DecisionsAdapter)
        result=_run_until_pause(self.engine,fence,adapter=adapter)
        self.assertEqual(result['state'],'proposed')
    def test_actual_operator_cli_mock_start_and_inspect(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from decisionops.commerce import api_investigation as cli
        from decisionops.commerce.openai_decisions import DecisionsConfig
        case=self.case();cfg=DecisionsConfig('CLI-MOCK')
        with TemporaryDirectory() as directory:
            p=Path(directory);(p/'config.json').write_text(json.dumps(cfg.record()))
            # Same engine/schema; CLI still checks actual database/user/server identity.
            with patch.object(cli,'database_engine',return_value=self.engine),redirect_stdout(StringIO()):
                self.assertEqual(cli.main(['start','--case',case['id'],'--report','Fictional lost shipment','--config',str(p/'config.json'),'--output',str(p/'trace')]),0)
            trace=json.loads((p/'trace/trace.json').read_text());self.assertTrue(trace['simulation']);self.assertEqual(trace['run']['state'],'proposed')
            with patch.object(cli,'database_engine',return_value=self.engine),redirect_stdout(StringIO()):
                self.assertEqual(cli.main(['inspect','--run',trace['run']['id']]),0)
    def test_actual_live_cli_without_approval_creates_no_budget_or_job(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from decisionops.commerce import api_investigation as cli,schema as db
        from decisionops.commerce.openai_decisions import DecisionsConfig
        with TemporaryDirectory() as directory:
            p=Path(directory);(p/'config.json').write_text(json.dumps(DecisionsConfig('CLI-NO-APPROVAL',execution='live').record()))
            with patch.object(cli,'database_engine',return_value=self.engine),patch.dict('os.environ',{'OPENAI_API_KEY':'fictional-presence-only'}):
                with self.assertRaisesRegex(ValueError,'explicit matching approval hash'):
                    cli.main(['start','--case','unused','--report','Fictional','--config',str(p/'config.json'),'--output',str(p/'trace')])
            with self.engine.connect() as c:
                self.assertEqual(c.execute(db.provider_budgets.select()).all(),[])
                self.assertEqual(c.execute(db.adaptive_runs.select()).all(),[])
