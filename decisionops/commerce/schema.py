"""Fictional store records, immutable audit, cases and local replacement ledger."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

policies = sa.Table(
    "policy_versions", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("store_id", sa.String, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("allow_confirmed_loss", sa.Boolean, nullable=False),
    sa.Column("max_units", sa.Integer, nullable=False),
    sa.Column("carrier_max_age_seconds", sa.Integer, nullable=False),
    sa.UniqueConstraint("store_id", "id"),
    sa.UniqueConstraint("store_id", "version"),
    sa.CheckConstraint("version > 0 AND max_units BETWEEN 1 AND 1000 AND carrier_max_age_seconds > 0"),
)
orders = sa.Table(
    "orders", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("store_id", sa.String, nullable=False),
    sa.Column("policy_id", sa.String, nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.Column("resolution_history_complete", sa.Boolean, nullable=False),
    sa.Column("compensation_revision", sa.BigInteger, nullable=False, server_default="0"),
    sa.CheckConstraint("compensation_revision >= 0", name="ck_compensation_revision"),
    sa.ForeignKeyConstraint(["store_id", "policy_id"], ["policy_versions.store_id", "policy_versions.id"]),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'"),
)
order_lines = sa.Table(
    "order_lines", metadata,
    sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), primary_key=True),
    sa.Column("variant_id", sa.String, primary_key=True),
    sa.Column("quantity", sa.Integer, nullable=False),
    sa.Column("unit_price_minor", sa.BigInteger, nullable=False),
    sa.CheckConstraint("quantity BETWEEN 1 AND 1000 AND unit_price_minor >= 0"),
)
payments = sa.Table(
    "payments", metadata,
    sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), primary_key=True),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("amount_minor", sa.BigInteger, nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.CheckConstraint("status IN ('paid', 'pending', 'failed') AND amount_minor >= 0"),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'"),
)
shipments = sa.Table(
    "shipments", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), nullable=False),
    sa.Column("fulfilment_status", sa.String, nullable=False),
    sa.Column("carrier_status", sa.String, nullable=False),
    sa.Column("carrier_observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("id", "order_id"),
    sa.CheckConstraint("fulfilment_status IN ('shipped', 'prepared')"),
    sa.CheckConstraint("carrier_status IN ('lost', 'in_transit', 'delivered', 'unknown')"),
)
shipment_lines = sa.Table(
    "shipment_lines", metadata,
    sa.Column("shipment_id", sa.String, primary_key=True),
    sa.Column("order_id", sa.String, nullable=False),
    sa.Column("variant_id", sa.String, primary_key=True),
    sa.Column("quantity", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(["shipment_id", "order_id"], ["shipments.id", "shipments.order_id"]),
    sa.ForeignKeyConstraint(["order_id", "variant_id"], ["order_lines.order_id", "order_lines.variant_id"]),
    sa.CheckConstraint("quantity BETWEEN 1 AND 1000"),
)
inventory = sa.Table(
    "inventory", metadata,
    sa.Column("store_id", sa.String, primary_key=True),
    sa.Column("variant_id", sa.String, primary_key=True),
    sa.Column("on_hand", sa.Integer, nullable=False),
    sa.Column("reserved", sa.Integer, nullable=False),
    sa.CheckConstraint("on_hand >= 0 AND reserved >= 0 AND reserved <= on_hand"),
)
resolutions = sa.Table(
    "resolutions", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("order_id", sa.String, nullable=False),
    sa.Column("variant_id", sa.String, nullable=False),
    sa.Column("quantity", sa.Integer, nullable=False),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("operation_id", sa.String, sa.ForeignKey("commerce_operations.id", use_alter=True, name="fk_resolution_operation")),
    sa.UniqueConstraint("operation_id", "variant_id", name="uq_resolution_operation_variant"),
    sa.CheckConstraint("operation_id IS NULL OR kind = 'replacement'", name="ck_resolution_operation_kind"),
    sa.ForeignKeyConstraint(["order_id", "variant_id"], ["order_lines.order_id", "order_lines.variant_id"]),
    sa.CheckConstraint("quantity BETWEEN 1 AND 1000 AND kind IN ('refund', 'replacement')"),
)
seed_versions = sa.Table("seed_versions", metadata, sa.Column("id", sa.String, primary_key=True))

# Audit snapshots are append-only; migration 0002 installs mutation guards.
investigations = sa.Table(
    "commerce_investigations", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("order_id", sa.String, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("assessment", JSONB, nullable=False),
    sa.CheckConstraint("jsonb_typeof(assessment) = 'object'"),
)
proposals = sa.Table(
    "commerce_proposals", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("investigation_id", sa.String, sa.ForeignKey("commerce_investigations.id"), nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("document", JSONB, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.CheckConstraint("jsonb_typeof(document) = 'object' AND content_hash ~ '^[0-9a-f]{64}$'"),
)

cases = sa.Table(
    "commerce_cases", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), nullable=False),
    sa.Column("request", JSONB, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("case_revision", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("investigation_id", sa.String, sa.ForeignKey("commerce_investigations.id")),
    sa.Column("proposal_id", sa.String, sa.ForeignKey("commerce_proposals.id")),
    sa.Column("approval_id", sa.String, sa.ForeignKey("commerce_reviews.id", use_alter=True, name="fk_case_approval")),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("id", "order_id"),
    sa.CheckConstraint("generation >= 0 AND status IN ('open','awaiting_review','needs_review','blocked','approved','rejected','escalated','executed')"),
    sa.CheckConstraint("status NOT IN ('awaiting_review','approved') OR proposal_id IS NOT NULL"),
    sa.CheckConstraint("status != 'approved' OR approval_id IS NOT NULL"),
)
reviews = sa.Table(
    "commerce_reviews", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("case_id", sa.String, sa.ForeignKey("commerce_cases.id"), nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("proposal_id", sa.String, sa.ForeignKey("commerce_proposals.id"), nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("decision", sa.String, nullable=False),
    sa.Column("actor", sa.String(128), nullable=False),
    sa.Column("operation_id", sa.String, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("case_id", "generation"),
    sa.UniqueConstraint("id", "case_id"),
    sa.UniqueConstraint("id", "operation_id"),
    sa.CheckConstraint("generation > 0 AND decision IN ('approve','reject') AND content_hash ~ '^[0-9a-f]{64}$'"),
    sa.CheckConstraint("(decision = 'approve' AND operation_id IS NOT NULL) OR (decision = 'reject' AND operation_id IS NULL)"),
)
case_events = sa.Table(
    "commerce_case_events", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("sequence", sa.BigInteger, sa.Identity(), nullable=False, unique=True),
    sa.Column("case_id", sa.String, sa.ForeignKey("commerce_cases.id"), nullable=False),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("details", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
operations = sa.Table(
    "commerce_operations", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("review_id", sa.String, nullable=False, unique=True),
    sa.Column("case_id", sa.String, nullable=False, unique=True),
    sa.Column("order_id", sa.String, nullable=False, unique=True),
    sa.Column("request", JSONB, nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("id", "order_id"),
    sa.ForeignKeyConstraint(["review_id", "case_id"], ["commerce_reviews.id", "commerce_reviews.case_id"]),
    sa.ForeignKeyConstraint(["review_id", "id"], ["commerce_reviews.id", "commerce_reviews.operation_id"]),
    sa.ForeignKeyConstraint(["case_id", "order_id"], ["commerce_cases.id", "commerce_cases.order_id"]),
)
replacement_orders = sa.Table(
    "commerce_replacement_orders", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("operation_id", sa.String, sa.ForeignKey("commerce_operations.id"), nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("id", "operation_id"),
)
replacement_lines = sa.Table(
    "commerce_replacement_lines", metadata,
    sa.Column("replacement_id", sa.String, nullable=False, primary_key=True),
    sa.Column("variant_id", sa.String, nullable=False, primary_key=True),
    sa.Column("operation_id", sa.String, nullable=False),
    sa.Column("order_id", sa.String, nullable=False),
    sa.Column("quantity", sa.Integer, nullable=False),
    sa.Column("resolution_id", sa.String, sa.ForeignKey("resolutions.id"), nullable=False, unique=True),
    sa.UniqueConstraint("operation_id", "variant_id", "quantity"),
    sa.ForeignKeyConstraint(["replacement_id", "operation_id"], ["commerce_replacement_orders.id", "commerce_replacement_orders.operation_id"]),
    sa.ForeignKeyConstraint(["operation_id", "order_id"], ["commerce_operations.id", "commerce_operations.order_id"]),
    sa.ForeignKeyConstraint(["order_id", "variant_id"], ["order_lines.order_id", "order_lines.variant_id"]),
    sa.CheckConstraint("quantity BETWEEN 1 AND 1000"),
)
reservations = sa.Table(
    "commerce_reservations", metadata,
    sa.Column("operation_id", sa.String, primary_key=True),
    sa.Column("variant_id", sa.String, primary_key=True),
    sa.Column("store_id", sa.String, nullable=False),
    sa.Column("quantity", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(["operation_id", "variant_id", "quantity"], ["commerce_replacement_lines.operation_id", "commerce_replacement_lines.variant_id", "commerce_replacement_lines.quantity"]),
    sa.ForeignKeyConstraint(["store_id", "variant_id"], ["inventory.store_id", "inventory.variant_id"]),
    sa.CheckConstraint("quantity BETWEEN 1 AND 1000"),
)

jobs = sa.Table(
    "commerce_jobs", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("case_id", sa.String, sa.ForeignKey("commerce_cases.id"), nullable=False),
    sa.Column("action", sa.String, nullable=False),
    sa.Column("operation_id", sa.String),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("token", sa.String),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("outcome", JSONB),
    sa.Column("error_kind", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("action IN ('investigate','execute') AND status IN ('queued','running','completed','failed') AND attempts BETWEEN 0 AND 3"),
    sa.CheckConstraint("(action='investigate' AND operation_id IS NULL) OR (action='execute' AND operation_id IS NOT NULL)"),
    sa.CheckConstraint("status != 'running' OR (token IS NOT NULL AND lease_until IS NOT NULL)"),
    sa.CheckConstraint("status != 'completed' OR outcome IS NOT NULL"),
)
sa.Index("uq_commerce_inflight_case", jobs.c.case_id, unique=True,
         postgresql_where=jobs.c.status.in_(("queued", "running")))

# Optional simulated decision routing; immutable limits/pricing and durable call state.
provider_budgets = sa.Table(
    'commerce_provider_budgets', metadata,
    sa.Column('id',sa.String(128),primary_key=True),
    sa.Column('limits',JSONB,nullable=False),sa.Column('pricing',JSONB,nullable=False),
    sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
)
provider_calls = sa.Table(
    'commerce_provider_calls',metadata,
    sa.Column('run_id',sa.String(128),primary_key=True),
    sa.Column('case_id',sa.String,sa.ForeignKey('commerce_cases.id'),nullable=False),
    sa.Column('budget_id',sa.String(128),sa.ForeignKey('commerce_provider_budgets.id'),nullable=False),
    sa.Column('request',JSONB,nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
    sa.Column('state',sa.String,nullable=False),
    sa.Column('reserved_cost_usd',sa.Numeric(20,8),nullable=False),
    sa.Column('actual_cost_usd',sa.Numeric(20,8)),
    sa.Column('dispatch_count',sa.Integer,nullable=False,server_default='0'),
    sa.Column('result',JSONB),sa.Column('effective_choice',sa.String),
    sa.Column('application_status',sa.String,nullable=False,server_default='pending'),
    sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
    sa.Column('deadline',sa.DateTime(timezone=True),nullable=False),
    sa.Column('finished_at',sa.DateTime(timezone=True)),
    sa.CheckConstraint("state IN ('reserved','dispatching','settled','uncertain','denied')"),
    sa.CheckConstraint("application_status IN ('pending','applied','fallback','stale')"),
    sa.CheckConstraint("effective_choice IS NULL OR effective_choice IN ('present_replacement','staff_review')"),
    sa.CheckConstraint('reserved_cost_usd >= 0 AND (actual_cost_usd IS NULL OR actual_cost_usd >= 0)'),
    sa.CheckConstraint('dispatch_count BETWEEN 0 AND 1'),
    sa.CheckConstraint("state != 'settled' OR (result IS NOT NULL AND actual_cost_usd IS NOT NULL)"),
    sa.CheckConstraint("state != 'uncertain' OR actual_cost_usd IS NULL"),
    sa.CheckConstraint("state != 'denied' OR (dispatch_count=0 AND reserved_cost_usd=0)"),
)

# Optional adaptive read-only investigation. Business writes remain separate.
adaptive_runs = sa.Table(
    'commerce_adaptive_runs', metadata,
    sa.Column('id',sa.String,primary_key=True),
    sa.Column('case_id',sa.String,sa.ForeignKey('commerce_cases.id'),nullable=False),
    sa.Column('generation',sa.Integer,nullable=False),
    sa.Column('case_revision',sa.BigInteger,nullable=False),
    sa.Column('request',JSONB,nullable=False),sa.Column('report',sa.Text,nullable=False),
    sa.Column('contracts',JSONB,nullable=False),
    sa.Column('state',sa.String,nullable=False),
    sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
    sa.Column('deadline',sa.DateTime(timezone=True),nullable=False),
    sa.Column('context_version',sa.BigInteger,nullable=False,server_default='0'),
    sa.Column('decision_attempts',sa.Integer,nullable=False,server_default='0'),
    sa.Column('tool_attempts',sa.Integer,nullable=False,server_default='0'),
    sa.Column('pending_token',sa.String),sa.Column('pending_context',sa.BigInteger),sa.Column('terminal',JSONB),
    sa.CheckConstraint("generation > 0 AND case_revision >= 0 AND context_version >= 0"),
    sa.CheckConstraint("state IN ('active','proposed','blocker_reported','review','stale')"),
    sa.CheckConstraint('decision_attempts BETWEEN 0 AND 16 AND tool_attempts BETWEEN 0 AND 12'),
    sa.CheckConstraint("octet_length(report) <= 2000 AND deadline > created_at AND deadline <= created_at + INTERVAL '240 seconds'"),
    sa.CheckConstraint("state = 'active' OR (terminal IS NOT NULL AND pending_token IS NULL)"),
    sa.CheckConstraint("(pending_token IS NULL AND pending_context IS NULL) OR (pending_token IS NOT NULL AND pending_context BETWEEN 1 AND context_version)"),
)
sa.Index('uq_adaptive_active_case',adaptive_runs.c.case_id,unique=True,
         postgresql_where=adaptive_runs.c.state=='active')
adaptive_steps = sa.Table(
    'commerce_adaptive_steps',metadata,
    sa.Column('run_id',sa.String,sa.ForeignKey('commerce_adaptive_runs.id'),primary_key=True),
    sa.Column('sequence',sa.BigInteger,primary_key=True),
    sa.Column('kind',sa.String,nullable=False),sa.Column('data',JSONB,nullable=False),
    sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
    sa.CheckConstraint('sequence > 0'),
)
adaptive_observations = sa.Table(
    'commerce_adaptive_observations',metadata,
    sa.Column('id',sa.String,primary_key=True),sa.Column('run_id',sa.String,nullable=False),
    sa.Column('step_sequence',sa.BigInteger,nullable=False),
    sa.Column('record',JSONB,nullable=False),sa.Column('applied',sa.Boolean,nullable=False),
    sa.UniqueConstraint('run_id','id'),
    sa.ForeignKeyConstraint(['run_id','step_sequence'],['commerce_adaptive_steps.run_id','commerce_adaptive_steps.sequence']),
)
adaptive_supersessions = sa.Table(
    'commerce_adaptive_supersessions',metadata,
    sa.Column('run_id',sa.String,primary_key=True),sa.Column('old_id',sa.String,primary_key=True),
    sa.Column('new_id',sa.String,nullable=False),
    sa.ForeignKeyConstraint(['run_id','old_id'],['commerce_adaptive_observations.run_id','commerce_adaptive_observations.id']),
    sa.ForeignKeyConstraint(['run_id','new_id'],['commerce_adaptive_observations.run_id','commerce_adaptive_observations.id']),
)
adaptive_active = sa.Table(
    'commerce_adaptive_active',metadata,
    sa.Column('run_id',sa.String,primary_key=True),sa.Column('tool',sa.String,primary_key=True),
    sa.Column('stream',sa.String,primary_key=True),sa.Column('observation_id',sa.String,nullable=False),
    sa.ForeignKeyConstraint(['run_id','observation_id'],['commerce_adaptive_observations.run_id','commerce_adaptive_observations.id']),
)
adaptive_tool_counts = sa.Table(
    'commerce_adaptive_tool_counts',metadata,
    sa.Column('run_id',sa.String,sa.ForeignKey('commerce_adaptive_runs.id'),primary_key=True),
    sa.Column('tool',sa.String,primary_key=True),sa.Column('attempts',sa.Integer,nullable=False),
    sa.CheckConstraint('attempts BETWEEN 1 AND 2'),
)
