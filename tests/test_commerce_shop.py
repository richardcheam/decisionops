"""Opt-in fictional customer projection; real isolated PostgreSQL, no browser agent."""
import os,unittest
from unittest.mock import patch
import test_commerce_adaptive_core as core
@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'Requires isolated shop PostgreSQL')
class ShopFixtureTests(unittest.TestCase):
    setUp=core.AdaptiveCoreTests.setUp
    cleanup=core.AdaptiveCoreTests.cleanup
    def client(self,enabled=True,store='demo-store'):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        return TestClient(create_app(self.engine,password='fictional-test-password',store_id=store,storefront_fixture=enabled))
    def test_disabled_by_default_and_wrong_store_denied(self):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        with patch.dict(os.environ,{'COMMERCE_STOREFRONT_FIXTURE':'0'}):
            self.assertEqual(TestClient(create_app(self.engine,password='fictional-test-password')).get('/demo-shop/orders').status_code,404)
        self.assertEqual(self.client(store='another-store').get('/demo-shop/orders').status_code,404)
    def test_projection_uses_only_customer_records(self):
        from sqlalchemy import event
        statements=[]
        def observe(c,cursor,statement,parameters,context,executemany):statements.append(statement.lower())
        event.listen(self.engine,'before_cursor_execute',observe)
        try:r=self.client().get('/demo-shop/orders')
        finally:event.remove(self.engine,'before_cursor_execute',observe)
        self.assertEqual(r.status_code,200,r.text)
        rows=r.json();self.assertEqual({r['id'] for r in rows},{'ORD-1042','ORD-TRACKING','ORD-HISTORY'})
        for private in ('inventory','resolutions','policy_versions','resolution_history_complete','policy_id'):
            self.assertFalse(any(private in statement for statement in statements),private)
            self.assertNotIn(private,r.text)
        item=next(x for x in rows if x['id']=='ORD-1042')
        self.assertEqual(item['lines'][0]['variant_id'],'shirt-blue-M')
        self.assertIsNone(item['shipment'])
        detail=self.client().get('/demo-shop/orders/ORD-1042').json()
        self.assertNotIn('carrier_status',detail['shipment'])
        tracking=self.client().get('/demo-shop/orders/ORD-1042/tracking').json()
        self.assertEqual(tracking['shipment']['carrier_status'],'lost')
    def test_unlisted_order_and_writes_are_rejected(self):
        client=self.client()
        self.assertEqual(client.get('/demo-shop/orders/ORD-COMP').status_code,404)
        for method in ('post','delete','patch'):
            self.assertEqual(client.request(method,'/demo-shop/orders/ORD-1042',json={}).status_code,405)
    def test_missing_shipment_is_unknown_not_invented(self):
        with self.engine.begin() as c:c.exec_driver_sql("DELETE FROM shipment_lines WHERE shipment_id='SHIP-1042'; DELETE FROM shipments WHERE id='SHIP-1042'")
        r=self.client().get('/demo-shop/orders/ORD-1042');self.assertEqual(r.status_code,200)
        self.assertIsNone(r.json()['shipment'])
    def test_fixture_seed_refuses_other_database_before_writes(self):
        from decisionops.commerce.shop_fixture import require_fixture_database
        with self.engine.connect() as c:
            # This test DB is admitted; the identity guard itself is explicit.
            require_fixture_database(c)
            with patch.object(c,'exec_driver_sql') as execute:
                execute.return_value.one.return_value=('commerce','commerce')
                with self.assertRaises(ValueError):require_fixture_database(c)
    def test_wrong_order_shipment_is_not_disclosed(self):
        with self.engine.begin() as c:
            c.exec_driver_sql("DELETE FROM shipment_lines WHERE shipment_id='SHIP-1042'")
            c.exec_driver_sql("UPDATE shipments SET order_id='ORD-TRACKING' WHERE id='SHIP-1042'")
        r=self.client().get('/demo-shop/orders/ORD-1042/tracking')
        self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['shipment'])
    def test_stale_tracking_reviews_with_truthful_record_provenance(self):
        from decisionops.commerce.cases import open_case
        from decisionops.commerce.read_tools import AssessmentRequest
        from decisionops.commerce.staff_investigations import work_once
        with self.engine.begin() as c:
            c.exec_driver_sql("UPDATE shipments SET carrier_observed_at=clock_timestamp()-interval '3 days' WHERE id='SHIP-TRACKING'")
            case=open_case(c,AssessmentRequest('ORD-TRACKING','SHIP-TRACKING',{'shirt-blue-M':1}))
        client=self.client();client.auth=('operator','fictional-test-password')
        started=client.post('/api/cases/'+case['id']+'/shipment-investigation',json={'report':'Please investigate the old shipment update','request_id':'SHOP-STALE','expected_generation':0})
        self.assertEqual(started.status_code,202,started.text);work_once(self.engine)
        saved=client.get('/api/cases/'+case['id']).json()
        self.assertIsNone(saved['proposal']);self.assertIsNone(saved['assessment']['facts']['loss_confirmed'])
        carrier=next(e for e in saved['shipment_investigation']['evidence'] if e['tool']=='carrier_loss')
        self.assertEqual(carrier['source']['kind'],'database_read');self.assertEqual(carrier['source']['tables'],['shipments'])
        self.assertEqual(carrier['source']['order_id'],'ORD-TRACKING');self.assertEqual(len(carrier['source']['version']),64)
        self.assertEqual(carrier['customer_page'],'/shop/account/orders/ORD-TRACKING/tracking')
    def test_mismatched_shipment_cannot_link_to_other_tracking_page(self):
        from decisionops.commerce.cases import open_case
        from decisionops.commerce.read_tools import AssessmentRequest
        from decisionops.commerce.staff_investigations import work_once
        with self.engine.begin() as c:case=open_case(c,AssessmentRequest('ORD-1042','SHIP-TRACKING',{'shirt-blue-M':1}))
        client=self.client();client.auth=('operator','fictional-test-password')
        r=client.post('/api/cases/'+case['id']+'/shipment-investigation',json={'report':'Check the supplied shipment binding','request_id':'WRONG-SHIP','expected_generation':0})
        self.assertEqual(r.status_code,202);work_once(self.engine)
        evidence=client.get('/api/cases/'+case['id']).json()['shipment_investigation']['evidence']
        shipment=[e for e in evidence if e['tool'] in ('fulfilment','carrier_loss')]
        self.assertTrue(shipment)
        self.assertTrue(all('customer_page' not in e for e in shipment))
    def test_seed_entry_point_refuses_wrong_database_before_seed(self):
        from unittest.mock import MagicMock
        from decisionops.commerce.shop_fixture import main
        engine=MagicMock();engine.connect.return_value.__enter__.return_value.exec_driver_sql.return_value.one.return_value=('commerce','commerce')
        with patch('decisionops.commerce.database.database_engine',return_value=engine),patch('decisionops.commerce.seed.seed') as seed:
            with self.assertRaises(ValueError):main()
            seed.assert_not_called();engine.begin.assert_not_called();engine.dispose.assert_called_once()
