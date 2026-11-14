"""Dependency-free contract verification; no SDK client, database or model loads."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import browser_evaluation as e


def response(action=None, **changes):
    value={'model':e.load_config()['model'],'status':'completed','usage':{'input_tokens':100,'output_tokens':50},'output':[{'type':'function_call','name':'browser_action','call_id':'test_call','status':'completed','arguments':json.dumps(action or {'action':'observe','url':None,'observation':None,'reference':None,'value':None,'result':None})}]}
    value.update(changes)
    return value


class BrowserEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config=e.load_config()

    def ledger(self):return e.Ledger(Path(self.temp.name)/'single',self.config,'reviewed')

    def test_reservation_and_exact_cost_caps(self):
        self.assertEqual(str(e.reservation(self.config)), '0.00512')
        self.assertEqual(e.reservation(self.config)*48, e.Decimal('0.245760'))
        ledger=self.ledger()
        for case in range(6):
            for _ in range(8):
                c=ledger.reserve({'input':'bounded'},str(case));ledger.dispatch(c);ledger.record(c,response(),0.01)
        with self.assertRaisesRegex(ValueError,'request cap'):ledger.reserve({},'new')

    def test_existing_and_expired_ledgers_do_not_replenish(self):
        ledger=self.ledger()
        with self.assertRaises(FileExistsError):self.ledger()
        ledger.value['deadline']=time.time()-1
        ledger.persist()
        with self.assertRaises(ValueError):ledger.reserve({},'case')
        self.assertEqual(len(json.loads((ledger.directory/'ledger.json').read_text())['calls']),0)

    def test_request_bound_and_metadata_exclusion(self):
        observation={'id':'local-ref','url':'http://127.0.0.1:8097/account','text':'visible','blocks':[],'controls':[],'truncated':False,'document_hash':'PRIVATE_HASH','observed_at':'audit-only'}
        body=e.request_body(self.config,{'observation':e.clean_observation(observation)})
        self.assertNotIn('PRIVATE_HASH',e.canonical(body).decode())
        self.assertNotIn('audit-only',e.canonical(body).decode())
        self.assertNotIn('previous_response_id',body)
        self.assertFalse(body['store'])
        with self.assertRaisesRegex(ValueError,'byte bound'):e.request_body(self.config,{'text':'x'*32768})

    def test_invalid_choice_refusal_wrong_model_and_incomplete(self):
        for value in [response(model='another'),response(status='incomplete'),response(output=[{'content':[{'type':'refusal','refusal':'no'}]}]),response(action={'action':'execute'}),response(output=[{'content':[{'type':'output_text','text':'not JSON'}]}])]:
            with self.subTest(value=value),self.assertRaises((ValueError,json.JSONDecodeError)):e.parse_action(value,self.config)
        self.assertEqual(e.parse_action(response(),self.config)['action'],'observe')

    def test_unknown_usage_retains_reservation_and_known_usage_settles(self):
        ledger=self.ledger();c=ledger.reserve({},'case');ledger.dispatch(c)
        with self.assertRaisesRegex(ValueError,'unknown_usage'):ledger.record(c,response(usage=None),0.02)
        self.assertEqual(c['reserved_usd'],'0.00512')
        self.assertEqual(c['state'],'known_result_unknown_usage')
        with self.assertRaisesRegex(ValueError,'Unresolved'):ledger.reserve({},'case')
        ledger=e.Ledger(Path(self.temp.name)/'known',self.config,'reviewed')
        d=ledger.reserve({},'case');ledger.dispatch(d);ledger.record(d,response(),0.02)
        self.assertEqual(d['state'],'settled')
        self.assertEqual(d['usage']['input_tokens'],100)

    def test_timeout_after_dispatch_is_uncertain_and_no_retry(self):
        ledger=self.ledger()
        bridge=FakeBridge()
        calls=[]
        def dispatch(*args):calls.append(args);raise TimeoutError()
        with self.assertRaisesRegex(RuntimeError,'Uncertain'):
            e.investigate(bridge,{},'http://127.0.0.1:8096/shop',self.config,ledger,'case',dispatch)
        self.assertEqual(len(calls),1)
        self.assertEqual(ledger.value['calls'][0]['state'],'uncertain')
        self.assertEqual(len(bridge.calls),1)

    def test_late_result_is_settled_but_not_applied(self):
        ledger=self.ledger();bridge=FakeBridge()
        clock=time.time()
        with patch.object(e.time,'time',return_value=clock) as wall:
            def dispatch(*args):
                wall.return_value=clock+61
                return response()
            with self.assertRaisesRegex(TimeoutError,'Late result'):
                e.investigate(bridge,{},'http://127.0.0.1:8096/shop',self.config,ledger,'case',dispatch)
        self.assertEqual(len(bridge.calls),1)
        self.assertEqual(ledger.value['calls'][0]['state'],'settled')
        self.assertEqual(ledger.value['calls'][0]['application_status'],'late_unapplied')

    def test_bound_action_applies_and_finish_is_browser_validated(self):
        ledger=self.ledger();bridge=FakeBridge()
        actions=[{'action':'act','url':None,'observation':'o1','reference':'c0','value':None,'result':None},{'action':'finish','url':None,'observation':None,'reference':None,'value':None,'result':{'outcome':'missing_evidence','reason':'absent','findings':None,'citations':[],'unknowns':['event']}}]
        result=e.investigate(bridge,{},'http://127.0.0.1:8096/shop',self.config,ledger,'case',lambda *_:response(actions.pop(0)))
        self.assertEqual(result['outcome'],'finished')
        self.assertEqual([c['op'] for c in bridge.calls],['start','act','finish'])
        self.assertEqual(len(ledger.value['calls']),2)


    def test_frozen_build_hashes_reject_stale_executables(self):
        root=Path(self.temp.name)/'fixture';(root/'evaluation').mkdir(parents=True)
        compiled=root/'compiled.js';compiled.write_bytes(b'reviewed build')
        import hashlib
        (root/'evaluation/FROZEN.json').write_text(json.dumps({'files':{'compiled.js':hashlib.sha256(compiled.read_bytes()).hexdigest()}}))
        with patch.object(e,'BROWSER',root):
            e.validate_frozen()
            compiled.write_bytes(b'stale executable')
            with self.assertRaisesRegex(ValueError,'Frozen input/source mismatch'):e.validate_frozen()

    def test_serving_identity_and_asset_mismatch_fail_closed(self):
        import hashlib
        health={'server_sha256':hashlib.sha256((e.BROWSER/'fixtures/server.mjs').read_bytes()).hexdigest(),'records_sha256':hashlib.sha256((e.BROWSER/'fixtures/records.json').read_bytes()).hexdigest()}
        class Response:
            def __init__(self,data):self.data=data
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,*_):return self.data
        class Opener:
            def open(self,url,timeout):
                if url.endswith('/health'):return Response(json.dumps(health).encode())
                return Response(b'different build')
        temporary_root=Path(self.temp.name)/'serving-test'
        (temporary_root/'runs/browser-investigation/dist').mkdir(parents=True)
        (temporary_root/'runs/browser-investigation/dist/evaluation.html').write_bytes(b'reviewed asset')
        with patch.object(e,'ROOT',temporary_root),patch('urllib.request.build_opener',return_value=Opener()):
            with self.assertRaisesRegex(ValueError,'Served fixture asset differs'):e.verify_serving_identity()
            health['server_sha256']='stale'
            with self.assertRaisesRegex(ValueError,'Running fixture identity mismatch'):e.verify_serving_identity()


    def test_browser_failure_on_final_action_continues_remaining_cases(self):
        # Exercise main's real continuation branch, not a copy of its policy.
        # Both early and final failures use the original frozen call cap.
        real_investigate=e.investigate
        real_ledger=e.Ledger
        for failure_at in (1,self.config['calls_per_case']):
            with self.subTest(failure_at=failure_at):
                bridge=FinalActionBridge(failure_at)
                ledgers=[]
                dispatches=[]
                def ledger_factory(*args):
                    ledger=real_ledger(*args);ledgers.append(ledger);return ledger
                def dispatch(*args):
                    dispatches.append(args)
                    return response()
                def investigate(*args):return real_investigate(*args,dispatch=dispatch)
                output=Path(self.temp.name)/('failure-'+str(failure_at))
                args=['browser_evaluation.py','--run-live-test','--approve-config',e.digest(self.config),'--source','reviewed','--output',str(output)]
                with patch('sys.argv',args), patch.object(e,'validate_frozen'), patch.object(e,'verify_serving_identity'), patch.object(e.subprocess,'check_output',side_effect=['reviewed','']), patch('importlib.metadata.version',return_value=self.config['sdk_version']), patch.object(e.os,'environ',{'OPENAI_API_KEY':'fictional-test-only'}), patch.object(e,'Ledger',side_effect=ledger_factory), patch.object(e,'Bridge',return_value=bridge), patch.object(e,'investigate',side_effect=investigate):
                    e.main()
                cases=json.loads((e.BROWSER/'evaluation/inputs.json').read_text())['cases']
                self.assertEqual(len(dispatches),len(cases)*failure_at)
                self.assertEqual(bridge.starts,len(cases))
                self.assertTrue(bridge.closed)
                for case in cases:
                    saved=json.loads((output/(case['key']+'.json')).read_text())
                    self.assertEqual(saved['result']['outcome'],'operational_stop')
                    self.assertEqual(saved['result']['error'],bridge.error)
                    self.assertEqual(saved['browser_audit']['reply'],{'ok':False,'error':bridge.error})
                persisted=json.loads((output/'ledger.json').read_text())
                self.assertEqual(persisted['state'],'completed')
                if failure_at==self.config['calls_per_case']:
                    self.assertEqual(persisted['current_case']['reply'],{'ok':False,'error':bridge.error})
                self.assertEqual(len(persisted['calls']),len(cases)*failure_at)
                self.assertTrue(all(call['state']=='settled' for call in persisted['calls']))
                self.assertEqual(persisted['calls'][-1]['application_status'],'rejected')

    def test_successful_final_action_remains_genuine_model_budget_exhaustion(self):
        bridge=FinalActionBridge(None)
        ledger=self.ledger()
        dispatches=[]
        def dispatch(*args):dispatches.append(args);return response()
        result=e.investigate(bridge,{},'http://127.0.0.1:8096/shop',self.config,ledger,'case',dispatch)
        self.assertEqual(result['outcome'],'model_budget_exhausted')
        self.assertNotIn('error',result)
        self.assertEqual(len(dispatches),self.config['calls_per_case'])
        self.assertEqual(len(bridge.calls),1+self.config['calls_per_case'])
        persisted=json.loads((ledger.directory/'ledger.json').read_text())
        self.assertTrue(persisted['current_case']['reply']['ok'])
        self.assertEqual(persisted['current_case']['reply'],bridge.last_reply)
        self.assertEqual(persisted['calls'][-1]['application_status'],'applied')


class FakeBridge:
    def __init__(self):self.calls=[]
    def call(self,message,timeout):
        self.calls.append(message)
        if message['op']=='finish':return {'ok':True,'result':{'execution_authorized':False}}
        return {'ok':True,'observation':{'id':'o1','url':'http://127.0.0.1:8096/shop','text':'visible only','blocks':[],'controls':[{'reference':'c0','name':'Details','role':'link','state':''}],'truncated':False,'document_hash':'HASH','observed_at':'NOW'},'features':{'remaining':{'actions':11}}}


class FinalActionBridge(FakeBridge):
    """Model-free browser failure at an explicitly counted action boundary."""
    def __init__(self,failure_at):
        super().__init__()
        self.failure_at=failure_at
        self.error={'kind':'navigation_failure','reason':'Tracking page unavailable on selected action'}
        self.starts=0
        self.actions=0
        self.closed=False
        self.last_reply=None
    def call(self,message,timeout):
        if message['op']=='start':self.starts+=1;self.actions=0
        elif message['op']=='close':
            self.calls.append(message)
            return {'ok':True,'reply':self.last_reply}
        else:self.actions+=1
        reply=super().call(message,timeout)
        if message['op']!='start' and self.actions==self.failure_at:
            reply={'ok':False,'error':self.error}
        self.last_reply=reply
        return reply
    def close(self):self.closed=True
