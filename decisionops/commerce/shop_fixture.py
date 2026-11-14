"""Opt-in fictional shopper projection and one-time isolated fixture preparation.

No inventory, compensation or replacement-policy data is queried or returned here.
"""
from datetime import timedelta
import sqlalchemy as sa
from . import schema as db
ORDER_IDS=('ORD-1042','ORD-TRACKING','ORD-HISTORY')
SEED='shop-browser-fixture-v1'

def require_fixture_database(c):
    if tuple(c.exec_driver_sql('SELECT current_database(),current_user').one())!=('shop_fixture','shop_fixture'):
        raise ValueError('Shop fixture requires its isolated shop_fixture database/user')

def shopper_orders(c,order_id=None,tracking=False):
    require_fixture_database(c)
    orders=c.execute(sa.select(db.orders.c.id,db.orders.c.currency).where(sa.and_(
        db.orders.c.store_id=='demo-store',db.orders.c.id.in_((order_id,) if order_id else ORDER_IDS)))).mappings().all()
    result=[]
    for order in orders:
        lines=[dict(r) for r in c.execute(sa.select(db.order_lines.c.variant_id,db.order_lines.c.quantity,db.order_lines.c.unit_price_minor).where(db.order_lines.c.order_id==order['id'])).mappings()]
        shipment=None
        if order_id:
            expected='SHIP-'+order['id'].removeprefix('ORD-')
            columns=[db.shipments.c.id,db.shipments.c.fulfilment_status]
            if tracking:columns.extend((db.shipments.c.carrier_status,db.shipments.c.carrier_observed_at))
            shipment=c.execute(sa.select(*columns).where(sa.and_(
                db.shipments.c.order_id==order['id'],db.shipments.c.id==expected))).mappings().one_or_none()
        result.append({'id':order['id'],'currency':order['currency'],'lines':lines,
                       'shipment':dict(shipment) if shipment else None})
    return result

def main():
    from .database import database_engine
    from .seed import seed
    engine=database_engine()
    try:
        with engine.connect() as c:require_fixture_database(c)
        seed(engine)
        with engine.begin() as c:
            require_fixture_database(c);c.exec_driver_sql('SELECT pg_advisory_xact_lock(10420002)')
            if c.execute(sa.select(db.seed_versions.c.id).where(db.seed_versions.c.id==SEED)).first():
                print('Shop fixture already prepared; records preserved');return
            now=c.exec_driver_sql('SELECT clock_timestamp()').scalar_one()
            c.execute(db.shipments.update().where(sa.and_(db.shipments.c.id=='SHIP-TRACKING',db.shipments.c.order_id=='ORD-TRACKING')).values(carrier_observed_at=now-timedelta(days=3)))
            c.execute(db.seed_versions.insert().values(id=SEED))
        print('Fictional shop prepared once: confirmed loss and an old unconfirmed tracking update')
    finally:engine.dispose()
if __name__=='__main__':main()
