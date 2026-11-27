"""Owned return requests and exact authorization against disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest

import test_commerce_adaptive_core as core


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class ReturnTests(unittest.TestCase):
    setUp = core.AdaptiveCoreTests.setUp
    cleanup = core.AdaptiveCoreTests.cleanup
    customer = ('camille', 'fictional-camille-phase2')
    other = ('alex', 'fictional-alex-phase2')
    manager = ('operator', 'fictional-manager-phase2')
    investigator = ('helper', 'fictional-helper-phase2')

    def fixture(self, clock=None):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        from decisionops.commerce.delivery_seed import seed
        from decisionops.commerce.portfolio_seed import seed as seed_portfolio
        seed(self.engine)
        seed_portfolio(self.engine)
        app = create_app(self.engine, username=self.manager[0], password=self.manager[1],
                         store_id='demo-store', demo_clock=clock, customer_accounts={
                             name: {'customer_id': name, 'password': password}
                             for name, password in (self.customer, self.other)
                         }, staff_accounts={
                             self.investigator[0]: {'password': self.investigator[1], 'role': 'staff'}
                         })
        client = TestClient(app)
        self.addCleanup(client.close)
        conversation = self.response(client.post('/customer-api/conversations', auth=self.customer, json={}))
        return client, '/customer-api/conversations/' + conversation['id']

    def response(self, response):
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def effects(self):
        with self.engine.connect() as connection:
            return [connection.exec_driver_sql(query).all() for query in (
                'SELECT * FROM inventory ORDER BY store_id, variant_id',
                'SELECT * FROM resolutions ORDER BY id',
                'SELECT * FROM commerce_replacement_orders ORDER BY id',
            )]

    def start(self, client, conversation, order='DEMO-ONTIME', variant='demo-tote'):
        return self.response(client.post(conversation + '/returns', auth=self.customer,
                                         json={'order_id': order, 'variant_id': variant}))

    def proposal(self, client, conversation):
        case = self.start(client, conversation)
        path = '/api/returns/' + case['id']
        proposal = self.response(client.post(path + '/investigate', auth=self.investigator, json={}))
        self.assertEqual(proposal['status'], 'proposed', proposal)
        return path, {'proposal_hash': proposal['proposal_hash']}

    def test_owned_eligibility_question_and_retry(self):
        client, conversation = self.fixture()
        order = {'order_id': 'DEMO-ONTIME'}
        before = self.response(client.get(conversation, auth=self.customer))
        result = self.response(client.get('/customer-api/returns/eligibility', auth=self.customer, params=order))
        self.assertEqual(result['items'][0]['variant_id'], 'demo-tote')
        self.assertEqual(self.response(client.get(conversation, auth=self.customer))['returns'], before['returns'])
        self.assertEqual(client.get('/customer-api/returns/eligibility', auth=self.other, params=order).status_code, 404)
        body = {**order, 'variant_id': 'demo-tote'}
        self.assertEqual(client.post(conversation + '/returns', auth=self.other, json=body).status_code, 404)
        first = self.start(client, conversation)
        self.assertEqual(self.start(client, conversation)['id'], first['id'])
        self.assertEqual(self.response(client.get(conversation, auth=self.customer))['returns'][0]['id'], first['id'])
        self.assertEqual(client.get('/api/returns/' + first['id'], auth=self.other).status_code, 401)

    def test_exact_approval_and_concurrent_confirmation_has_one_effect(self):
        client, conversation = self.fixture()
        effects = self.effects()
        path, body = self.proposal(client, conversation)
        self.assertEqual(client.post(path + '/confirm', auth=self.manager, json=body).status_code, 409)
        self.assertEqual(client.post(path + '/approve', auth=self.investigator, json=body).status_code, 403)
        self.assertEqual(client.post(path + '/approve', auth=self.manager,
                                     json={'proposal_hash': '0' * 64}).status_code, 409)
        approved = self.response(client.post(path + '/approve', auth=self.manager, json=body))
        self.assertEqual(approved['status'], 'approved')
        self.assertIsNone(approved['authorization_id'])
        self.assertEqual(client.post(path + '/confirm', auth=self.investigator, json=body).status_code, 403)
        def confirm(_):
            return self.response(client.post(path + '/confirm', auth=self.manager, json=body))
        with ThreadPoolExecutor(max_workers=2) as threads:
            a, b = threads.map(confirm, range(2))
        self.assertEqual(a['status'], 'authorized')
        self.assertTrue(a['authorization_id'])
        self.assertEqual(a['authorization_id'], b['authorization_id'])
        saved = self.response(client.get(conversation, auth=self.customer))['returns'][0]
        self.assertEqual(saved['authorization_id'], a['authorization_id'])
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT count(*) FROM commerce_return_authorizations').scalar_one(), 1)
        self.assertEqual(self.effects(), effects)
        prior = self.response(client.get('/customer-api/returns/eligibility', auth=self.customer, params={
            'order_id': 'DEMO-ONTIME', 'variant_id': 'demo-tote'}))
        self.assertEqual(prior['reason'], 'prior_return')

    def test_ineligible_lost_order_does_not_get_proposal(self):
        client, conversation = self.fixture()
        case = self.start(client, conversation, 'DEMO-LYON')
        path = '/api/returns/' + case['id']
        saved = self.response(client.post(path + '/investigate', auth=self.investigator, json={}))
        self.assertIn(saved['status'], ('review', 'ineligible'))
        self.assertIsNone(saved['proposal_hash'])

    def test_prior_return_and_policy_window_boundary(self):
        from datetime import timedelta
        now = [None]
        client, conversation = self.fixture(lambda: now[0])
        with self.engine.connect() as connection:
            delivered = connection.exec_driver_sql(
                "SELECT event_at FROM commerce_carrier_events WHERE shipment_id='PARCEL-DEMO-ONTIME' "
                "AND status='delivered'").scalar_one()
        now[0] = delivered + timedelta(days=30)
        path, body = self.proposal(client, conversation)
        self.assertEqual(self.response(client.post(path + '/approve', auth=self.manager, json=body))['status'], 'approved')
        now[0] += timedelta(microseconds=1)
        response = client.post(path + '/confirm', auth=self.manager, json=body)
        self.assertNotEqual(response.json().get('status'), 'authorized', response.text)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT count(*) FROM commerce_return_authorizations').scalar_one(), 0)

    def test_choices_and_expired_demo_order(self):
        client, conversation = self.fixture()
        path = '/customer-api/returns/eligibility'
        choices = self.response(client.get(path, auth=self.customer, params={'order_id': 'DEMO-RETURN'}))
        self.assertEqual({item['variant_id'] for item in choices['items']}, {'return-tote', 'return-final-sale'})
        self.assertEqual(choices['reason'], 'choose_item')
        self.assertEqual(self.response(client.get(conversation, auth=self.customer))['returns'], [])
        rejected = self.response(client.get(path, auth=self.customer, params={
            'order_id': 'DEMO-RETURN-EXPIRED', 'variant_id': 'return-tote'}))
        self.assertEqual(rejected['reason'], 'outside_window')
        final_sale = self.response(client.get(path, auth=self.customer, params={
            'order_id': 'DEMO-RETURN', 'variant_id': 'return-final-sale'}))
        self.assertEqual(final_sale['reason'], 'item_ineligible')

    def test_upgrade_0011_keeps_existing_delivery_and_customer_data(self):
        from alembic import command
        from alembic.config import Config
        from decisionops.commerce.schema_readiness import validate_readiness
        from pathlib import Path
        client, conversation = self.fixture()
        config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        with self.engine.begin() as connection:
            config.attributes['connection'] = connection
            command.downgrade(config, '0011')
            row = connection.exec_driver_sql(
                "SELECT id, store_id FROM orders WHERE id='DEMO-LYON'").one()
            command.upgrade(config, 'head')
            self.assertEqual(connection.exec_driver_sql(
                "SELECT id, store_id FROM orders WHERE id='DEMO-LYON'").one(), row)
            validate_readiness(connection)
        self.assertEqual(self.response(client.get(conversation, auth=self.customer))['returns'], [])

    def test_conflicting_evidence_after_approval_requires_staff_review(self):
        from datetime import datetime, timezone
        from decisionops.commerce.delivery import ingest_event

        client, conversation = self.fixture()
        path, body = self.proposal(client, conversation)
        self.response(client.post(path + '/approve', auth=self.manager, json=body))
        with self.engine.begin() as connection:
            ingest_event(connection, 'demo-store', 'PARCEL-DEMO-ONTIME', 'fixture',
                         'return-conflict', 'lost', datetime.now(timezone.utc), {'verified': True})
        client.post(path + '/confirm', auth=self.manager, json=body)
        state = self.response(client.get(path, auth=self.manager))
        self.assertEqual(state['status'], 'review', state)
        self.assertIsNone(state['authorization_id'])

    def test_prior_refund_disqualifies_the_exact_item(self):
        from decisionops.commerce import schema as db

        client, conversation = self.fixture()
        with self.engine.begin() as connection:
            connection.execute(db.resolutions.insert().values(
                id='phase2-existing-refund', order_id='DEMO-RETURN', variant_id='return-tote',
                quantity=1, kind='refund'))
        result = self.response(client.get('/customer-api/returns/eligibility', auth=self.customer, params={
            'order_id': 'DEMO-RETURN', 'variant_id': 'return-tote'}))
        self.assertEqual(result['reason'], 'prior_refund')
        self.assertEqual(self.response(client.get(conversation, auth=self.customer))['returns'], [])

    def test_chat_routes_to_eligibility_without_filing(self):
        client, conversation = self.fixture()

        def say(message, request_id):
            return self.response(client.post(conversation + '/messages', auth=self.customer, json={
                'message': message, 'request_id': request_id}))

        reply = say('Can I return an item from DEMO-RETURN?', 'return-question')
        self.assertEqual(reply['return_order_id'], 'DEMO-RETURN')
        conflict = say('Can I return something from DEMO-RETURN and PARCEL-DEMO-ONTIME?', 'return-conflict')
        self.assertEqual(conflict['intent'], 'clarify')
        self.assertNotIn('return_order_id', conflict)
        self.assertEqual(self.response(client.get(conversation, auth=self.customer))['returns'], [])

    def test_retry_from_new_conversation_identifies_the_original(self):
        client, conversation = self.fixture()
        case = self.start(client, conversation)
        another = self.response(client.post('/customer-api/conversations', auth=self.customer, json={}))
        replay = self.start(client, '/customer-api/conversations/' + another['id'])
        self.assertEqual(replay['id'], case['id'])
        self.assertEqual(replay['conversation_id'], conversation.rsplit('/', 1)[1])
        items = self.response(client.get(conversation, auth=self.customer))['returns']
        self.assertEqual([item['id'] for item in items], [case['id']])
