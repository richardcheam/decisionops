"""Offline contract checks for the delivered Compose/Kubernetes packaging.

Requires PyYAML for deployment tooling only; never contacts Docker, a Kubernetes
API, AWS, telemetry or a model. Successful parsing is not a deployment claim.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify():
    import yaml
    compose = yaml.safe_load((ROOT / 'compose.yaml').read_text())
    services = compose['services']
    assert set(('postgres', 'init', 'api', 'worker', 'staff-investigator', 'web')) <= services.keys()
    command = ' '.join(services['init']['command'])
    assert command.index('alembic upgrade head') < command.index('commerce.customer_seed') < command.index('commerce.worker setup')
    for name in ('COMMERCE_CUSTOMER_CAMILLE_PASSWORD', 'COMMERCE_CUSTOMER_ALEX_PASSWORD'):
        assert ':?' in services['api']['environment'][name], 'Explicit separate customer credentials required'
    assert services['api']['environment']['COMMERCE_STAFF_INVESTIGATION_MODE'].endswith(':-rules}')
    assert services['worker']['command'][-1] == 'run'
    assert 'decisionops.commerce.staff_investigations' in services['staff-investigator']['command']
    assert services['init']['environment']['LANGSMITH_TRACING'] == 'false'
    assert services['init']['environment']['LANGCHAIN_TRACING_V2'] == 'false'
    assert '127.0.0.1:' in services['web']['ports'][0]
    for name in ('api', 'worker', 'staff-investigator'):
        assert services[name]['read_only'] is True
        assert services[name]['cap_drop'] == ['ALL']
    base = ROOT / 'deploy/kubernetes'
    kustomization = yaml.safe_load((base / 'kustomization.yaml').read_text())
    objects = [obj for filename in kustomization['resources'] for obj in yaml.safe_load_all((base / filename).read_text()) if obj]
    keys = [(obj['kind'], obj['metadata']['name']) for obj in objects]
    assert len(keys) == len(set(keys)), 'Duplicate Kubernetes object identity'
    indexed = dict(zip(keys, objects))
    assert indexed[('Namespace', 'decisionops-local-portfolio')]['metadata']['labels']['decisionops.synthetic-only'] == 'true'
    workloads = [obj for obj in objects if obj['kind'] in ('Deployment', 'StatefulSet', 'Job')]
    for obj in workloads:
        template = obj['spec']['template']
        assert template['spec']['automountServiceAccountToken'] is False
        for container in template['spec']['containers']:
            assert 'requests' in container['resources'] and 'limits' in container['resources']
            assert container.get('imagePullPolicy') != 'Always', 'Local images must be loadable'
    deployments = {obj['metadata']['name']: obj for obj in objects if obj['kind'] == 'Deployment'}
    assert set(deployments) == {'api', 'worker', 'staff-investigator', 'web'}
    for name in ('api', 'worker', 'staff-investigator'):
        pod = deployments[name]['spec']['template']['spec']
        container = pod['containers'][0]
        assert pod['securityContext']['runAsNonRoot'] is True
        assert container['securityContext']['readOnlyRootFilesystem'] is True
        if name == 'api':
            assert {'secretRef': {'name': 'decisionops-credentials'}} in container['envFrom']
        else:
            assert all('secretRef' not in item for item in container['envFrom'])
            assert container['env'] == [{'name': 'COMMERCE_DATABASE_URL', 'valueFrom': {'secretKeyRef': {'name': 'decisionops-credentials', 'key': 'COMMERCE_DATABASE_URL'}}}], 'Workers receive only database credentials'
    migrate = indexed[('Job', 'decisionops-migrate')]
    migration_command = ' '.join(migrate['spec']['template']['spec']['containers'][0]['command'])
    assert migration_command == command, 'Compose and Kubernetes must migrate/seed the same app'
    for name in ('api', 'web', 'postgres'):
        service = indexed[('Service', name)]
        workload = indexed[('StatefulSet' if name == 'postgres' else 'Deployment', name)]
        labels = workload['spec']['template']['metadata']['labels']
        assert all(labels.get(key) == value for key, value in service['spec']['selector'].items())
    for config in ((ROOT / 'docker/nginx.conf').read_text(), indexed[('ConfigMap', 'decisionops-nginx')]['data']['default.conf']):
        assert 'location /customer-api/' in config
        assert 'location /api/' in config
        assert 'Authorization $http_authorization' in config
        assert 'try_files $uri $uri/ /index.html' in config
    assert '127.0.0.11' not in indexed[('ConfigMap', 'decisionops-nginx')]['data']['default.conf'], 'Docker DNS is not cluster DNS'
    assert not any(obj['kind'] == 'Secret' for obj in objects), 'Credentials are created from runtime input, not committed'
    return {'status': 'passed', 'checks': ['single Compose same-app startup', 'explicit customer credentials', 'worker commands and readonly mounts', 'Kubernetes object/selectors/resources', 'migration-seed parity', 'customer and staff proxy routes', 'no committed Kubernetes secrets'], 'kubernetes_objects': len(objects), 'runtime': 'not established by offline checks'}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
