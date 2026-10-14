"""Run-scoped local session phase accounting; no business/runtime upgrade."""
from alembic import op
revision='0008'
down_revision='0007'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("""CREATE TABLE commerce_adaptive_sessions (
      id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL REFERENCES commerce_adaptive_runs(id),
      job_id VARCHAR NOT NULL REFERENCES commerce_adaptive_jobs(id), token VARCHAR NOT NULL,
      ordinal INTEGER NOT NULL, config JSONB NOT NULL, config_hash VARCHAR(64) NOT NULL,
      generation INTEGER NOT NULL, case_revision BIGINT NOT NULL, state VARCHAR NOT NULL,
      retired BOOLEAN NOT NULL DEFAULT false, reserved_ms INTEGER NOT NULL, actual_charge_ms INTEGER,
      waiting_ms INTEGER NOT NULL DEFAULT 0, load_ms INTEGER NOT NULL DEFAULT 0,
      inference_ms INTEGER NOT NULL DEFAULT 0, total_ms INTEGER NOT NULL DEFAULT 0,
      api_charge_usd NUMERIC(20,8) NOT NULL DEFAULT 0, diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
      deadline TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL, UNIQUE(run_id,ordinal),
      CHECK(ordinal BETWEEN 1 AND 3 AND state IN ('waiting','loading','ready','closed','uncertain','failed') AND reserved_ms BETWEEN 1 AND 150000 AND api_charge_usd=0),
      CHECK(actual_charge_ms IS NULL OR actual_charge_ms BETWEEN 0 AND reserved_ms),
      CHECK(waiting_ms>=0 AND load_ms>=0 AND inference_ms>=0 AND total_ms>=0),
      CHECK(state NOT IN ('ready','closed','failed') OR actual_charge_ms IS NOT NULL))""")
    op.execute("CREATE UNIQUE INDEX uq_adaptive_session_pending ON commerce_adaptive_sessions(run_id) WHERE NOT retired AND state IN ('waiting','loading','ready','uncertain')")
    op.execute("""CREATE TABLE commerce_adaptive_session_events (
      session_id VARCHAR NOT NULL REFERENCES commerce_adaptive_sessions(id), sequence INTEGER NOT NULL,
      kind VARCHAR NOT NULL,data JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(session_id,sequence))""")
    op.execute('CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON commerce_adaptive_session_events FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()')
    op.execute("""CREATE FUNCTION commerce_guard_session() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Session history immutable'; END IF;
      IF ROW(NEW.id,NEW.run_id,NEW.job_id,NEW.token,NEW.ordinal,NEW.config,NEW.config_hash,NEW.generation,NEW.case_revision,NEW.reserved_ms,NEW.deadline,NEW.created_at)
         IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.job_id,OLD.token,OLD.ordinal,OLD.config,OLD.config_hash,OLD.generation,OLD.case_revision,OLD.reserved_ms,OLD.deadline,OLD.created_at)
        THEN RAISE EXCEPTION 'Session binding immutable'; END IF;
      IF (OLD.state='loading' AND NEW.state NOT IN ('loading','ready','uncertain','failed'))
         OR (OLD.state='ready' AND NEW.state NOT IN ('ready','closed','uncertain'))
         OR (OLD.state IN ('closed','uncertain','failed') AND ROW(NEW.state,NEW.actual_charge_ms) IS DISTINCT FROM ROW(OLD.state,OLD.actual_charge_ms))
         OR (OLD.actual_charge_ms IS NOT NULL AND NEW.actual_charge_ms IS DISTINCT FROM OLD.actual_charge_ms)
         OR (OLD.retired AND NOT NEW.retired) OR NEW.waiting_ms<OLD.waiting_ms OR NEW.load_ms<OLD.load_ms OR NEW.inference_ms<OLD.inference_ms OR NEW.total_ms<OLD.total_ms
        THEN RAISE EXCEPTION 'Session progress cannot reset'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER commerce_session_binding BEFORE UPDATE OR DELETE ON commerce_adaptive_sessions FOR EACH ROW EXECUTE FUNCTION commerce_guard_session()')

def downgrade():
    op.drop_table('commerce_adaptive_session_events');op.drop_table('commerce_adaptive_sessions');op.execute('DROP FUNCTION commerce_guard_session()')
