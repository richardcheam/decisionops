"""Local model protocol, strict routing and persisted specialist integration."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch

import test_commerce_adaptive_core as core


@contextmanager
def model_server(choose):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            answer = choose(self.path, payload)
            response = json.dumps({'message': {'content': json.dumps(answer)}, 'done': True}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield {'COMMERCE_LLM_MODEL': 'local-test:latest',
                   'COMMERCE_OLLAMA_URL': f'http://127.0.0.1:{server.server_port}'}
        finally:
            server.shutdown()
            thread.join()


class LocalModelTests(unittest.TestCase):
    def test_only_explicit_local_model_endpoint_is_accepted(self):
        from decisionops.commerce.local_llm import LocalModel
        for endpoint in ('https://example.invalid', 'http://127.0.0.1.evil.invalid',
                         'http://127.0.0.1@remote.invalid:11434', 'http://localhost:11434/api/chat'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                LocalModel('local-test', endpoint)
        with self.assertRaises(ValueError):
            LocalModel('some-model:cloud', 'http://ollama:11434')

    def test_chat_uses_model_choice_and_invalid_output_never_falls_back(self):
        from decisionops.commerce.local_llm import LocalModel
        from decisionops.commerce.role_actions import ModelActionAdapter, ModelUnavailable
        requests = []

        def choose(path, payload):
            requests.append((path, payload))
            return {'kind': 'overdue' if len(requests) == 1 else 'approve'}

        with model_server(choose) as env, patch.dict(os.environ, env):
            router = ModelActionAdapter(LocalModel.from_environment().route, fallback=False).staff()
            self.assertEqual(router.choose('What can you help me?').kind, 'overdue')
            with self.assertRaises(ModelUnavailable):
                router.choose('How many deliveries this week?')
        self.assertEqual(requests[0][0], '/api/chat')
        self.assertFalse(requests[0][1]['stream'])
        self.assertIn('overdue', requests[0][1]['format']['properties']['kind']['enum'])


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class LLMFlowTests(unittest.TestCase):
    setUp = core.AdaptiveCoreTests.setUp
    cleanup = core.AdaptiveCoreTests.cleanup

    def fixture(self):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        from decisionops.commerce.portfolio_seed import seed
        seed(self.engine)
        return TestClient(create_app(self.engine, username='operator', password='fictional-staff-llm-only',
                                    staff_investigation_mode='llm',
                                    customer_accounts={'camille': {'password': 'fictional-customer-llm-only',
                                                                   'customer_id': 'camille'}}))

    def test_normal_api_and_worker_use_model_choices_without_giving_it_write_authority(self):
        from decisionops.commerce import adaptive_investigations, staff_investigations
        requests = []

        def choose(path, payload):
            prompt = json.loads(payload['messages'][-1]['content'])
            requests.append(prompt)
            if 'message' in prompt:
                choices = {'What can you help me?': 'refund_help', 'Please handle the Lyon delivery': 'investigate',
                           'How do I report this parcel missing?': 'report_nonreceipt'}
                return {'kind': choices[prompt['message']]}
            return {'index': next(i for i, action in enumerate(prompt['allowed_actions']) if action['kind'] == 'read')}

        customer = ('camille', 'fictional-customer-llm-only')
        staff = ('operator', 'fictional-staff-llm-only')
        with model_server(choose) as env, patch.dict(os.environ, env), self.fixture() as client:
            customer_chat = client.post('/customer-api/conversations', auth=customer, json={}).json()['id']
            path = '/customer-api/conversations/' + customer_chat
            response = client.post(path + '/messages', auth=customer,
                                   json={'message': 'What can you help me?', 'request_id': 'customer-help'})
            self.assertEqual(response.json()['intent'], 'refund_help')
            client.post(path + '/select', auth=customer, json={'order_id': 'DEMO-LYON', 'shipment_id': 'PARCEL-DEMO-LYON'})
            response = client.post(path + '/messages', auth=customer,
                                   json={'message': 'How do I report this parcel missing?', 'request_id': 'not-consent'})
            self.assertEqual(response.json()['intent'], 'clarify')
            self.assertNotIn('case_id', response.json())
            rows = client.get('/api/exceptions', auth=staff).json()
            lyon = next(row['case_id'] for row in rows if row['order_id'] == 'DEMO-LYON')
            chat = client.post('/api/conversations', auth=staff, json={}).json()['id']
            path = '/api/conversations/' + chat
            client.post(path + '/select', auth=staff, json={'case_id': lyon})
            response = client.post(path + '/messages', auth=staff,
                                   json={'message': 'Please handle the Lyon delivery', 'request_id': 'start'})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = response.json()['investigation']['id']
            result = staff_investigations.work_once(self.engine)
            self.assertEqual(result['run_id'], run_id)
            self.assertEqual(result['state'], 'proposed')
            run = adaptive_investigations.inspect(self.engine, run_id)
            self.assertEqual(run['contracts']['specialist_model'], 'local-test:latest')
            details = client.get('/api/cases/' + lyon, auth=staff).json()
            self.assertEqual(details['shipment_investigation']['mode'], 'llm')
            self.assertIsNotNone(details['proposal'])
            self.assertIsNone(details['approval'])
            self.assertIsNone(details['operation'])
        self.assertEqual({p['specialist'] for p in requests if 'specialist' in p}, {'order', 'shipment'})

    def test_invalid_chat_output_is_unavailable_and_invalid_specialists_require_review(self):
        customer = ('camille', 'fictional-customer-llm-only')
        staff = ('operator', 'fictional-staff-llm-only')
        with model_server(lambda *_: {'kind': 'execute'}) as env, patch.dict(os.environ, env), self.fixture() as client:
            chat = client.post('/customer-api/conversations', auth=customer, json={}).json()['id']
            result = client.post(f'/customer-api/conversations/{chat}/messages', auth=customer,
                                 json={'message': 'What can you help me?', 'request_id': 'unavailable'})
            self.assertEqual(result.status_code, 503)
            case = next(row for row in client.get('/api/exceptions', auth=staff).json() if row['order_id'] == 'DEMO-LYON')
            path = '/api/cases/' + case['case_id']
            started = client.post(path + '/investigate', auth=staff, json={})
            self.assertEqual(started.status_code, 202, started.text)
            from decisionops.commerce.staff_investigations import work_once
            self.assertEqual(work_once(self.engine)['state'], 'review')
            self.assertIsNone(client.get(path, auth=staff).json()['proposal'])
