"""Real SQLAlchemy projection/derivation tests on a SQLite record mirror, not PostgreSQL."""
from datetime import datetime, timezone
import importlib.util
import unittest

AVAILABLE = importlib.util.find_spec('sqlalchemy') is not None
NOW = datetime(2026,10,14,tzinfo=timezone.utc)

@unittest.skipUnless(AVAILABLE, 'SQLAlchemy optional; run with commerce dependency profile')
class AdaptiveToolTests(unittest.TestCase):
    def setUp(self):
        import sqlalchemy as sa
        from decisionops.commerce import schema as db
        self.sa=sa; self.db=db
        self.engine=sa.create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        meta=sa.MetaData()
        # Only business tables, without PostgreSQL-only constraints or migrations.
        class UTCDateTime(sa.TypeDecorator):
            impl=sa.DateTime; cache_ok=True
            def process_result_value(self,value,dialect):
                return value.replace(tzinfo=timezone.utc) if value else None
        for table in (db.orders,db.order_lines,db.policies,db.payments,db.shipments,
                      db.shipment_lines,db.inventory,db.resolutions):
            sa.Table(table.name,meta,*(sa.Column(c.name,UTCDateTime() if isinstance(c.type,sa.DateTime) else c.type,
                     primary_key=c.primary_key) for c in table.columns))
        original_type=db.shipments.c.carrier_observed_at.type
        db.shipments.c.carrier_observed_at.type=UTCDateTime()
        self.addCleanup(setattr,db.shipments.c.carrier_observed_at,'type',original_type)
        meta.create_all(self.engine)
        self.c=self.engine.connect(); self.addCleanup(self.c.close)
        self.c.execute(db.orders.insert(),dict(id='O',store_id='store',policy_id='P',currency='USD',
                                             resolution_history_complete=True,compensation_revision=0))
        self.c.execute(db.order_lines.insert(),dict(order_id='O',variant_id='blue',quantity=1,unit_price_minor=2500))
        self.c.execute(db.policies.insert(),dict(id='P',store_id='store',version=1,allow_confirmed_loss=True,
                                               max_units=10,carrier_max_age_seconds=86400))
        self.c.execute(db.payments.insert(),dict(order_id='O',status='paid',amount_minor=2500,currency='USD'))
        self.c.execute(db.shipments.insert(),dict(id='S',order_id='O',fulfilment_status='shipped',
                                                carrier_status='lost',carrier_observed_at=NOW))
        self.c.execute(db.shipment_lines.insert(),dict(shipment_id='S',order_id='O',variant_id='blue',quantity=1))
        self.c.execute(db.inventory.insert(),dict(store_id='store',variant_id='blue',on_hand=3,reserved=1))
        self.queries=[]
        def capture(connection, clause, multiparams, params, options):
            if isinstance(clause,sa.sql.Select):
                self.queries.append(tuple((col.table.name,col.name) for col in clause.selected_columns))
        sa.event.listen(self.c,'before_execute',capture)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('decisionops.commerce.adaptive_tools'),
                             'Stage 1 selectable reads are not implemented')
        from decisionops.commerce import adaptive_tools as a
        from decisionops.commerce.adaptive_evidence import History
        from decisionops.commerce.read_tools import AssessmentRequest
        return a,History,AssessmentRequest

    def history(self, items=None, shipment='S', order='O'):
        a,H,R=self.api()
        return H({'order_id':order,'shipment_id':shipment,'items':items or {'blue':1}})

    def read(self,h,tool,**kw):
        a,H,R=self.api()
        result=a.read_tool(self.c,tool,R(**h.request),h,NOW,
                           dependencies=tuple(h.select(name,NOW) for name in a.DEPENDENCIES[tool]))
        h.append(result,**kw)
        return result

    def complete(self,h):
        for tool in ('order_manifest','replacement_policy','payment','fulfilment','carrier_loss',
                     'compensation_history','inventory'):
            if tool == 'carrier_loss' and (not h.active('fulfilment') or h.active('fulfilment')[-1].value is None):
                continue
            self.read(h,tool)
        return h.assess(NOW)

    def test_manifest_selects_only_declared_columns(self):
        h=self.history(); self.read(h,'order_manifest')
        self.assertEqual(self.queries,[tuple(('orders',c) for c in ('id','store_id','policy_id','currency')),
                                      tuple(('order_lines',c) for c in ('order_id','variant_id','quantity','unit_price_minor'))])
        self.assertIsNone(h.assess(NOW)['facts']['paid'])

    def test_each_tool_has_exact_query_projection(self):
        a,H,R=self.api(); h=self.history(); self.complete(h)
        expected_catalog = {
            'order_manifest': (('orders',('id','store_id','policy_id','currency')),
                               ('order_lines',('order_id','variant_id','quantity','unit_price_minor'))),
            'replacement_policy': (('policy_versions',('id','store_id','version','allow_confirmed_loss','max_units','carrier_max_age_seconds')),),
            'payment': (('payments',('order_id','status','amount_minor','currency')),),
            'fulfilment': (('shipments',('id','order_id','fulfilment_status')),
                           ('shipment_lines',('shipment_id','order_id','variant_id','quantity'))),
            'carrier_loss': (('shipments',('id','order_id','carrier_status','carrier_observed_at')),),
            'compensation_history': (('orders',('id','resolution_history_complete','compensation_revision')),
                                     ('resolutions',('id','order_id','variant_id','quantity','kind','operation_id'))),
            'inventory': (('inventory',('store_id','variant_id','on_hand','reserved')),),
        }
        for tool in expected_catalog:
            self.queries.clear(); a.read_tool(self.c,tool,R(**h.request),h,NOW,
                dependencies=tuple(h.select(name,NOW) for name in a.DEPENDENCIES[tool]))
            expected=[tuple((table,col) for col in columns) for table,columns in expected_catalog[tool]]
            # Wrong-order supporting lookup is conditional and absent on this eligible case.
            self.assertEqual(self.queries,expected,tool)

    def test_fulfilment_does_not_expose_carrier_records(self):
        h=self.history(); self.read(h,'order_manifest'); self.queries.clear()
        obs=self.read(h,'fulfilment')
        self.assertNotIn('carrier',str(obs.record()))
        self.assertFalse(any('carrier' in name for query in self.queries for table,name in query))
        self.assertIsNone(h.assess(NOW)['facts']['loss_confirmed'])

    def test_dependencies_checked_before_sql(self):
        a,H,R=self.api(); h=self.history()
        with self.assertRaises(ValueError): a.read_tool(self.c,'inventory',R(**h.request),h,NOW)
        self.assertEqual(self.queries,[])
        self.read(h,'order_manifest'); self.queries.clear()
        with self.assertRaises(ValueError): a.read_tool(self.c,'carrier_loss',R(**h.request),h,NOW)
        self.assertEqual(self.queries,[])

    def test_missing_payment_inventory_and_ship_lines_are_unknown(self):
        self.c.execute(self.db.payments.delete()); self.c.execute(self.db.inventory.delete())
        self.c.execute(self.db.shipment_lines.delete())
        result=self.complete(self.history())
        for fact in ('paid','stock_available','shipped'): self.assertIsNone(result['facts'][fact])
        self.assertEqual(result['decision']['status'],'needs_review')

    def test_incomplete_or_failed_history_cannot_prove_zero(self):
        self.c.execute(self.db.orders.update().values(resolution_history_complete=False))
        h=self.history(); self.read(h,'order_manifest'); obs=self.read(h,'compensation_history')
        self.assertIsNone(obs.value)
        self.assertIsNone(h.assess(NOW)['facts']['no_previous_compensation'])
        from sqlalchemy.exc import SQLAlchemyError
        def fail(*args): raise SQLAlchemyError('private connection diagnostic')
        self.sa.event.listen(self.c,'before_execute',fail)
        try:
            a,H,R=self.api(); failed=a.read_tool(self.c,'compensation_history',R(**h.request),h,NOW,dependencies=(h.select('order_manifest',NOW),))
        finally: self.sa.event.remove(self.c,'before_execute',fail)
        self.assertEqual(failed.record()['status'],'unavailable'); self.assertIsNone(failed.value)
        self.assertNotIn('private',str(failed.record()))

    def test_complete_supported_assessment_matches_bundled_and_v1_proposal(self):
        from decisionops.commerce.read_tools import read_assessment
        from decisionops.commerce.proposals import build_proposal,check_proposal
        a,H,R=self.api(); h=self.history(); adaptive=self.complete(h)
        legacy=read_assessment(self.c,R(**h.request),NOW)
        self.assertEqual(adaptive['facts'],legacy['facts'])
        self.assertEqual(adaptive['decision'],legacy['decision'])
        document=build_proposal(legacy)
        self.assertEqual(document['schema_version'],1)
        self.assertEqual(check_proposal(document,legacy)['status'],'valid_for_review')
        self.assertNotIn('read_tools',adaptive)
        self.c.execute(self.db.inventory.update().values(on_hand=4))
        changed=read_assessment(self.c,R(**h.request),NOW)
        self.assertEqual(check_proposal(document,changed)['status'],'requires_reinvestigation')

    def test_supported_blockers_and_unknown_tracking_match_bundled(self):
        from decisionops.commerce.read_tools import read_assessment
        a,H,R=self.api()
        for table,changes in ((self.db.inventory,{'on_hand':1,'reserved':1}),
                              (self.db.payments,{'status':'failed'}),
                              (self.db.shipments,{'carrier_status':'in_transit'}),
                              (self.db.policies,{'allow_confirmed_loss':False})):
            with self.subTest(table=table.name),self.c.begin_nested() as tx:
                self.c.execute(table.update().values(**changes)); h=self.history()
                adaptive=self.complete(h); legacy=read_assessment(self.c,R(**h.request),NOW)
                self.assertEqual(adaptive['facts'],legacy['facts'])
                self.assertEqual(adaptive['decision'],legacy['decision']); tx.rollback()

    def test_wrong_order_binding_discloses_no_other_carrier(self):
        self.c.execute(self.db.shipments.update().values(order_id='other'))
        h=self.history(); self.read(h,'order_manifest'); self.queries.clear()
        obs=self.read(h,'fulfilment')
        self.assertEqual(self.queries,[tuple(('shipments',col) for col in ('id','order_id','fulfilment_status')),
                                      (('shipments','order_id'),)])
        self.assertIsNone(obs.value); self.assertIn('shipment_order_mismatch',obs.record()['scope_reasons'])
        a,H,R=self.api(); self.queries.clear()
        with self.assertRaises(ValueError): a.read_tool(self.c,'carrier_loss',R(**h.request),h,NOW)
        self.assertEqual(self.queries,[])

    def test_partial_request_and_compensation_need_review(self):
        self.c.execute(self.db.order_lines.update().values(quantity=2))
        self.c.execute(self.db.shipment_lines.update().values(quantity=2))
        self.c.execute(self.db.payments.update().values(amount_minor=5000))
        self.c.execute(self.db.resolutions.insert(),dict(id='refund',order_id='O',variant_id='blue',quantity=1,kind='refund'))
        result=self.complete(self.history(items={'blue':2}))
        self.assertIn('partial_compensation',result['scope_reasons'])
        self.assertEqual(result['decision']['status'],'needs_review')
        h=self.history(); self.read(h,'order_manifest')
        self.assertIn('partial_request',h.assess(NOW)['scope_reasons'])

    def test_manifest_refresh_invalidates_dependents_without_reading_them(self):
        h=self.history(); first=self.read(h,'order_manifest'); self.read(h,'payment')
        self.c.execute(self.db.order_lines.update().values(unit_price_minor=2600)); self.queries.clear()
        self.read(h,'order_manifest',supersedes=first.id)
        result=h.assess(NOW)
        self.assertIsNone(result['facts']['paid']); self.assertEqual(len(h.observations),3)
        self.assertEqual({table for query in self.queries for table,col in query},{'orders','order_lines'})

    def test_record_identity_conflicts_never_choose_first(self):
        from unittest.mock import patch
        a,H,R=self.api(); h=self.history(); self.read(h,'order_manifest')
        original=a.projected_rows
        def conflicting(connection,table,columns,condition):
            rows=original(connection,table,columns,condition)
            if table is self.db.payments: rows += [{**rows[0],'status':'failed'}]
            return rows
        with patch.object(a,'projected_rows',side_effect=conflicting):
            obs=a.read_tool(self.c,'payment',R(**h.request),h,NOW,dependencies=(h.select('order_manifest',NOW),))
        self.assertIsNone(obs.value); self.assertEqual(obs.record()['reason'],'conflicting_records')

    def test_missing_manifest_cannot_establish_false_or_fetch_dependents(self):
        h=self.history(order='missing'); obs=self.read(h,'order_manifest')
        self.assertIsNone(obs.value)
        a,H,R=self.api(); self.queries.clear()
        with self.assertRaises(ValueError): a.read_tool(self.c,'payment',R(**h.request),h,NOW,dependencies=(h.select('order_manifest',NOW),))
        self.assertEqual(self.queries,[])

    def test_carrier_expiry_and_future_event_are_unknown(self):
        from datetime import timedelta
        for timestamp in (NOW-timedelta(days=2),NOW+timedelta(seconds=1)):
            with self.subTest(timestamp=timestamp):
                self.c.execute(self.db.shipments.update().values(carrier_observed_at=timestamp))
                h=self.history(); self.complete(h)
                self.assertIsNone(h.assess(NOW)['facts']['loss_confirmed'])

    def test_duplicate_resolutions_are_unknown_not_double_counted(self):
        from unittest.mock import patch
        a,H,R=self.api(); h=self.history(); self.read(h,'order_manifest')
        self.c.execute(self.db.resolutions.insert(),dict(id='refund',order_id='O',variant_id='blue',quantity=1,kind='refund'))
        original=a.projected_rows
        def duplicate(connection,table,columns,condition):
            rows=original(connection,table,columns,condition)
            return rows+rows if table is self.db.resolutions else rows
        with patch.object(a,'projected_rows',side_effect=duplicate):
            obs=a.read_tool(self.c,'compensation_history',R(**h.request),h,NOW,dependencies=(h.select('order_manifest',NOW),))
        self.assertIsNone(obs.value)
        self.assertEqual(obs.record()['reason'],'conflicting_records')

    def test_unavailable_tool_does_not_leak_partial_data(self):
        from sqlalchemy.exc import SQLAlchemyError
        def fail_resolution(connection,clause,*args):
            if isinstance(clause,self.sa.sql.Select) and any(col.table is self.db.resolutions for col in clause.selected_columns):
                raise SQLAlchemyError('private diagnostic')
        h=self.history(); self.read(h,'order_manifest')
        self.sa.event.listen(self.c,'before_execute',fail_resolution)
        try: obs=self.read(h,'compensation_history')
        finally: self.sa.event.remove(self.c,'before_execute',fail_resolution)
        self.assertEqual(obs.record()['payload'],{})
        self.assertEqual(obs.record()['status'],'unavailable')
        self.assertIsNone(h.assess(NOW)['facts']['no_previous_compensation'])

    def test_untrusted_stream_rejected_before_sql(self):
        a,H,R=self.api(); h=self.history(); self.read(h,'order_manifest'); self.queries.clear()
        with self.assertRaises(ValueError):
            a.read_tool(self.c,'inventory',R(**h.request),h,NOW,stream='untrusted')
        self.assertEqual(self.queries,[])

    def test_supported_state_matrix_agrees_with_bundled(self):
        from itertools import product
        from decisionops.commerce.read_tools import read_assessment
        a,H,R=self.api()
        for paid,lost,stock,policy,shipped,compensated in product((True,False),repeat=6):
            with self.subTest(state=(paid,lost,stock,policy,shipped,compensated)),self.c.begin_nested() as tx:
                self.c.execute(self.db.payments.update().values(status='paid' if paid else 'failed'))
                self.c.execute(self.db.shipments.update().values(carrier_status='lost' if lost else 'delivered',
                                                               fulfilment_status='shipped' if shipped else 'prepared'))
                self.c.execute(self.db.inventory.update().values(on_hand=3 if stock else 1,reserved=1))
                self.c.execute(self.db.policies.update().values(allow_confirmed_loss=policy))
                if compensated:
                    self.c.execute(self.db.resolutions.insert(),dict(id='resolution',order_id='O',variant_id='blue',quantity=1,kind='refund'))
                h=self.history(); adaptive=self.complete(h)
                legacy=read_assessment(self.c,R(**h.request),NOW)
                self.assertEqual(adaptive['facts'],legacy['facts'])
                self.assertEqual(adaptive['decision'],legacy['decision'])
                tx.rollback()

    def test_mutated_request_revalidated_before_sql(self):
        a,H,R=self.api(); request=R('O','S',{'blue':1})
        request.items['blue']=0
        h=H({'order_id':'O','shipment_id':'S','items':{'blue':0}})
        with self.assertRaises(ValueError): a.read_tool(self.c,'order_manifest',request,h,NOW)
        self.assertEqual(self.queries,[])

    def test_same_fact_conflicting_dependency_contents_cannot_remain_eligible(self):
        h=self.history(); self.complete(h)
        self.c.execute(self.db.order_lines.update().values(unit_price_minor=2600))
        self.read(h,'order_manifest')  # No explicit supersession: both contents remain active.
        self.assertIsNone(h.assess(NOW)['facts']['paid'])
        self.assertEqual(h.assess(NOW)['decision']['status'],'needs_review')
        with self.assertRaises(ValueError): h.select('order_manifest',NOW)
        self.assertEqual(len(h.observations),8)

    def test_tool_requires_explicit_dependency_objects_even_when_history_has_them(self):
        a,H,R=self.api(); h=self.history(); self.read(h,'order_manifest'); self.queries.clear()
        with self.assertRaises(ValueError): a.read_tool(self.c,'inventory',R(**h.request),h,NOW)
        self.assertEqual(self.queries,[])

    def test_leaf_content_conflict_is_unknown_even_if_both_values_agree(self):
        h=self.history(); self.complete(h)
        self.c.execute(self.db.inventory.update().values(on_hand=4))
        self.read(h,'inventory')  # Independent active content; do not select a newest winner.
        self.assertIsNone(h.assess(NOW)['facts']['stock_available'])
        self.assertEqual(h.assess(NOW)['decision']['status'],'needs_review')
        self.assertTrue(all(obs['value'] is None for obs in h.policy_view(NOW)['observations']
                            if obs['tool']=='inventory'))

if __name__=='__main__': unittest.main()
