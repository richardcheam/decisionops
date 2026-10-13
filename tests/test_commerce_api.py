"""Authenticated store-bound API tests; fake staff with real isolated PostgreSQL."""
import os
import unittest
import test_commerce_execution as execution_fixtures


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'PostgreSQL integration is opt-in')
class APITests(unittest.TestCase):
    def setUp(self):
        execution_fixtures.ExecutionRaceTests.setUp(self)
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        self.client=TestClient(create_app(self.engine,password='test-password-16-chars',username='staff',origins={'http://testserver'}))
        self.client.auth=('staff','test-password-16-chars')
        self.addCleanup(self.client.close)
        with self.engine.begin() as connection:
            connection.exec_driver_sql('UPDATE shipments SET carrier_observed_at=clock_timestamp()')

    def cleanup_schema(self):
        execution_fixtures.ExecutionRaceTests.cleanup_schema(self)

    def open(self):
        result=self.client.post('/api/cases',json={'order_id':'ORD-1042','shipment_id':'SHIP-1042','items':{'shirt-blue-M':1}})
        self.assertEqual(result.status_code,201,result.text)
        return result.json()

    def test_authentication_and_json_origin_checks(self):
        self.assertEqual(self.client.get('/api/cases',auth=('bad','bad')).status_code,401)
        self.client.auth=None
        self.assertEqual(self.client.get('/api/cases').status_code,401)
        self.client.auth=('staff','test-password-16-chars')
        self.assertEqual(self.client.get('/api/session').json()['username'],'staff')
        self.assertEqual(self.client.post('/api/cases',json={'order_id':'ORD-1042','shipment_id':'SHIP-1042','items':{'shirt-blue-M':1}},headers={'Origin':'https://attacker.invalid'}).status_code,403)
        self.assertEqual(self.client.post('/api/cases',content='order=ORD-1042',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code,415)

    def test_strict_input_and_store_binding(self):
        self.assertEqual(self.client.post('/api/cases',json={'order_id':'ORD-1042','shipment_id':'SHIP-1042','items':{'shirt-blue-M':True}}).status_code,422)
        self.assertEqual(self.client.post('/api/cases',json={'order_id':'ORD-1042','shipment_id':'SHIP-1042','items':{'shirt-blue-M':1},'actor':'admin'}).status_code,422)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO policy_versions VALUES ('other-v1','other-store',1,true,10,86400)")
            connection.exec_driver_sql("INSERT INTO orders (id,store_id,policy_id,currency,resolution_history_complete) VALUES ('OTHER','other-store','other-v1','USD',true)")
        self.assertEqual(self.client.post('/api/cases',json={'order_id':'OTHER','shipment_id':'OTHER-SHIP','items':{'shirt-blue-M':1}}).status_code,404)
        orders=self.client.get('/api/orders').json()
        self.assertNotIn('OTHER',[row['id'] for row in orders])

    def test_async_investigation_bound_review_and_execution(self):
        from decisionops.commerce.worker import claim_one
        from decisionops.commerce.jobs import complete
        case=self.open()
        queued=self.client.post('/api/cases/'+case['id']+'/investigate',json={})
        self.assertEqual(queued.status_code,202,queued.text)
        claimed=claim_one(self.engine)
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection,connection.begin():
            complete(connection,claimed['id'],claimed['token'])
        case=self.client.get('/api/cases/'+case['id']).json()
        body={'generation':case['generation'],'proposal_id':case['proposal']['id'],'content_hash':case['proposal']['content_hash'],'decision':'approve'}
        wrong=dict(body,content_hash='0'*64)
        self.assertEqual(self.client.post('/api/cases/'+case['id']+'/review',json=wrong).status_code,409)
        approved=self.client.post('/api/cases/'+case['id']+'/review',json=body)
        self.assertEqual(approved.status_code,200,approved.text)
        operation=approved.json()['approval']['operation_id']
        self.assertEqual(approved.json()['approval']['actor'],'staff')
        queued=self.client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':operation})
        self.assertEqual(queued.status_code,202,queued.text)
        claimed=claim_one(self.engine)
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection,connection.begin():
            complete(connection,claimed['id'],claimed['token'])
        shown=self.client.get('/api/cases/'+case['id']).json()
        self.assertEqual(shown['status'],'executed')
        self.assertEqual(shown['operation']['status'],'verified')
        self.assertNotIn('token',self.client.get('/api/jobs/'+queued.json()['id']).json())

    def test_failed_database_is_unavailable_not_empty_inbox(self):
        from unittest.mock import patch
        from sqlalchemy.exc import OperationalError
        with patch.object(self.engine,'connect',side_effect=OperationalError('secret',{},Exception('secret'))):
            result=self.client.get('/api/cases')
        self.assertEqual(result.status_code,503)
        self.assertNotIn('secret',result.text)

    def test_secret_required_before_server_start(self):
        from decisionops.commerce.api import create_app
        with self.assertRaises(ValueError):
            create_app(self.engine,password='short')
