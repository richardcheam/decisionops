"""Optional real cached-browser bridge with scripted fake API choices. No paid calls.
Fixture-specific route selection is confined to this test, never controller features.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from scripts import browser_evaluation as e
import asyncio
try:
    import httpx2 as httpx
    from openai import AsyncOpenAI
except ImportError:
    httpx=AsyncOpenAI=None

@unittest.skipUnless(os.environ.get('BROWSER_FIXTURE_TESTS')=='1' and AsyncOpenAI is not None,'explicit isolated browser fixtures not selected')
class BrowserBridgeTests(unittest.TestCase):
    def test_actual_controller_browser_bridge_and_cleanup_with_fake_choices(self):
        config=e.load_config()
        with tempfile.TemporaryDirectory() as temporary:
            ledger=e.Ledger(Path(temporary)/'run',config,'model-free-scripted')
            bridge=e.Bridge(ledger.directory)
            def fake(body,timeout):
                context=json.loads(body['input']);o=context['observations'][-1]
                actions=[c for c in o['controls'] if c['name']=='View order OR-4821 →' or c['name']=='Track shipment →']
                if actions:
                    action={'action':'act','observation':o['id'],'reference':actions[0]['reference'],'url':None,'value':None,'result':None}
                else:
                    history=context['observations'];item=next(v for v in history if any('shirt-blue-M' in b['text'] and 'Quantity 1' in b['text'] for b in v['blocks']))
                    ib=next(b for b in item['blocks'] if 'shirt-blue-M' in b['text'] and 'Quantity 1' in b['text'])
                    pb=next(b for b in o['blocks'] if 'PK-6204' in b['text'])
                    def cite(obs,block,quote):return {'observation':obs['id'],'block':block['reference'],'quote':quote}
                    fields={'order':cite(item,ib,'OR-4821'),'item':cite(item,ib,ib['text']),'parcel':cite(o,pb,'PK-6204'),'claim':cite(o,pb,'lost'),'event_time':cite(o,pb,'13 Nov 2026, 10:00 UTC')}
                    action={'action':'finish','observation':None,'reference':None,'url':None,'value':None,'result':{'outcome':'evidence_found','reason':'scripted fake test only','findings':fields,'citations':[],'unknowns':[]}}
                payload={'model':config['model'],'status':'completed','usage':{'input_tokens':1,'output_tokens':1,'simulated':True},'output':[{'type':'function_call','name':'browser_action','call_id':'mock_call_'+str(len(ledger.value['calls'])),'status':'completed','arguments':json.dumps(action)}]}
                async def transport(request):
                    sent=json.loads(request.content)
                    self.assertEqual(sent['input'],body['input'])
                    self.assertFalse(sent['parallel_tool_calls'])
                    return httpx.Response(200,json=payload)
                def client_factory(**kwargs):
                    return AsyncOpenAI(**kwargs,api_key='fictional-mock-only',http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
                return asyncio.run(e.sdk_request(body,timeout,client_factory))
            try:
                inputs=json.loads((e.BROWSER/'evaluation/inputs.json').read_text())['cases'][0]
                result=e.investigate(bridge,inputs['goal'],'http://127.0.0.1:8096'+inputs['entry_path'],config,ledger,'scripted',fake)
                audit=bridge.call({'op':'close'},5)
                self.assertEqual(result['outcome'],'finished')
                self.assertFalse(result['result']['result']['execution_authorized'])
                self.assertEqual(len(ledger.value['calls']),3)
                self.assertTrue(audit['audit'])
                ledger.value['state']='completed';ledger.persist()
                evidence=e.ROOT/'runs/browser-investigation/bridge-smoke.json'
                e.save(evidence,{'label':'scripted fake transport and simulated usage; not model navigation evidence','result':result,'browser_audit':audit,'ledger':ledger.value})
            finally:bridge.close()
            self.assertIsNotNone(bridge.process.poll())
            print('Owned browser container removed; Docker client reaped; simulated calls=3')
