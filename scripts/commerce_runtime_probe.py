"""Exercise worker interruption and inspect the fictional deployed database in CI."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "decisionops-local-portfolio"

CRASH = """
import os
from sqlalchemy import text
from decisionops.commerce.database import database_engine
from decisionops.commerce import adaptive_jobs as jobs, multi_agent_workflow as graph

engine = database_engine()
with engine.connect() as connection:
    job = connection.execute(text('''
        SELECT j.id FROM commerce_adaptive_jobs j
        JOIN commerce_adaptive_runs r ON r.id=j.run_id
        JOIN commerce_cases c ON c.id=r.case_id
        WHERE c.order_id='DEMO-LYON' AND j.status='queued'
    ''')).scalar_one()
owned = jobs.claim(engine, job_id=job, action=jobs.SPECIALIST_ACTION)
assert owned is not None
def interrupt(name, result):
    if name == 'order':
        os._exit(73)
graph.run(engine, jobs.Fence(owned['id'], owned['token']), after_node=interrupt)
"""

SNAPSHOT = """
import json
from sqlalchemy import text
from decisionops.commerce.database import database_engine

with database_engine().connect() as connection:
    run, claims = connection.execute(text('''
        SELECT r.id, j.claims FROM commerce_adaptive_runs r
        JOIN commerce_adaptive_jobs j ON j.run_id=r.id
        JOIN commerce_cases c ON c.id=r.case_id WHERE c.order_id='DEMO-LYON'
    ''')).one()
    calls = connection.execute(text('''
        SELECT id FROM commerce_specialist_calls
        WHERE run_id=:run AND specialist='order' AND disposition='applied' ORDER BY id
    '''), {'run':run}).scalars().all()
    counts = connection.execute(text('''
        SELECT
          (SELECT count(*) FROM commerce_operations WHERE order_id='DEMO-LYON'),
          (SELECT count(*) FROM commerce_replacement_orders r JOIN commerce_operations o ON r.operation_id=o.id WHERE o.order_id='DEMO-LYON'),
          (SELECT count(*) FROM commerce_reservations r JOIN commerce_operations o ON r.operation_id=o.id WHERE o.order_id='DEMO-LYON'),
          (SELECT coalesce(sum(r.quantity),0) FROM commerce_reservations r JOIN commerce_operations o ON r.operation_id=o.id WHERE o.order_id='DEMO-LYON'),
          (SELECT count(*) FROM commerce_delivery_case_links WHERE order_id='DEMO-LYON')
    ''')).one()
    print(json.dumps({'claims':claims, 'order_calls':calls, 'counts':list(counts)}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("pause", "interrupt", "verify"))
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This probe requires the disposable GitHub Actions environment")
    mode = os.environ.get("COMMERCE_RUNTIME")
    if mode == "compose":
        base = ["docker", "compose", "--env-file", "/dev/null", "-p", "decisionops-runtime", "-f", "compose.yaml"]
        execute = [*base, "exec", "-T", "api"]
        pause = [*base, "stop", "staff-investigator"]
        resume = [*base, "start", "staff-investigator"]
    elif mode == "kubernetes":
        base = ["kubectl", "--context", "kind-decisionops-runtime", "-n", NAMESPACE]
        execute = [*base, "exec", "deployment/api", "--"]
        pause = [*base, "scale", "deployment/staff-investigator", "--replicas=0"]
        resume = [*base, "scale", "deployment/staff-investigator", "--replicas=1"]
    else:
        parser.error("Set COMMERCE_RUNTIME to compose or kubernetes")

    def run(command, **kwargs):
        return subprocess.run(command, cwd=ROOT, timeout=100, text=True, **kwargs)

    def snapshot():
        result = run([*execute, "python", "-B", "-c", SNAPSHOT], capture_output=True, check=True)
        return json.loads(result.stdout)

    evidence = ROOT / "runs" / f"runtime-{mode}-interruption.json"
    if args.phase == "pause":
        run(pause, check=True)
        if mode == "kubernetes":
            pods = run([*base, "get", "pods", "-l", "app=staff-investigator", "-o", "name"],
                       capture_output=True, check=True).stdout.split()
            if pods:
                run([*base, "wait", "--for=delete", "--timeout=65s", *pods], check=True)
    elif args.phase == "interrupt":
        result = run([*execute, "python", "-B", "-c", CRASH])
        if result.returncode != 73:
            raise RuntimeError(f"Expected hard exit 73, received {result.returncode}")
        before = snapshot()
        if before["claims"] != 1 or len(before["order_calls"]) != 2 or before["counts"] != [0, 0, 0, 0, 1]:
            raise RuntimeError("Interrupted worker did not leave the expected committed specialist work")
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text(json.dumps(before))
        run(resume, check=True)
    else:
        before = json.loads(evidence.read_text())
        after = snapshot()
        if after["claims"] != 2 or after["order_calls"] != before["order_calls"] or after["counts"] != [1, 1, 1, 1, 1]:
            raise RuntimeError("Recovery changed committed specialist calls or duplicated business records")
        print(json.dumps({"hard_exit": 73, "claims": after["claims"], "committed_calls_reused": 2,
                          "operations": 1, "replacement_orders": 1, "reservations": 1,
                          "reserved_units": 1, "canonical_case_links": 1}))


if __name__ == "__main__":
    main()
