"""Delivery provenance, promises, exception queue and scoped conversations."""
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint('uq_orders_store_id','orders',['store_id','id'])
    op.execute('''CREATE TABLE commerce_delivery_parcels (
      shipment_id VARCHAR PRIMARY KEY, order_id VARCHAR NOT NULL, store_id VARCHAR NOT NULL,
      city VARCHAR NOT NULL, dispatch_origin VARCHAR NOT NULL,
      dispatched_at TIMESTAMPTZ NOT NULL, promised_at TIMESTAMPTZ NOT NULL,
      feed_available BOOLEAN NOT NULL DEFAULT TRUE, reported_nonreceipt BOOLEAN NOT NULL DEFAULT FALSE,
      FOREIGN KEY(store_id,order_id) REFERENCES orders(store_id,id),
      FOREIGN KEY(shipment_id,order_id) REFERENCES shipments(id,order_id),
      UNIQUE(store_id,shipment_id,order_id), CHECK(promised_at >= dispatched_at))''')
    op.execute('CREATE INDEX ix_delivery_store_promise ON commerce_delivery_parcels(store_id,promised_at)')
    op.execute('''CREATE TABLE commerce_carrier_events (
      id VARCHAR(64) PRIMARY KEY, shipment_id VARCHAR NOT NULL REFERENCES commerce_delivery_parcels(shipment_id),
      source VARCHAR(128) NOT NULL, external_id VARCHAR(256) NOT NULL,
      event_at TIMESTAMPTZ NOT NULL, received_at TIMESTAMPTZ NOT NULL,
      status VARCHAR NOT NULL, verified BOOLEAN NOT NULL, original JSONB NOT NULL,
      CHECK(status IN ('lost','in_transit','delivered','unknown') AND jsonb_typeof(original)='object'))''')
    op.execute('CREATE INDEX ix_carrier_source_identity ON commerce_carrier_events(source,external_id)')
    op.execute('CREATE INDEX ix_carrier_parcel_time ON commerce_carrier_events(shipment_id,event_at)')
    op.execute('CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON commerce_carrier_events FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()')
    op.execute('''CREATE TABLE commerce_delivery_case_links (
      store_id VARCHAR NOT NULL, shipment_id VARCHAR NOT NULL, order_id VARCHAR NOT NULL,
      case_id VARCHAR NOT NULL UNIQUE, active BOOLEAN NOT NULL, PRIMARY KEY(store_id,shipment_id),
      FOREIGN KEY(store_id,shipment_id,order_id) REFERENCES commerce_delivery_parcels(store_id,shipment_id,order_id),
      FOREIGN KEY(case_id,order_id) REFERENCES commerce_cases(id,order_id))''')
    op.execute('''CREATE TABLE commerce_delivery_triggers (
      store_id VARCHAR NOT NULL, shipment_id VARCHAR NOT NULL, kind VARCHAR NOT NULL,
      active BOOLEAN NOT NULL, updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(store_id,shipment_id,kind),
      FOREIGN KEY(store_id,shipment_id) REFERENCES commerce_delivery_case_links(store_id,shipment_id),
      CHECK(kind IN ('overdue','nonreceipt','carrier_conflict')))''')
    op.execute('''CREATE TABLE commerce_conversations (
      id VARCHAR PRIMARY KEY, actor VARCHAR(128) NOT NULL, store_id VARCHAR NOT NULL,
      selected_case_id VARCHAR REFERENCES commerce_cases(id), created_at TIMESTAMPTZ NOT NULL)''')
    op.execute('''CREATE TABLE commerce_conversation_messages (
      conversation_id VARCHAR REFERENCES commerce_conversations(id), request_id VARCHAR(128),
      message VARCHAR(2000) NOT NULL, response JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
      PRIMARY KEY(conversation_id,request_id))''')


def downgrade():
    for table in ('commerce_conversation_messages','commerce_conversations','commerce_delivery_triggers',
                  'commerce_delivery_case_links','commerce_carrier_events','commerce_delivery_parcels'):
        op.drop_table(table)
    op.drop_constraint('uq_orders_store_id','orders',type_='unique')
