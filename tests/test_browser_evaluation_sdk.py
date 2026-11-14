"""Optional locked SDK, fake HTTP only. Never calls an external endpoint."""
import asyncio
import json
import unittest
from scripts import browser_evaluation as e
try:
    import httpx2 as httpx
    from openai import AsyncOpenAI
except ImportError:
    httpx=AsyncOpenAI=None

@unittest.skipUnless(AsyncOpenAI,'locked commerce-api profile unavailable; no install attempted')
class BrowserSDKTests(unittest.TestCase):
    def test_actual_sdk_serialization_with_mock_transport(self):
        hits=[]
        async def handler(request):
            hits.append(request)
            return httpx.Response(200,json={'model':'gpt-6-luna','status':'completed','usage':{'input_tokens':10,'output_tokens':10},'output':[{'type':'function_call','name':'browser_action','call_id':'test_sdk','status':'completed','arguments':json.dumps({'action':'observe','url':None,'observation':None,'reference':None,'value':None,'result':None})}]})
        def factory(**kwargs):
            self.assertEqual(kwargs['max_retries'],0)
            return AsyncOpenAI(**kwargs,api_key='fictional-test-only',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        body=e.request_body(e.load_config(),{'goal':'fictional','observations':[]})
        result=asyncio.run(e.sdk_request(body,1,factory))
        self.assertEqual(e.parse_action(result,e.load_config())['action'],'observe')
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0].url.path,'/v1/responses')
        self.assertEqual(json.loads(hits[0].content)['tool_choice'],{'type':'function','name':'browser_action'})
        self.assertFalse(json.loads(hits[0].content)['parallel_tool_calls'])
        self.assertTrue(json.loads(hits[0].content)['tools'][0]['strict'])

    def test_observed_phased_messages_survive_sdk_but_are_rejected(self):
        from test_browser_protocol import observed_shape
        raw=observed_shape()
        hits=[]
        async def handler(request):
            hits.append(request)
            return httpx.Response(200,json=raw)
        def factory(**kwargs):return AsyncOpenAI(**kwargs,api_key='fictional-test-only',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        decoded=asyncio.run(e.sdk_request(e.request_body(e.load_config(),{}),1,factory))
        self.assertEqual(decoded,raw)
        self.assertEqual([o['phase'] for o in decoded['output']],['commentary','commentary','final_answer'])
        with self.assertRaisesRegex(ValueError,'Ambiguous'):e.parse_action(decoded,e.load_config())
        self.assertEqual(len(hits),1)

    def test_timeout_and_500_have_no_sdk_retries(self):
        for mode in ('timeout','500'):
            hits=[]
            async def handler(request):
                hits.append(request)
                if mode=='timeout':await asyncio.sleep(1)
                return httpx.Response(500,json={'error':{'message':'fictional server failure'}})
            def factory(**kwargs):return AsyncOpenAI(**kwargs,api_key='fictional-test-only',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            with self.subTest(mode=mode),self.assertRaises(Exception):asyncio.run(e.sdk_request(e.request_body(e.load_config(),{}),0.05,factory))
            self.assertEqual(len(hits),1)

    def test_streamed_response_overflow_is_bounded(self):
        class Output(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(100):yield b'x'*8192
        async def handler(request):return httpx.Response(200,stream=Output())
        def factory(**kwargs):return AsyncOpenAI(**kwargs,api_key='fictional-test-only',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with self.assertRaisesRegex(ValueError,'byte cap'):asyncio.run(e.sdk_request(e.request_body(e.load_config(),{}),1,factory))
