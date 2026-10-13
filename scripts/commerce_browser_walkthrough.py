"""Real browser + API + worker demo in owned temporary business/checkpoint schemas.

Temporarily switches this local Compose app to the temporary store, then restores
the original public store even on failure. Do not run while another operator uses it.
"""
import os
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy.engine import make_url
from decisionops.commerce.database import database_engine
from decisionops.commerce.workflow import graph_schema


def main():
    (ROOT / "runs").mkdir(exist_ok=True)
    url = os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:
        raise SystemExit('Set COMMERCE_TEST_DATABASE_URL to the local demo database')
    schema = 'browser_walkthrough_' + uuid.uuid4().hex
    engine = database_engine(url)
    directory = Path(tempfile.mkdtemp(prefix='browser-walkthrough-', dir=ROOT/'runs'))
    results = directory/'results'
    results.mkdir(mode=0o777)
    results.chmod(0o777)
    container_url = make_url(url).set(host='postgres', port=5432).update_query_dict({'options': '-csearch_path='+schema})
    override = directory/'compose.test.yaml'
    # Only fictional database credentials; staff credentials stay in ignored .env.
    override.write_text('services:\n' + ''.join(
        f'  {service}:\n    environment:\n      COMMERCE_DATABASE_URL: {container_url.render_as_string(hide_password=False)!r}\n'
        for service in ('init', 'api', 'worker')))
    def docker(name, *args, timeout=180):
        result = subprocess.run(['sg','docker','-c',shlex.join(['docker', *args])], cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        (directory/(name+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError(f'{name} failed; inspect {directory/(name+".log")}')
    created = False
    switched = False
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        switched = True
        docker('start-isolated', 'compose', '-f','compose.yaml','-f',str(override),'--profile','app','up','-d','--wait')
        docker('browser', 'run','--rm','--network','host','--user',f'{os.getuid()}:{os.getgid()}',
               '--env-file','.env','-e','COMMERCE_WEB_URL='+os.environ.get('COMMERCE_WEB_URL','http://127.0.0.1:8080'),'-e','HOME=/tmp','-e','PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright',
               '-v',str(results)+':/workspace/artifacts','decisionops-commerce-browser:local')
        report = json.loads((results/'browser-report.json').read_text())
        stats = report['stats']
        if stats['expected'] < 5 or stats['skipped'] or stats['unexpected'] or stats['flaky']:
            raise RuntimeError('Required browser checks did not all execute successfully: '+str(stats))
        with engine.begin() as connection:
            count = connection.exec_driver_sql(f'SELECT count(*) FROM "{schema}".commerce_operations').scalar_one()
            assert count == 1, 'Browser flow must create exactly one operation'
        print('browser checks passed: superseded approval rejected, fresh replacement verified, incomplete history stays unknown')
        print('screenshots and logs: '+str(directory.relative_to(ROOT)))
    finally:
        # Restore before dropping: running workers must never point to deleted data.
        if switched:
            docker('restore-original', 'compose','--profile','app','up','-d','--wait')
        if created:
            with engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{graph_schema(schema)}" CASCADE')
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
    print('original store restored; only owned test schemas removed')


if __name__ == '__main__':
    main()
