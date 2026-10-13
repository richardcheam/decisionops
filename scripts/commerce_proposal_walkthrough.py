"""Local success/drift/undo demo in a disposable schema, never public records.

Run from repository root with COMMERCE_TEST_DATABASE_URL and the commerce venv.
The parent database must already exist. Uses no models or external providers.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

# Direct script execution adds scripts/, not the repository root, to sys.path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from decisionops.commerce.database import database_engine
from decisionops.commerce.seed import seed


def main():
    url = os.environ.get("COMMERCE_TEST_DATABASE_URL")
    if not url:
        raise SystemExit("Set COMMERCE_TEST_DATABASE_URL to the local fictional demo database")
    schema = "walkthrough_" + uuid.uuid4().hex
    admin = database_engine(url)
    scoped = make_url(url).update_query_dict({"options": "-csearch_path=" + schema})
    engine = database_engine(scoped)
    (ROOT / "runs").mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="proposal-walkthrough-", dir=ROOT / "runs"))
    created = False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        config = Config(str(ROOT / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        seed(engine)  # Fresh fictional records in this isolated schema only.
        env = dict(os.environ, COMMERCE_DATABASE_URL=scoped.render_as_string(hide_password=False))

        def cli(name, *args, expected=0):
            completed = subprocess.run([sys.executable, "-B", "-m", "decisionops.commerce.case_demo", *args],
                                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            (directory / (name + ".json")).write_text(completed.stdout)
            (directory / (name + ".stderr.log")).write_text(completed.stderr)
            if completed.returncode != expected:
                raise RuntimeError(f"{name}: expected exit {expected}, received {completed.returncode}; see {directory}")
            return json.loads(completed.stdout)

        saved = cli("investigation", "investigate", "--order", "ORD-1042", "--shipment", "SHIP-1042", "--item", "shirt-blue-M:1")
        proposal = saved["proposal_id"]
        assert proposal is not None
        before = cli("before", "check", "--proposal", proposal)
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
        changed = cli("stock-changed", "check", "--proposal", proposal, expected=4)
        snapshot = cli("original-snapshot", "inspect", "--investigation", saved["investigation_id"])
        assert before["status"] == "valid_for_review"
        assert changed["status"] == "requires_reinvestigation"
        assert changed["current_decision"]["status"] == "eligible_to_propose"
        assert changed["changed_requirements"] == ["stock_available"]
        assert snapshot["assessment"]["read_tools"][5]["details"]["available_units"]["shirt-blue-M"] == 9
        with engine.begin() as connection:
            # Safe undo of our known isolated demo change; no intervening writers.
            connection.exec_driver_sql("UPDATE inventory SET on_hand=10 WHERE variant_id='shirt-blue-M'")
        restored = cli("stock-restored", "check", "--proposal", proposal)
        assert restored["status"] == "valid_for_review"
        for name, result in (("before", before), ("stock changed", changed), ("stock restored", restored)):
            print(name + ": " + result["status"])
        print("artifacts: " + str(directory.relative_to(ROOT)))
    finally:
        engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
    print("isolated schema removed; public demo data unchanged")


if __name__ == "__main__":
    main()
