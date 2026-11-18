"""Owned customer conversations and immutable nonreceipt reports."""
from alembic import op
revision='0011'
down_revision='0010'
branch_labels=None
depends_on=None

def upgrade():
    op.create_unique_constraint('uq_delivery_link_case_scope','commerce_delivery_case_links',['store_id','shipment_id','case_id'])
    op.execute('''CREATE TABLE commerce_customers (
        id VARCHAR(128) PRIMARY KEY, store_id VARCHAR NOT NULL,
        display_name VARCHAR(128) NOT NULL, UNIQUE(id,store_id))''')
    op.execute('''CREATE TABLE commerce_customer_orders (
        customer_id VARCHAR(128) NOT NULL, order_id VARCHAR NOT NULL UNIQUE,
        store_id VARCHAR NOT NULL, PRIMARY KEY(customer_id,order_id),
        FOREIGN KEY(customer_id,store_id) REFERENCES commerce_customers(id,store_id),
        FOREIGN KEY(store_id,order_id) REFERENCES orders(store_id,id))''')
    op.execute('''CREATE TABLE commerce_customer_conversations (
        id VARCHAR PRIMARY KEY, customer_id VARCHAR(128) NOT NULL REFERENCES commerce_customers(id),
        selected_order_id VARCHAR, selected_shipment_id VARCHAR, created_at TIMESTAMPTZ NOT NULL,
        UNIQUE(id,customer_id),
        FOREIGN KEY(customer_id,selected_order_id) REFERENCES commerce_customer_orders(customer_id,order_id),
        FOREIGN KEY(selected_shipment_id,selected_order_id) REFERENCES shipments(id,order_id),
        CHECK(selected_shipment_id IS NULL OR selected_order_id IS NOT NULL))''')
    op.execute('''CREATE TABLE commerce_customer_messages (
        conversation_id VARCHAR REFERENCES commerce_customer_conversations(id), request_id VARCHAR(128),
        message VARCHAR(2000) NOT NULL, response JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(conversation_id,request_id))''')
    op.execute('''CREATE TABLE commerce_customer_reports (
        id VARCHAR PRIMARY KEY, conversation_id VARCHAR NOT NULL, customer_id VARCHAR(128) NOT NULL,
        store_id VARCHAR NOT NULL, order_id VARCHAR NOT NULL,
        request_id VARCHAR(128) NOT NULL, case_id VARCHAR NOT NULL REFERENCES commerce_cases(id),
        shipment_id VARCHAR NOT NULL REFERENCES commerce_delivery_parcels(shipment_id),
        message VARCHAR(2000) NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        UNIQUE(conversation_id,request_id),
        FOREIGN KEY(customer_id,order_id) REFERENCES commerce_customer_orders(customer_id,order_id),
        FOREIGN KEY(store_id,shipment_id,case_id) REFERENCES commerce_delivery_case_links(store_id,shipment_id,case_id),
        FOREIGN KEY(store_id,shipment_id,order_id) REFERENCES commerce_delivery_parcels(store_id,shipment_id,order_id),
        FOREIGN KEY(conversation_id,customer_id) REFERENCES commerce_customer_conversations(id,customer_id))''')
    for table in ('commerce_customer_reports','commerce_customer_messages'):
        op.execute(f'CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()')

def downgrade():
    for table in ('commerce_customer_reports','commerce_customer_messages','commerce_customer_conversations','commerce_customer_orders','commerce_customers'):
        op.drop_table(table)

    op.drop_constraint('uq_delivery_link_case_scope','commerce_delivery_case_links',type_='unique')
