"""Demonstrate failed local config rollout and rollback, then database recovery.

Temporarily interrupts the local workspace. Preserves images and persistent data.
Never starts paid services. Run only when the workspace is not in use.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    (ROOT / "runs").mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='release-walkthrough-', dir=ROOT/'runs'))
    def docker(name, *args):
        result = subprocess.run(['sg','docker','-c',shlex.join(['docker',*args])], cwd=ROOT, capture_output=True, text=True, timeout=180)
        (directory/(name+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError(f'{name} failed; see {directory}')
        return result.stdout
    def health():
        try:
            with urllib.request.urlopen(os.environ.get('COMMERCE_WEB_URL', 'http://127.0.0.1:8080')+'/health', timeout=8) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
        except (OSError, TimeoutError):
            return 0
    def await_status(expected, seconds=40):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            status = health()
            if status in expected:
                return status
            time.sleep(1)
        raise RuntimeError('Readiness did not reach expected state')
    def records(name):
        return docker(name,'compose','exec','-T','postgres','psql','-U','commerce','-d','commerce','-Atc',
                      "SELECT jsonb_build_object('orders',(SELECT count(*) FROM orders),'inventory',(SELECT jsonb_agg(to_jsonb(i) ORDER BY variant_id) FROM inventory i),'operations',(SELECT count(*) FROM commerce_operations))")
    before = records('records-before')
    images = {label:docker('image-'+label,'inspect',docker('container-'+service,'compose','ps','-q',service).strip(),'--format','{{.Image}}').strip() for label,service in (('app','api'),('web','web'))}
    (directory/'release.json').write_text(json.dumps({'schema':'0005','images':images,'scope':'local configuration rollout; same code and schema'},indent=2)+'\n')
    override = directory/'failed-config.yaml'
    override.write_text('services:\n  api:\n    command: [python, -c, "raise SystemExit(42)"]\n    restart: "no"\n')
    try:
        docker('failed-rollout','compose','-f','compose.yaml','-f',str(override),'--profile','app','up','-d','--no-deps','api')
        assert await_status({502,503}) in (502,503)
        end = time.monotonic()+15
        while time.monotonic()<end:
            state = json.loads(docker('failed-exit','inspect',docker('api-id','compose','ps','-aq','api').strip(),'--format','{{json .State}}'))
            if not state['Running']:
                break
            time.sleep(0.5)
        assert not state['Running'] and state['ExitCode'] == 42
        docker('rollback','compose','--profile','app','up','-d','--wait')
        assert await_status({200}) == 200
        actual = docker('restored-image','inspect',docker('restored-api-id','compose','ps','-q','api').strip(),'--format','{{.Image}}').strip()
        assert actual == images['app']
        print('bad configuration: API exit 42 and unavailable proxy; restored original image/config: ready')
        docker('stop-database','compose','stop','postgres')
        assert await_status({503}) == 503
        docker('outage-logs','compose','--profile','app','logs','--tail','10','worker')
        docker('recover-database','compose','up','-d','--wait','postgres')
        assert await_status({200}) == 200
        assert records('records-after') == before
        print('database outage: explicit 503; restart recovery: ready; checked records unchanged')
    finally:
        docker('ensure-recovered','compose','--profile','app','up','-d','--wait')
    print('release/recovery evidence: '+str(directory.relative_to(ROOT)))


if __name__ == '__main__':
    main()
