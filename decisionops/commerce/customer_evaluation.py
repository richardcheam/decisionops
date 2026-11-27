"""Compare rules and optional typed adapters on disposable synthetic customer flows."""

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
from threading import Lock
import time
from unittest.mock import patch
import uuid

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from .database import database_engine
from .local_llm import LocalModel

EXPECTED = {
    'resolution': 'replacement_created',
    'ambiguity': 'clarify',
    'wrong_owner': 'denied',
    'stale_evidence': 'review',
    'carrier_outage': 'review',
}
CASES = tuple(EXPECTED)
DEFAULT_CASES = tuple({
    'name': name, 'message': 'My parcel never arrived. Please report it missing.',
    'staff_message': 'Fix this', 'expected': expected,
} for name, expected in EXPECTED.items())


class LocalBenchmarkModel(LocalModel):
    """Use the product transport with a shared lock, hard cap and attempt ledger."""

    def __init__(self, model, endpoint, max_calls):
        super().__init__(model, endpoint)
        if self.host not in ('127.0.0.1', '::1', 'localhost'):
            raise ValueError('Benchmark requires a loopback Ollama origin')
        if self.host == 'localhost':
            self.host = '127.0.0.1'
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError('Provide a positive physical model call cap')
        self.max_calls = max_calls
        self.lock = Lock()
        self.case = None
        self.calls = []
        self.blocked = dict.fromkeys(('cap', 'uncertain', 'cancelled'), 0)
        self.uncertain = False
        self.wait_ms = 0

    def configured_model(self, *, model=None):
        if model is not None and model != self.model:
            raise ValueError('Worker requested a different model than the benchmark')
        return self

    def _check_dispatch(self, *, cancelled=False):
        reason = ('cancelled' if cancelled else 'uncertain' if self.uncertain
                  else 'cap' if len(self.calls) >= self.max_calls else None)
        if reason:
            self.blocked[reason] += 1
            raise RuntimeError('Benchmark skipped model dispatch')

    def route(self, request):
        waiting = time.monotonic()
        with self.lock:
            self.wait_ms = (time.monotonic() - waiting) * 1000
            self._check_dispatch(cancelled=self.wait_ms >= 500)
            return super().route(request)

    def specialist(self, request, *, timeout_ms, cancel):
        waiting = time.monotonic()
        with self.lock:
            self.wait_ms = (time.monotonic() - waiting) * 1000
            remaining = timeout_ms - int(self.wait_ms)
            self._check_dispatch(cancelled=remaining <= 100 or (cancel is not None and cancel.is_set()))
            return super().specialist(request, timeout_ms=remaining, cancel=cancel)

    def _choose(self, instruction, features, field, options, timeout):
        call = {
            'case': self.case,
            'role': features.get('role', 'specialist'),
            'lock_wait_ms': round(self.wait_ms, 3),
        }
        if 'specialist' in features:
            call['specialist'] = features['specialist']
        self.calls.append(call)
        started = time.monotonic()
        try:
            choice = super()._choose(instruction, features, field, options, timeout)
        except TimeoutError:
            self.uncertain = True
            call['status'] = 'timeout'
            raise
        except (OSError, http.client.HTTPException):
            self.uncertain = True
            call['status'] = 'transport_error'
            raise
        except ValueError:
            call['status'] = 'invalid'
            raise
        else:
            call.update(status='valid', choice=choice[field])
            if field == 'index':
                action = features['allowed_actions'][choice[field]]
                call['action'] = action['kind']
                if 'tool' in action:
                    call['tool'] = action['tool']
            return choice
        finally:
            call['transport_ms'] = round((time.monotonic() - started) * 1000, 3)


def validate_cases(cases):
    if not isinstance(cases, (tuple, list)) or not cases:
        raise ValueError('Case plan must be a nonempty JSON array')
    labels = set()
    for case in cases:
        if not isinstance(case, dict) or not {'name', 'message', 'staff_message', 'expected'} <= case.keys():
            raise ValueError('Each case needs name, message, staff_message and expected')
        for key in ('name', 'expected', 'message', 'staff_message', 'label'):
            if not isinstance(case.get(key, ''), str) or len(case.get(key, '').encode()) > 2000:
                raise ValueError('Use bounded strings in the case plan')
        if case['name'] not in CASES or not case['expected'].strip():
            raise ValueError('Unknown case scenario or empty expected outcome')
        if case['name'] != 'wrong_owner' and not all(
                case[key].strip() for key in ('message', 'staff_message')):
            raise ValueError('Non-ownership scenarios need both conversation messages')
        label = case.get('label', case['name'])
        if label in labels or not label.strip():
            raise ValueError('Use distinct nonempty case labels')
        labels.add(label)


def simulated_transport(payload):
    from .role_actions import DemoCustomerRouter, DemoStaffRouter

    if payload['role'] == 'customer':
        return {'kind': DemoCustomerRouter().choose(payload['message']).kind}
    if payload['role'] == 'staff':
        return {'kind': DemoStaffRouter().choose(payload['message']).kind}
    allowed = payload['features']['allowed_actions']
    return next((a for a in allowed if a['kind'] == 'read'), allowed[0])


def write_counts(engine, *, effects_only=False):
    from . import schema as db

    tables = (db.operations, db.replacement_orders, db.reservations)
    if not effects_only:
        tables = (db.customer_reports, db.proposals, db.reviews, *tables)
    with engine.connect() as c:
        return {
            table.name: c.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in tables
        }


def run_flow(client, engine, case, adapter, row):
    from . import adaptive_jobs as jobs, multi_agent_workflow as graph, schema as db
    from . import staff_investigations as staff, worker

    name = case['name']
    owner = 'alex' if name in ('wrong_owner', 'carrier_outage') else 'camille'
    customer_auth = (owner, 'fictional-evaluation-' + owner)
    staff_auth = ('operator', 'fictional-evaluation-staff')
    if name == 'wrong_owner':
        response = client.get('/customer-api/orders/DEMO-LYON', auth=customer_auth)
        return 'denied' if response.status_code == 404 else f'wrong_owner_http_{response.status_code}'

    order = {'ambiguity': 'DEMO-SPLIT', 'carrier_outage': 'DEMO-OUTAGE'}.get(name, 'DEMO-LYON')
    conversation = client.post('/customer-api/conversations', json={}, auth=customer_auth)
    conversation.raise_for_status()
    customer_path = '/customer-api/conversations/' + conversation.json()['id']
    selected = client.post(customer_path + '/select', auth=customer_auth, json={
        'order_id': order, 'shipment_id': None if name == 'ambiguity' else 'PARCEL-' + order,
    })
    selected.raise_for_status()
    response = client.post(customer_path + '/messages', auth=customer_auth, json={
        'message': case['message'], 'request_id': 'FROZEN-REPORT',
    })
    if response.status_code != 200:
        return 'customer_unavailable' if response.status_code == 503 else f'customer_http_{response.status_code}'
    reply = response.json()
    row['customer_intent'] = reply['intent']
    if not reply.get('case_id'):
        return reply['intent']
    case_id = reply['case_id']

    conversation = client.post('/api/conversations', json={}, auth=staff_auth)
    conversation.raise_for_status()
    staff_path = '/api/conversations/' + conversation.json()['id']
    client.post(staff_path + '/select', json={'case_id': case_id}, auth=staff_auth).raise_for_status()
    investigation = client.post(staff_path + '/messages', auth=staff_auth, json={
        'message': case['staff_message'], 'request_id': 'FROZEN-INVESTIGATION',
    })
    if investigation.status_code != 200:
        return ('staff_unavailable' if investigation.status_code == 503
                else f'staff_http_{investigation.status_code}')
    reply = investigation.json()
    row['staff_intent'] = reply['intent']
    if not reply.get('investigation'):
        return 'staff_' + reply['intent']
    if adapter is None:
        staff.work_once(engine)
    else:
        with engine.connect() as c:
            job_id = c.execute(sa.select(db.adaptive_jobs.c.id).where(
                db.adaptive_jobs.c.run_id == reply['investigation']['id'])).scalar_one()
        claimed = jobs.claim(engine, job_id=job_id, action=jobs.SPECIALIST_ACTION)
        graph.run(engine, jobs.Fence(claimed['id'], claimed['token']),
                  adapters={'order': adapter, 'shipment': adapter})

    case_path = '/api/cases/' + case_id
    response = client.get(case_path, auth=staff_auth)
    response.raise_for_status()
    saved = response.json()
    investigation = saved['shipment_investigation']
    if investigation:
        row['investigation_state'] = investigation['state']
        row['investigation_reason'] = investigation['reason']
        row['specialists'] = [
            {k: item[k] for k in ('specialist', 'state', 'disposition', 'error', 'tool') if k in item}
            for item in investigation['specialists']
        ]
    proposal = saved['proposal']
    if name != 'resolution' or proposal is None:
        return 'review' if saved['status'] == 'needs_review' and proposal is None else saved['status']
    phases = row['write_checkpoints'] = {'before_approval': write_counts(engine, effects_only=True)}
    if any(phases['before_approval'].values()):
        return 'write_before_approval'
    approved = client.post(case_path + '/review', auth=staff_auth, json={
        'generation': saved['generation'], 'proposal_id': proposal['id'],
        'content_hash': proposal['content_hash'], 'decision': 'approve',
    })
    if approved.status_code != 200:
        return f'approval_http_{approved.status_code}'
    phases['before_confirmation'] = write_counts(engine, effects_only=True)
    if any(phases['before_confirmation'].values()):
        return 'write_before_confirmation'
    confirmed = client.post(case_path + '/execute', auth=staff_auth, json={
        'operation_id': approved.json()['approval']['operation_id'],
    })
    if confirmed.status_code != 202:
        return f'execution_http_{confirmed.status_code}'
    phases['before_execution_worker'] = write_counts(engine, effects_only=True)
    if any(phases['before_execution_worker'].values()):
        return 'write_before_execution_worker'
    result = worker.work_once(engine)
    if result['event'] != 'job_result':
        return result['event']
    response = client.get(customer_path, auth=customer_auth)
    response.raise_for_status()
    public = response.json()['cases'][0]
    details = client.get(case_path, auth=staff_auth)
    details.raise_for_status()
    operation = details.json()['operation']
    row['operation_status'] = operation['status'] if operation else None
    row['customer_shipped'] = public['shipped']
    exactly_one = all(count == 1 for count in write_counts(engine, effects_only=True).values())
    return ('replacement_created' if exactly_one and row['operation_status'] == 'verified'
            and public['replacement_created'] and not public['shipped'] else 'unverified')


def evaluate(url, *, simulate_adapter=False, adapter=None, model=None, max_calls=None, cases=DEFAULT_CASES):
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    from . import multi_agent_workflow as graph, schema as db
    from .api import create_app
    from .customer_seed import seed as customer_seed
    from .delivery_seed import seed as delivery_seed
    from .role_actions import ModelActionAdapter
    from .seed import seed
    from .workflow import graph_schema, setup_checkpoints

    if make_url(url).host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Use disposable loopback PostgreSQL')
    if sum((simulate_adapter, adapter is not None, model is not None)) > 1:
        raise ValueError('Choose simulation, local model or explicitly injected adapter')
    if model is None and max_calls is not None:
        raise ValueError('Specify a physical call cap with a local model')
    validate_cases(cases)
    local = None
    modes = [('rules', 'rules', None)]
    if simulate_adapter:
        modes.append(('adapter_simulation', 'mock-specialists', ModelActionAdapter(simulated_transport)))
    elif adapter is not None:
        modes.append(('injected_adapter', 'mock-specialists', adapter))
    elif model is not None:
        local = LocalBenchmarkModel(model, os.environ.get('COMMERCE_OLLAMA_URL', 'http://127.0.0.1:11434'), max_calls)
        modes.append(('local_model', 'llm', None))

    scope = patch.object(LocalModel, 'from_environment', new=local.configured_model) if local else nullcontext()
    frozen = datetime.now(timezone.utc).replace(microsecond=0)
    runs = []
    admin = database_engine(url)
    try:
        with scope:
            for case in cases:
                rules_hash = None
                for mode, product_mode, current_adapter in modes:
                    schema = 'customer_eval_' + uuid.uuid4().hex
                    with admin.begin() as c:
                        c.exec_driver_sql('CREATE SCHEMA ' + schema)
                    engine = database_engine(make_url(url).update_query_dict({'options': '-csearch_path=' + schema}))
                    specialist_schema = None
                    try:
                        cfg = Config('alembic.ini')
                        with engine.begin() as c:
                            cfg.attributes['connection'] = c
                            command.upgrade(cfg, 'head')
                        seed(engine, observed_at=frozen)
                        delivery_seed(engine, frozen)
                        customer_seed(engine)
                        setup_checkpoints(engine)
                        if case['name'] == 'stale_evidence':
                            with engine.begin() as c:
                                c.execute(db.policies.insert().values(
                                    id='evaluation-short-freshness', store_id='demo-store', version=1001,
                                    allow_confirmed_loss=True, max_units=10, carrier_max_age_seconds=30,
                                ))
                                c.execute(db.orders.update().where(db.orders.c.id == 'DEMO-LYON').values(
                                    policy_id='evaluation-short-freshness',
                                ))
                        with engine.connect() as c:
                            source = {
                                table.name: [dict(row) for row in c.execute(
                                    sa.select(table).order_by(*table.primary_key.columns)).mappings()]
                                for table in (db.orders, db.order_lines, db.shipments, db.shipment_lines, db.payments,
                                              db.policies, db.inventory, db.resolutions, db.carrier_events,
                                              db.delivery_parcels, db.customers, db.customer_orders)
                            }
                        source_hash = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()
                        if mode == 'rules':
                            rules_hash = source_hash
                        elif source_hash != rules_hash:
                            raise ValueError('Compared modes have different seeded business inputs')
                        if product_mode != 'rules':
                            specialist_schema = graph.checkpoint_url(engine)[0]
                        app = create_app(engine, username='operator', store_id='demo-store',
                                         password='fictional-evaluation-staff', action_adapter=current_adapter,
                                         staff_investigation_mode=product_mode, customer_accounts={
                                             owner: {'customer_id': owner, 'password': 'fictional-evaluation-' + owner}
                                             for owner in ('camille', 'alex')
                                         })
                        label = case.get('label', case['name'])
                        row = {
                            'case': label, 'scenario': case['name'], 'mode': mode,
                            'source_hash': source_hash, 'expected': case['expected'],
                        }
                        calls_before = 0
                        if product_mode == 'llm':
                            with local.lock:
                                local.case = label
                                calls_before = len(local.calls)
                        started = time.monotonic()
                        with TestClient(app) as client:
                            outcome = run_flow(client, engine, case, current_adapter, row)
                        row['observed_local_ms'] = round((time.monotonic() - started) * 1000, 3)
                        if product_mode == 'llm':
                            with local.lock:
                                row['physical_model_calls'] = len(local.calls) - calls_before
                        row['writes'] = write_counts(engine)
                        if outcome != 'replacement_created' and any(
                                row['writes'][table.name] for table in (db.operations, db.replacement_orders, db.reservations)):
                            row['unexpected_effects'] = True
                        row.update(outcome=outcome, matches_expected=outcome == case['expected'])
                        if row.get('unexpected_effects'):
                            row['matches_expected'] = False
                        runs.append(row)
                    finally:
                        engine.dispose()
                        with admin.begin() as c:
                            for drop in (specialist_schema, graph_schema(schema), schema):
                                if drop:
                                    c.exec_driver_sql('DROP SCHEMA IF EXISTS '
                                                      + c.dialect.identifier_preparer.quote(drop) + ' CASCADE')
    finally:
        admin.dispose()

    result = {
        'contract': 'customer-staff-comparison/v1',
        'population': [case.get('label', case['name']) for case in cases],
        'fixture_as_of': frozen.isoformat(),
        'case_plan_sha256': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
        'runs': runs,
        'interpretation': 'Frozen synthetic flows. Local calls are serialized and workflow timing includes that constraint.',
        'paid_model_calls': 0 if adapter is None else None,
        'live_model_quality': None,
        'live_model_latency_ms': None,
        'live_model_cost_usd': None,
        'live_model_status': 'measured on the listed synthetic flows' if local else 'unmeasured',
        'hosted_traces_exported': False,
    }
    if local:
        result['local_model'] = {
            'model': model, 'max_calls': max_calls, 'physical_calls': len(local.calls),
            'timeouts': sum(call['status'] == 'timeout' for call in local.calls),
            'invalid_replies': sum(call['status'] == 'invalid' for call in local.calls),
            'transport_errors': sum(call['status'] == 'transport_error' for call in local.calls),
            'blocked': local.blocked, 'uncertain_generation': local.uncertain, 'calls': local.calls,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--simulate-adapter', action='store_true')
    modes.add_argument('--local-model', metavar='MODEL')
    parser.add_argument('--cases', type=Path)
    parser.add_argument('--max-calls', type=int)
    args = parser.parse_args()
    url = os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:
        parser.error('Set disposable loopback COMMERCE_TEST_DATABASE_URL')
    try:
        cases = json.loads(args.cases.read_text()) if args.cases else DEFAULT_CASES
        report = evaluate(url, simulate_adapter=args.simulate_adapter, model=args.local_model,
                          max_calls=args.max_calls, cases=cases)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
