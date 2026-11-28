"""Staff-only image relinking against disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest

import test_commerce_adaptive_core as core


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class CatalogTests(unittest.TestCase):
    setUp = core.AdaptiveCoreTests.setUp
    cleanup = core.AdaptiveCoreTests.cleanup
    manager = ('operator', 'fictional-manager-catalog')
    investigator = ('helper', 'fictional-helper-catalog')
    customer = ('camille', 'fictional-camille-catalog')
    wrong = '/api/catalog/TOTE-BLUE'

    def fixture(self, *, store='demo-store'):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        from decisionops.commerce.portfolio_seed import seed

        seed(self.engine)
        app = create_app(self.engine, username=self.manager[0], password=self.manager[1],
                         store_id=store, customer_accounts={
                             self.customer[0]: {'customer_id': self.customer[0], 'password': self.customer[1]},
                         }, staff_accounts={
                             self.investigator[0]: {'password': self.investigator[1], 'role': 'staff'},
                         })
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def response(self, response):
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def listing(self):
        with self.engine.connect() as c:
            return tuple(c.exec_driver_sql(
                "SELECT current_image_id, version FROM commerce_catalog_listings "
                "WHERE store_id='demo-store' AND sku='TOTE-BLUE'").one())

    def proposed(self, client):
        row = self.response(client.post(self.wrong + '/investigate', auth=self.investigator, json={}))
        self.assertEqual(row['status'], 'proposed')
        self.assertEqual((row['current_image_id'], row['proposed_image_id']), ('tote-red', 'tote-blue'))
        return {'proposal_hash': row['proposal_hash']}

    def test_store_staff_and_mutation_roles_are_checked(self):
        client = self.fixture()
        for path in ('/api/catalog', self.wrong, self.wrong + '/images/tote-red'):
            self.assertEqual(client.get(path, auth=self.customer).status_code, 401)
        other_store = self.fixture(store='different-store')
        self.assertEqual(other_store.get(self.wrong, auth=self.manager).status_code, 404)
        self.assertEqual(other_store.get(self.wrong + '/images/tote-red', auth=self.manager).status_code, 404)
        image = client.get(self.wrong + '/images/tote-red', auth=self.investigator)
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers['content-type'], 'image/png')
        self.assertTrue(image.content.startswith(b'\x89PNG'))
        body = self.proposed(client)
        for action in ('approve', 'confirm'):
            self.assertEqual(client.post(self.wrong + '/' + action, auth=self.investigator, json=body).status_code, 403)

    def test_exact_confirmation_is_idempotent_under_concurrency(self):
        client = self.fixture()
        before = self.listing()
        body = self.proposed(client)
        self.assertEqual(client.post(self.wrong + '/confirm', auth=self.manager, json=body).status_code, 409)
        self.assertEqual(client.post(self.wrong + '/approve', auth=self.manager,
                                     json={'proposal_hash': '0' * 64}).status_code, 409)
        approval = self.response(client.post(self.wrong + '/approve', auth=self.manager, json=body))
        self.assertEqual(approval['status'], 'approved')
        self.assertEqual(self.listing(), before)

        def confirm(_):
            return self.response(client.post(self.wrong + '/confirm', auth=self.manager, json=body))

        with ThreadPoolExecutor(max_workers=2) as threads:
            first, second = threads.map(confirm, range(2))
        self.assertEqual(first['status'], 'confirmed')
        self.assertTrue(first['receipt'])
        self.assertEqual(first['receipt'], second['receipt'])
        self.assertEqual(self.listing(), ('tote-blue', before[1] + 1))
        with self.engine.connect() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_catalog_relinks').scalar_one(), 1)

    def test_changed_version_and_conflicting_evidence_leave_image_unchanged(self):
        client = self.fixture()
        original = self.listing()
        body = self.proposed(client)
        self.response(client.post(self.wrong + '/approve', auth=self.manager, json=body))
        with self.engine.begin() as c:
            c.exec_driver_sql("UPDATE commerce_catalog_listings SET version = version + 1 WHERE sku = 'TOTE-BLUE'")
        client.post(self.wrong + '/confirm', auth=self.manager, json=body)
        row = self.response(client.get(self.wrong, auth=self.manager))
        self.assertEqual(row['status'], 'review')
        self.assertEqual(self.listing()[0], original[0])
        for sku, expected in (('TOTE-SLATE', 'current'), ('MUG-WHITE', 'review')):
            row = self.response(client.post('/api/catalog/' + sku + '/investigate', auth=self.manager, json={}))
            self.assertEqual(row['status'], expected, row)
            self.assertIsNone(row['proposal_hash'])
        with self.engine.connect() as c:
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_catalog_relinks').scalar_one(), 0)

    def test_supplier_disagreement_after_approval_without_version_change(self):
        client = self.fixture()
        before = self.listing()
        body = self.proposed(client)
        self.response(client.post(self.wrong + '/approve', auth=self.manager, json=body))
        with self.engine.begin() as c:
            c.exec_driver_sql(
                "UPDATE commerce_catalog_listings SET supplier_record = "
                "jsonb_set(supplier_record, '{image_id}', to_jsonb('tote-red'::text)) "
                "WHERE store_id='demo-store' AND sku='TOTE-BLUE'")
        client.post(self.wrong + '/confirm', auth=self.manager, json=body)
        row = self.response(client.get(self.wrong, auth=self.manager))
        self.assertEqual(row['status'], 'review')
        self.assertIsNone(row['receipt'])
        self.assertEqual(self.listing(), before)

    def test_upgrade_from_0012_preserves_customer_returns_and_delivery(self):
        from alembic import command
        from alembic.config import Config
        from decisionops.commerce.schema_readiness import validate_readiness
        from pathlib import Path

        client = self.fixture()
        conversation = self.response(client.post('/customer-api/conversations', auth=self.customer, json={}))
        request = self.response(client.post('/customer-api/conversations/' + conversation['id'] + '/returns',
            auth=self.customer, json={'order_id': 'DEMO-RETURN', 'variant_id': 'return-tote'}))
        path = '/api/returns/' + request['id']
        proposal = self.response(client.post(path + '/investigate', auth=self.investigator, json={}))
        body = {'proposal_hash': proposal['proposal_hash']}
        self.response(client.post(path + '/approve', auth=self.manager, json=body))
        authorized = self.response(client.post(path + '/confirm', auth=self.manager, json=body))
        self.assertEqual(authorized['status'], 'authorized')
        config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        with self.engine.begin() as c:
            config.attributes['connection'] = c
            command.downgrade(config, '0012')
            orders = c.exec_driver_sql('SELECT id, store_id FROM orders ORDER BY id').all()
            command.upgrade(config, 'head')
            self.assertEqual(c.exec_driver_sql('SELECT id, store_id FROM orders ORDER BY id').all(), orders)
            self.assertEqual(c.exec_driver_sql('SELECT id FROM commerce_return_authorizations').scalar_one(),
                             authorized['authorization_id'])
            validate_readiness(c)
