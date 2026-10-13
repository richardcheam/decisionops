"""Backup the local demo and prove restoration in a separate disposable database.

Never overwrites the running commerce database. Retains a private dump artifact.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    (ROOT / "runs").mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='backup-walkthrough-', dir=ROOT/'runs'))
    directory.chmod(0o700)
    dump = directory/'commerce.dump'
    database = 'restore_check_' + uuid.uuid4().hex
    def command(*args, **kwargs):
        return subprocess.run(['sg','docker','-c',shlex.join(['docker','compose','exec','-T','postgres',*args])], cwd=ROOT, check=True, **kwargs)
    descriptor = os.open(dump, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        command('pg_dump','-U','commerce','-d','commerce','-Fc',stdout=output)
    created = False
    try:
        command('createdb','-U','commerce',database)
        created = True
        with dump.open('rb') as source:
            command('pg_restore','-U','commerce','-d',database,'--exit-on-error',stdin=source,stdout=subprocess.DEVNULL)
        checks = {}
        for table in ('orders','order_lines','inventory','resolutions','commerce_cases','commerce_operations','commerce_jobs'):
            query = f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM public.{table} t"
            original = command('psql','-U','commerce','-d','commerce','-Atc',query,capture_output=True).stdout
            restored = command('psql','-U','commerce','-d',database,'-Atc',query,capture_output=True).stdout
            if original != restored:
                raise RuntimeError(f'{table}: source changed during verification or restore mismatch; do not use as verified backup')
            checks[table] = {'rows':len(json.loads(restored)), 'sha256':hashlib.sha256(restored).hexdigest()}
        revision = command('psql','-U','commerce','-d',database,'-Atc','SELECT version_num FROM alembic_version',capture_output=True).stdout.decode().strip()
        assert revision == '0005'
        graph = command('psql','-U','commerce','-d',database,'-Atc',"SELECT count(*) FROM information_schema.tables WHERE table_schema='commerce_graph'",capture_output=True).stdout.decode().strip()
        assert int(graph) > 0
        (directory/'verification.json').write_text(json.dumps({'revision':revision,'graph_tables':int(graph),'records':checks},indent=2)+'\n')
        print('private pg_dump restored successfully; business records match; migration and graph tables present')
        print('backup and verification: '+str(directory.relative_to(ROOT)))
    finally:
        if created:
            command('dropdb','-U','commerce',database)
    print('only the disposable restore database was dropped; running store unchanged')


if __name__ == '__main__':
    main()
