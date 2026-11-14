"""Opt-in PostgreSQL contracts in a disposable test schema, never the application schema."""
import os
import unittest
import test_commerce_postgres as postgres_fixture

NOW = postgres_fixture.NOW


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'PostgreSQL integration is opt-in')
class AdaptivePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the established test-only schema/migration/seed fixture, not a running app upgrade.
        postgres_fixture.PostgresTests.setUpClass.__func__(cls)

    @classmethod
    def cleanup_schema(cls):
        postgres_fixture.PostgresTests.cleanup_schema.__func__(cls)

    def setUp(self):
        postgres_fixture.PostgresTests.setUp(self)

    def history(self, order='ORD-1042', shipment='SHIP-1042', items=None, *, streams=('primary',)):
        from decisionops.commerce.adaptive_evidence import History
        return History(dict(order_id=order,shipment_id=shipment,items=items or {'shirt-blue-M':1}),streams=streams)

    def read(self, history, tool, *, stream='primary', supersedes=None):
        from decisionops.commerce.adaptive_tools import read_tool, DEPENDENCIES
        from decisionops.commerce.read_tools import AssessmentRequest
        result=read_tool(self.connection,tool,AssessmentRequest(**history.request),history,NOW,stream=stream,
                         dependencies=tuple(history.select(name,NOW) for name in DEPENDENCIES[tool]))
        history.append(result,supersedes=supersedes)
        return result

    def complete(self,history):
        for tool in ('order_manifest','replacement_policy','payment','fulfilment','carrier_loss',
                     'compensation_history','inventory'):
            self.read(history,tool)
        return history.assess(NOW)

    def test_seeded_supported_cases_agree_with_bundled(self):
        from decisionops.commerce.read_tools import AssessmentRequest, read_assessment
        for suffix,variant in (('1042','shirt-blue-M'),('STOCK','shirt-red-M'),('COMP','shirt-blue-M'),
                               ('TRACKING','shirt-blue-M'),('POLICY','shirt-blue-M')):
            with self.subTest(order=suffix):
                h=self.history('ORD-'+suffix,'SHIP-'+suffix,{variant:1})
                adaptive=self.complete(h)
                bundled=read_assessment(self.connection,AssessmentRequest(**h.request),NOW)
                self.assertEqual(adaptive['facts'],bundled['facts'])
                self.assertEqual(adaptive['decision'],bundled['decision'])

    def test_fulfilment_selects_only_explicit_columns(self):
        import sqlalchemy as sa
        h=self.history(); self.read(h,'order_manifest'); queries=[]
        def capture(connection,clause,*args):
            self.assertIsInstance(clause,sa.sql.Select)
            queries.append(tuple((col.table.name,col.name) for col in clause.selected_columns))
        sa.event.listen(self.connection,'before_execute',capture)
        try: obs=self.read(h,'fulfilment')
        finally: sa.event.remove(self.connection,'before_execute',capture)
        self.assertEqual(queries,[tuple(('shipments',name) for name in ('id','order_id','fulfilment_status')),
                                 tuple(('shipment_lines',name) for name in ('shipment_id','order_id','variant_id','quantity'))])
        self.assertNotIn('carrier',str(obs.record()))

    def test_incomplete_history_and_missing_payment_are_unknown(self):
        h=self.history('ORD-HISTORY','SHIP-HISTORY'); self.read(h,'order_manifest')
        self.assertIsNone(self.read(h,'compensation_history').value)
        import sqlalchemy as sa
        from decisionops.commerce import schema as db
        self.connection.execute(sa.delete(db.payments).where(db.payments.c.order_id=='ORD-HISTORY'))
        self.assertIsNone(self.read(h,'payment').value)

    def test_wrong_order_prevents_carrier_dispatch(self):
        from decisionops.commerce.adaptive_tools import read_tool, DEPENDENCIES
        from decisionops.commerce.read_tools import AssessmentRequest
        h=self.history(shipment='SHIP-STOCK'); self.read(h,'order_manifest')
        self.read(h,'replacement_policy'); fulfilment=self.read(h,'fulfilment')
        self.assertIsNone(fulfilment.value)
        with self.assertRaises(ValueError):
            read_tool(self.connection,'carrier_loss',AssessmentRequest(**h.request),h,NOW)

    def test_partial_scope_requires_review(self):
        for suffix in ('PARTIAL','PARTCOMP'):
            with self.subTest(order=suffix):
                h=self.history('ORD-'+suffix,'SHIP-'+suffix,{'shirt-blue-M':2})
                self.assertEqual(self.complete(h)['decision']['status'],'needs_review')

    def test_complete_empty_history_requires_authoritative_marker_and_success(self):
        import sqlalchemy as sa
        from decisionops.commerce import schema as db
        from decisionops.commerce.adaptive_tools import read_tool, DEPENDENCIES
        from decisionops.commerce.read_tools import AssessmentRequest
        h=self.history(); self.read(h,'order_manifest')
        complete=self.read(h,'compensation_history')
        self.assertTrue(complete.value)
        self.assertEqual(complete.record()['payload']['resolutions'],[])
        self.connection.execute(db.orders.update().where(db.orders.c.id=='ORD-1042').values(resolution_history_complete=False))
        self.assertIsNone(self.read(h,'compensation_history',supersedes=complete.id).value)
        def fail_history(connection,cursor,statement,*args):
            if 'FROM resolutions' in statement:
                connection.exec_driver_sql('SELECT 1/0')  # Actual PostgreSQL failure, isolated savepoint.
        with self.connection.begin_nested() as nested:
            sa.event.listen(self.connection,'before_cursor_execute',fail_history)
            try: failed=read_tool(self.connection,'compensation_history',AssessmentRequest(**h.request),h,NOW,
                                  dependencies=(h.select('order_manifest',NOW),))
            finally: sa.event.remove(self.connection,'before_cursor_execute',fail_history)
            self.assertEqual(failed.record()['status'],'unavailable')
            self.assertIsNone(failed.value); self.assertEqual(failed.record()['payload'],{})
            nested.rollback()

    def test_independent_conflict_survives_same_stream_refresh(self):
        from decisionops.commerce import schema as db
        h=self.history(streams=('primary','corroborating'))
        self.read(h,'order_manifest'); first=self.read(h,'payment')
        self.connection.execute(db.payments.update().where(db.payments.c.order_id=='ORD-1042').values(status='failed'))
        self.read(h,'payment',stream='corroborating')
        self.connection.execute(db.payments.update().where(db.payments.c.order_id=='ORD-1042').values(status='paid'))
        self.read(h,'payment',supersedes=first.id)
        self.assertIsNone(h.assess(NOW)['facts']['paid'])
        self.assertIn('contradictory',h.assess(NOW)['issues']['paid'])
        self.assertEqual(len(h.observations),4)

    def test_variant_quantity_and_store_binding(self):
        from decisionops.commerce import schema as db
        for items in ({'wrong-variant':1},{'shirt-blue-M':2}):
            with self.subTest(items=items):
                h=self.history(items=items)
                self.assertFalse(self.read(h,'order_manifest').value)
        self.connection.execute(db.inventory.update().where(db.inventory.c.variant_id=='shirt-blue-M').values(store_id='another-store'))
        h=self.history(); self.read(h,'order_manifest')
        self.assertIsNone(self.read(h,'inventory').value)

    def test_read_only_transaction_and_legacy_proposal_recheck(self):
        from decisionops.commerce.read_tools import read_assessment,AssessmentRequest
        from decisionops.commerce.proposals import build_proposal,check_proposal
        self.connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        h=self.history(); adaptive=self.complete(h)
        legacy=read_assessment(self.connection,AssessmentRequest(**h.request),NOW)
        self.assertEqual(adaptive['decision'],legacy['decision'])
        proposal=build_proposal(legacy)
        self.assertEqual(proposal['schema_version'],1)
        self.assertEqual(check_proposal(proposal,legacy)['status'],'valid_for_review')
        self.assertNotIn('read_tools',adaptive)

    def test_no_hidden_bundle_inventory_history_or_assembly_queries(self):
        import sqlalchemy as sa
        from unittest.mock import patch
        h=self.history(); tables=[]
        def capture(connection,clause,*args):
            self.assertIsInstance(clause,sa.sql.Select)
            tables.extend(col.table.name for col in clause.selected_columns)
        sa.event.listen(self.connection,'before_execute',capture)
        try:
            with patch('decisionops.commerce.read_tools.read_assessment',side_effect=AssertionError('hidden bundle')):
                self.read(h,'order_manifest'); self.read(h,'payment')
        finally: sa.event.remove(self.connection,'before_execute',capture)
        self.assertEqual(set(tables),{'orders','order_lines','payments'})
        def forbid(*args): self.fail('Observation assembly executed SQL')
        sa.event.listen(self.connection,'before_execute',forbid)
        try:
            self.assertIsNone(h.assess(NOW)['facts']['stock_available'])
            self.assertEqual(len(h.policy_view(NOW)['observations']),2)
        finally: sa.event.remove(self.connection,'before_execute',forbid)

if __name__=='__main__': unittest.main()
