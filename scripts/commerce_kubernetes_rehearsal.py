"""Rehearse the same app on an explicitly named disposable kind cluster.

Requires built/loaded local images, kubectl, and operator-supplied synthetic secrets.
Never creates a cloud cluster, changes Docker permissions or changes another namespace.
Run browser acceptance against the forwarded deployment separately; this script's
health and rollout checks alone do not establish the customer/staff browser workflow.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'decisionops-local-portfolio'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True, help='Explicit kind-* disposable context')
    parser.add_argument('--kubectl', default='kubectl')
    parser.add_argument('--port', type=int, default=8166)
    parser.add_argument('--app-image', required=True, help='Built and loaded app image tagged with candidate SHA')
    parser.add_argument('--web-image', required=True, help='Built and loaded web image tagged with candidate SHA')
    args = parser.parse_args()
    if not args.context.startswith('kind-'):
        parser.error('Only explicit disposable kind-* contexts are accepted')
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged local port')
    required = {'COMMERCE_STAFF_PASSWORD': 'COMMERCE_DEMO_PASSWORD', 'COMMERCE_HELPER_PASSWORD': 'COMMERCE_HELPER_PASSWORD',
                'COMMERCE_CUSTOMER_CAMILLE_PASSWORD': 'COMMERCE_CUSTOMER_CAMILLE_PASSWORD', 'COMMERCE_CUSTOMER_ALEX_PASSWORD': 'COMMERCE_CUSTOMER_ALEX_PASSWORD'}
    secrets = {}
    for key, source in required.items():
        value = os.environ.get(source, '')
        if len(value) < 16:
            parser.error(f'Set {source} to a synthetic password of at least 16 characters')
        secrets[key] = value
    if len(set(secrets.values())) != len(secrets):
        parser.error('Use different synthetic passwords for every identity')
    # Unique ephemeral database credential, never printed or written to disk.
    import uuid
    database_password = uuid.uuid4().hex
    secrets.update(POSTGRES_PASSWORD=database_password, COMMERCE_DATABASE_URL=f'postgresql+psycopg://portfolio:{database_password}@postgres:5432/portfolio')
    import yaml
    base = [args.kubectl, '--context', args.context]
    def run(*argv, input=None, capture=False, timeout=180):
        return subprocess.run([*base, *argv], input=input, capture_output=capture, text=True, check=True, timeout=timeout, cwd=ROOT)
    def scoped(*argv, **kwargs):
        return run('-n', NAMESPACE, *argv, **kwargs)
    def apply_application(filename):
        objects = list(yaml.safe_load_all((ROOT / 'deploy/kubernetes' / filename).read_text()))
        for obj in objects:
            pod = obj.get('spec', {}).get('template', {}).get('spec', {})
            for container in pod.get('containers', []):
                if container['image'] == 'decisionops-github-demo-app:local':
                    container['image'] = args.app_image
                elif container['image'] == 'decisionops-github-demo-web:local':
                    container['image'] = args.web_image
        scoped('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}))
    # Verify explicit context before any mutation. Namespace is dedicated synthetic.
    run('cluster-info', capture=True, timeout=15)
    run('apply', '-f', 'deploy/kubernetes/namespace.yaml')
    existing = scoped('get', 'secret', 'decisionops-credentials', '--ignore-not-found', '-o', 'name', capture=True).stdout.strip()
    if existing:
        parser.error('This namespace already has credentials. Use a fresh disposable cluster; existing data is preserved.')
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'decisionops-credentials', 'namespace': NAMESPACE},
              'type': 'Opaque', 'data': {key: base64.b64encode(value.encode()).decode() for key, value in secrets.items()}}
    scoped('create', '-f', '-', input=json.dumps(secret))
    scoped('apply', '-f', 'deploy/kubernetes/config.yaml', '-f', 'deploy/kubernetes/postgres.yaml')
    scoped('patch', 'configmap', 'decisionops-config', '--type=merge', '-p', json.dumps({'data': {'COMMERCE_ORIGINS': f'http://127.0.0.1:{args.port},http://localhost:{args.port}'}}))
    scoped('rollout', 'status', 'statefulset/postgres', '--timeout=180s')
    apply_application('migrate.yaml')
    scoped('wait', '--for=condition=complete', 'job/decisionops-migrate', '--timeout=180s')
    apply_application('application.yaml')
    for name in ('api', 'worker', 'staff-investigator', 'web'):
        scoped('rollout', 'status', 'deployment/' + name, '--timeout=180s')
    forwarding = subprocess.Popen([*base, '-n', NAMESPACE, 'port-forward', '--address=127.0.0.1', 'service/web', f'{args.port}:8080'], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = []
    try:
        def health():
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/health', timeout=2) as response:
                        if response.status == 200:
                            return
                except OSError:
                    pass
                time.sleep(.2)
            raise RuntimeError('Deployed web/API did not become healthy')
        health()
        checks.append('web and API readiness')
        # Exercise actual interruption/replacement of worker Pods. For business
        # recovery/uniqueness, run the browser/SQL checks documented in the guide.
        for name in ('worker', 'staff-investigator'):
            scoped('delete', 'pods', '-l', 'app=' + name, '--wait=true')
            scoped('rollout', 'status', 'deployment/' + name, '--timeout=120s')
        health()
        checks.append('worker Pod replacement and restored readiness')
        # Observe the injected failure on the new replica before rolling it back.
        def api_template():
            return json.loads(scoped('get', 'deployment/api', '-o', 'json', capture=True).stdout)['spec']['template']

        original = api_template()
        scoped('patch', 'deployment', 'api', '--type=strategic', '-p', json.dumps({
            'spec': {'template': {'metadata': {'labels': {'decisionops-test': 'failed-release'}},
                                  'spec': {'containers': [{'name': 'api', 'command': ['python', '-c', 'raise SystemExit(73)']}]}}}
        }))
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                pods = json.loads(scoped('get', 'pods', '-l', 'decisionops-test=failed-release',
                                         '-o', 'json', capture=True).stdout)['items']
                terminated = [
                    phase.get('terminated', {}).get('exitCode')
                    for pod in pods for status in pod.get('status', {}).get('containerStatuses', [])
                    for phase in (status.get('state', {}), status.get('lastState', {}))
                ]
                if 73 in terminated:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Failed API rollout never reached injected exit 73')
        finally:
            scoped('rollout', 'undo', 'deployment/api')
            scoped('rollout', 'status', 'deployment/api', '--timeout=120s')
        if api_template() != original:
            raise RuntimeError('Rollback did not restore the original API pod template')
        health()
        checks.append('failed application process exit 73, original API template restored, and rollback readiness')
        print(json.dumps({'status': 'passed', 'context': args.context, 'namespace': NAMESPACE, 'app_image': args.app_image, 'web_image': args.web_image, 'checks': checks,
                          'browser_and_business_recovery': 'run separately; not established by readiness checks',
                          'cleanup': f'kubectl --context {args.context} delete namespace {NAMESPACE}'}))
    finally:
        forwarding.terminate()
        try:
            forwarding.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forwarding.kill()
            forwarding.wait()


if __name__ == '__main__':
    main()
