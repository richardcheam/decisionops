"""The pilot has separate users, tenant memberships and browser sessions."""
import os
from pathlib import Path
from unittest import TestCase, skipUnless
from uuid import uuid4


class PilotIdentityFixture:

    origin = 'https://pilot.example.test'
    headers = {'Origin': origin}
    manager = {'email': 'manager-a@example.test', 'password': 'fictional-manager-a-password'}
    other = {'email': 'manager-b@example.test', 'password': 'fictional-manager-b-password'}

    def setUp(self):
        from alembic import command
        from alembic.config import Config
        from fastapi import Depends, FastAPI
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        from decisionops.commerce.pilot_identity import bootstrap, install_identity

        admin = database_engine(os.environ['COMMERCE_TEST_DATABASE_URL'])
        namespace = 'pilot_identity_' + uuid4().hex
        with admin.begin() as connection:
            connection.exec_driver_sql('CREATE SCHEMA ' + namespace)
        def cleanup():
            self.engine.dispose()
            with admin.begin() as connection:
                connection.exec_driver_sql('DROP SCHEMA ' + namespace + ' CASCADE')
            admin.dispose()
        self.addCleanup(cleanup)
        test_url = make_url(os.environ['COMMERCE_TEST_DATABASE_URL']).update_query_dict(
            {'options': '-c search_path=' + namespace})
        self.engine = database_engine(test_url)
        config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        with self.engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        bootstrap(self.engine, 'shop-a', 'First fictional shop', **self.manager)
        bootstrap(self.engine, 'shop-b', 'Second fictional shop', **self.other)

        self.app = FastAPI()
        self.identity = install_identity(self.app, self.engine, origin=self.origin)

        @self.app.get('/pilot-api/stores/{store_id}/probe')
        def probe(principal=Depends(self.identity.staff)):
            return {'store_id': principal.store_id, 'role': principal.role}

        @self.app.post('/pilot-api/stores/{store_id}/approve-probe')
        def approve_probe(principal=Depends(self.identity.approver)):
            return {'store_id': principal.store_id}

    def client(self):
        from fastapi.testclient import TestClient

        client = TestClient(self.app, base_url=self.origin)
        self.addCleanup(client.close)
        return client

    def login(self, client, account=None):
        return client.post('/pilot-api/login', json=account or self.manager, headers=self.headers)

    def invite(self, manager, email='support@example.test'):
        response = manager.post('/pilot-api/stores/shop-a/invites',
                                json={'email': email, 'role': 'staff'}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['token']

    def accept(self, client, token, password='fictional-support-password'):
        return client.post('/pilot-api/invites/accept',
                           json={'token': token, 'password': password}, headers=self.headers)

@skipUnless(os.environ.get("COMMERCE_TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class PilotIdentityTests(PilotIdentityFixture, TestCase):
    def test_hosted_sign_in_requires_origin_and_uses_revocable_secure_cookie(self):
        client = self.client()
        self.assertEqual(client.get('/pilot-api/session').status_code, 401)
        self.assertEqual(client.post('/pilot-api/login', json=self.manager).status_code, 403)
        self.assertEqual(self.login(client, dict(self.manager, password='fictional-wrong-password')).status_code, 401)
        response = self.login(client)
        self.assertEqual(response.status_code, 200, response.text)
        cookie = response.headers['set-cookie'].lower()
        for attribute in ('__host-decisionops-pilot=', 'httponly', 'secure', 'samesite=lax', 'path=/'):
            self.assertIn(attribute, cookie)
        self.assertEqual(client.get('/pilot-api/session').json()['stores'], [
            {'id': 'shop-a', 'name': 'First fictional shop', 'role': 'approver'}])
        old_cookie = client.cookies.get(self.identity.cookie)
        self.assertEqual(client.post('/pilot-api/logout', json={}, headers=self.headers).status_code, 200)
        attacker = self.client()
        self.assertEqual(attacker.get('/pilot-api/session', headers={
            'Cookie': f'{self.identity.cookie}={old_cookie}'}).status_code, 401)

    def test_tenant_membership_and_approver_role_checked_by_server(self):
        manager, support = self.client(), self.client()
        self.assertEqual(self.login(manager).status_code, 200)
        self.assertEqual(manager.get('/pilot-api/stores/shop-b/probe').status_code, 404)
        self.assertEqual(manager.post('/pilot-api/stores/shop-b/approve-probe',
                                      json={}, headers=self.headers).status_code, 404)
        token = self.invite(manager)
        self.assertEqual(self.accept(support, token).status_code, 200)
        self.assertEqual(support.get('/pilot-api/stores/shop-a/probe').json()['role'], 'staff')
        self.assertEqual(support.get('/pilot-api/stores/shop-b/probe').status_code, 404)
        self.assertEqual(support.post('/pilot-api/stores/shop-a/approve-probe',
                                      json={}, headers=self.headers).status_code, 403)
        self.assertEqual(self.accept(self.client(), token).status_code, 404)

    def test_invite_to_existing_account_cannot_change_password_or_role(self):
        manager, other, stranger = self.client(), self.client(), self.client()
        self.assertEqual(self.login(manager).status_code, 200)
        token = self.invite(manager, self.other['email'])
        self.assertEqual(self.accept(stranger, token).status_code, 409)
        self.assertEqual(self.login(other, self.other).status_code, 200)
        response = self.accept(other, token, '')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([row['role'] for row in response.json()['stores']], ['staff', 'approver'])
        self.assertEqual(self.login(self.client(), self.other).status_code, 200)

    def test_login_attempts_remain_bounded_across_clients(self):
        for _ in range(10):
            self.assertEqual(self.login(self.client(), dict(self.manager, password='wrong')).status_code, 401)
        self.assertEqual(self.login(self.client()).status_code, 429)

    def test_concurrent_invite_acceptance_creates_one_member(self):
        from concurrent.futures import ThreadPoolExecutor

        manager = self.client()
        self.assertEqual(self.login(manager).status_code, 200)
        token = self.invite(manager)
        recipients = [self.client(), self.client()]
        with ThreadPoolExecutor(max_workers=2) as threads:
            results = list(threads.map(lambda recipient: self.accept(recipient, token), recipients))
        self.assertEqual(sorted(response.status_code for response in results), [200, 404])
        with self.engine.connect() as connection:
            member_count = connection.exec_driver_sql(
                "SELECT count(*) FROM commerce_pilot_memberships WHERE store_id='shop-a'"
            ).scalar_one()
        self.assertEqual(member_count, 2)
