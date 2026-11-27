"""Add delivered fictional return orders without altering the delivery queue."""

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from . import schema as db
from .cases import clock
from .delivery import _lock, aware, ingest_event

STORE = 'demo-store'
SEED_VERSION = 'commerce-return-demo-v1'


def seed(engine, now=None):
    with engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
        _lock(c, STORE)
        if c.execute(sa.select(db.seed_versions.c.id).where(db.seed_versions.c.id == SEED_VERSION)).first():
            return
        at = aware(clock(c, now))
        policy = c.execute(sa.select(db.policies.c.id).where(db.policies.c.store_id == STORE)
                           .order_by(db.policies.c.version.desc()).limit(1)).scalar_one()
        c.execute(insert(db.customers).values(id='camille', store_id=STORE,
                                              display_name='Camille Martin').on_conflict_do_nothing())
        for order, age, variants in (
            ('DEMO-RETURN', 8, ('return-tote', 'return-final-sale')),
            ('DEMO-RETURN-EXPIRED', 40, ('return-tote',)),
        ):
            shipment = 'PARCEL-' + order
            delivered = at - timedelta(days=age)
            c.execute(db.orders.insert().values(id=order, store_id=STORE, policy_id=policy,
                                                currency='EUR', resolution_history_complete=True))
            c.execute(db.customer_orders.insert().values(customer_id='camille', store_id=STORE, order_id=order))
            c.execute(db.shipments.insert().values(id=shipment, order_id=order, fulfilment_status='shipped',
                                                  carrier_status='delivered', carrier_observed_at=delivered))
            c.execute(db.delivery_parcels.insert().values(shipment_id=shipment, order_id=order, store_id=STORE,
                city='Paris', dispatch_origin='Paris', dispatched_at=delivered-timedelta(days=2), promised_at=delivered))
            for variant in variants:
                c.execute(db.order_lines.insert().values(order_id=order, variant_id=variant,
                                                         quantity=1, unit_price_minor=2900))
                c.execute(db.shipment_lines.insert().values(shipment_id=shipment, order_id=order,
                                                            variant_id=variant, quantity=1))
            ingest_event(c, STORE, shipment, 'return-fixture', order, 'delivered', delivered,
                         {'verified': True}, now=delivered)
        c.execute(db.seed_versions.insert().values(id=SEED_VERSION))
