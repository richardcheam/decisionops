"""Versioned catalog images, staff cases and immutable relink receipts."""
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE commerce_catalog_listings (
        store_id VARCHAR NOT NULL, sku VARCHAR NOT NULL, title VARCHAR NOT NULL,
        current_image_id VARCHAR NOT NULL, version INTEGER NOT NULL CHECK (version > 0),
        image_mappings JSONB NOT NULL CHECK (jsonb_typeof(image_mappings) = 'array'),
        supplier_record JSONB NOT NULL CHECK (jsonb_typeof(supplier_record) = 'object'),
        PRIMARY KEY (store_id, sku)
    )""")
    op.execute("""CREATE TABLE commerce_catalog_cases (
        store_id VARCHAR NOT NULL, id VARCHAR NOT NULL, sku VARCHAR NOT NULL,
        status VARCHAR NOT NULL, reason VARCHAR NOT NULL, proposal JSONB,
        proposal_hash VARCHAR(64), approved_by VARCHAR(128),
        PRIMARY KEY (store_id, id), UNIQUE (store_id, sku),
        FOREIGN KEY (store_id, sku) REFERENCES commerce_catalog_listings(store_id, sku),
        CHECK (status IN ('open', 'current', 'review', 'proposed', 'approved', 'confirmed')),
        CHECK ((status IN ('proposed', 'approved', 'confirmed')) = (proposal_hash IS NOT NULL AND proposal IS NOT NULL)),
        CHECK ((status IN ('approved', 'confirmed')) = (approved_by IS NOT NULL))
    )""")
    op.execute("""CREATE TABLE commerce_catalog_relinks (
        store_id VARCHAR NOT NULL, case_id VARCHAR NOT NULL, proposal_hash VARCHAR(64) NOT NULL,
        previous_image_id VARCHAR NOT NULL, saved_image_id VARCHAR NOT NULL,
        listing_version INTEGER NOT NULL CHECK (listing_version > 1),
        approved_by VARCHAR(128) NOT NULL, confirmed_by VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (store_id, case_id), FOREIGN KEY (store_id, case_id) REFERENCES commerce_catalog_cases(store_id, id),
        CHECK (previous_image_id <> saved_image_id)
    )""")
    op.execute("""CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON commerce_catalog_relinks
        FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()""")


def downgrade():
    op.drop_table('commerce_catalog_relinks')
    op.drop_table('commerce_catalog_cases')
    op.drop_table('commerce_catalog_listings')
