"""Model-free frozen SQL comparison: python -m decisionops.commerce.comparison.

This is a controller-policy simulation using production projected SQL readers,
History, typed actions and choosers. SQLite mirrors frozen source records; it does
not measure PostgreSQL worker concurrency, browser latency, or live model quality.
The durable graph and execution guarantees have separate PostgreSQL acceptance.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import statistics
import time

import sqlalchemy as sa

from . import schema as db
from .adaptive_evidence import History, canonical
from .adaptive_investigations import allowed as permitted
from .adaptive_policies import Action, FixedOrder, CueRules, PolicyRequest, ORDER
from .adaptive_tools import DEPENDENCIES, read_tool
from .read_tools import AssessmentRequest
from .specialist_contracts import MockSpecialist, SpecialistRequest, validate_action
from .workflow_registry import LOST_SHIPMENT

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
MODES = ('rules', 'single_chooser', 'specialists')
BUDGETS = {'tool_attempts': 12, 'decisions': 16, 'per_tool': 2, 'specialist_decisions': 4,
           'decision_timeout_ms': 5000, 'deadline_seconds': 240}


@dataclass(frozen=True)
class FrozenCase:
    name: str
    expected: str
    change: str = ''
    report: str = 'Check stock and lost parcel'


# Expected labels are hand-assigned before running any controller.
CASES = (FrozenCase('eligible', 'proposed'),
         FrozenCase('already_replaced', 'blocked', 'replaced'),
         FrozenCase('carrier_unavailable', 'review', 'outage'),
         FrozenCase('conflicting_carrier', 'review', 'conflict'),
         FrozenCase('incomplete_history', 'review', 'incomplete'),
         FrozenCase('out_of_stock', 'blocked', 'stock'),
         FrozenCase('policy_denied', 'blocked', 'policy'),
         FrozenCase('stale_carrier', 'review', 'stale'),
         FrozenCase('stock_drift', 'blocked', 'drift'),
         FrozenCase('split_shipment', 'review', 'split'),
         FrozenCase('wrong_parcel_binding', 'review', 'wrong_scope'))


def source_snapshot(case):
    """Detached finite fictional rows; hash covers source events and drift script."""
    observed = NOW - timedelta(days=2) if case.change == 'stale' else NOW
    rows = {
        'policy_versions': [dict(id='P', store_id='demo', version=1, allow_confirmed_loss=case.change != 'policy', max_units=10, carrier_max_age_seconds=86400)],
        'orders': [dict(id='O', store_id='demo', policy_id='P', currency='EUR', resolution_history_complete=case.change != 'incomplete', compensation_revision=0)],
        'order_lines': [dict(order_id='O', variant_id='tote', quantity=1, unit_price_minor=2500)],
        'payments': [dict(order_id='O', status='paid', amount_minor=2500, currency='EUR')],
        'shipments': [dict(id='S', order_id='O', fulfilment_status='shipped', carrier_status='unknown' if case.change == 'conflict' else 'lost', carrier_observed_at=observed.isoformat())],
        'shipment_lines': [dict(shipment_id='S', order_id='O', variant_id='tote', quantity=1)],
        'inventory': [dict(store_id='demo', variant_id='tote', on_hand=0 if case.change == 'stock' else 3, reserved=0)],
        'resolutions': [dict(id='R', order_id='O', variant_id='tote', quantity=1, kind='replacement', operation_id=None)] if case.change == 'replaced' else [],
    }
    if case.change == 'wrong_scope':
        rows['orders'].append(dict(rows['orders'][0], id='OTHER'))
        rows['order_lines'].append(dict(rows['order_lines'][0], order_id='OTHER'))
        rows['shipments'][0]['order_id'] = 'OTHER'
        rows['shipment_lines'][0]['order_id'] = 'OTHER'
    if case.change == 'split':
        rows['shipments'].append(dict(rows['shipments'][0], id='S2'))
    return {'rows': rows, 'outage': case.change == 'outage', 'drift': case.change == 'drift',
            'carrier_projection': 'opposing_verified_terminal_events' if case.change == 'conflict' else 'single_verified_event',
            'clock': NOW.isoformat(), 'request': {'order_id': 'O', 'shipment_id': 'S', 'items': {'tote': 1}}}


def _mirror(snapshot):
    engine = sa.create_engine('sqlite://')
    metadata = sa.MetaData()
    for name in snapshot['rows']:
        source = db.metadata.tables[name]
        # ISO strings preserve UTC offsets through SQLite's DateTime read parser.
        sa.Table(name, metadata, *(sa.Column(c.name, sa.String() if isinstance(c.type, sa.DateTime) else c.type,
                                             primary_key=c.primary_key) for c in source.columns))
    metadata.create_all(engine)
    with engine.begin() as c:
        for name, rows in snapshot['rows'].items():
            if rows: c.execute(metadata.tables[name].insert(), rows)
    return engine


def _policy_request(history, choices, counts, decisions, report):
    return PolicyRequest('frozen-run', decisions, report, history.policy_view(NOW), tuple(choices),
                         tuple({'tool': t} for t, n in counts.items() for _ in range(n)),
                         {'tools': 12-sum(counts.values()), 'decisions': 16-decisions, 'seconds': 240}, ())


def evaluate(case, mode, *, attack=None):
    if mode not in MODES: raise ValueError('Unknown comparison mode')
    if attack not in (None, 'invalid_action', 'early_review', 'timeout'): raise ValueError('Unknown attack')
    snapshot = source_snapshot(case)
    engine = _mirror(snapshot)
    history = History(snapshot['request'])
    counts = Counter(); branch_decisions = Counter(); audit = []
    decisions = safety_reads = fallbacks = invalid_actions = timeouts = renewed = retry_reads = avoidable = 0
    drifted = attacked = False
    outcome = 'review'
    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            def outage(c, clause, *args):
                if (snapshot['outage'] and isinstance(clause, sa.sql.Select)
                        and any(col.table is db.shipments and col.name == 'carrier_status' for col in clause.selected_columns)):
                    raise sa.exc.SQLAlchemyError('Simulated carrier feed unavailable')
            sa.event.listen(connection, 'before_execute', outage)

            def read(tool, target):
                return read_tool(connection, tool, AssessmentRequest(**target.request), target, NOW,
                                 dependencies=tuple(target.select(dep, NOW) for dep in DEPENDENCIES[tool]))

            for _ in range(BUDGETS['decisions']):
                decisions += 1
                assessment = history.assess(NOW)
                choices = list(permitted(history, counts, {'tool_attempts': sum(counts.values())}, NOW))
                # Every mode uses the same supported-scope gate before reporting
                # a blocker, matching Commerce's final blocker authority.
                if not assessment['scope_complete'] or assessment['scope_reasons']:
                    choices = [a for a in choices if a.kind != 'report_blocker']
                request = _policy_request(history, choices, counts, decisions, case.report)
                owner = 'coordinator'
                if mode == 'specialists':
                    action = next((a for name in LOST_SHIPMENT.prerequisites for a in choices
                                   if a.kind == 'read' and a.tool == name), None)
                    # Retain both branches' successful evidence. Each owns two
                    # reads and a bounded retry, just as the durable dispatcher.
                    if action is None:
                        for branch in sorted(dict(LOST_SHIPMENT.branches), key=lambda b: (branch_decisions[b], b)):
                            reads = tuple(a for a in choices if a.kind == 'read' and a.tool in LOST_SHIPMENT.allowed_tools(branch))
                            if not reads or branch_decisions[branch] >= 4: continue
                            owner = branch
                            specialist = SpecialistRequest('frozen-run', 'call-'+str(decisions), branch,
                                branch_decisions[branch]+1, 'simulation', 1, 0, case.report,
                                history.policy_view(NOW), reads + (Action('request_review', reason='unknown_evidence'),),
                                tuple({'tool': t} for t in LOST_SHIPMENT.allowed_tools(branch) for _ in range(counts[t])),
                                {'decisions': 4-branch_decisions[branch], 'remaining_ms': 5000})
                            action = validate_action(specialist, MockSpecialist().choose(specialist))
                            branch_decisions[branch] += 1
                            break
                    if action is None:
                        # An unresolved exhausted specialist cannot be bypassed
                        # by a coordinator's stock read or a proposal choice.
                        complete = all(any(o.record()['status'] == 'success' and o.value is not None
                                           and not history.invalid_reason(o, NOW) for o in history.active(t))
                                       for _, tools in LOST_SHIPMENT.branches for t in tools)
                        action = FixedOrder().choose(request) if complete else Action('request_review', reason='unknown_evidence')
                else:
                    action = (FixedOrder() if mode == 'rules' else CueRules()).choose(request)
                requested = action.record()
                fallback = None
                if attack and not attacked:
                    attacked = True
                    if attack == 'early_review':
                        action = Action('request_review', reason='manual_review')
                        requested = action.record()
                    else:
                        try:
                            if attack == 'invalid_action':
                                requested = {'kind': 'execute'}
                                Action.from_record(requested)
                            else:
                                requested = {'error': 'decision_timeout'}
                                raise TimeoutError('Local fixture transport timeout')
                        except ValueError:
                            invalid_actions += 1
                        except TimeoutError:
                            timeouts += 1
                        fallbacks += 1
                        fallback = attack
                        action = FixedOrder().choose(request)
                # Only listed typed actions reach the scoped reader; safety reads
                # stay private and never populate missing policy evidence.
                if action not in choices: raise ValueError('Unlisted comparison action')
                entry = dict(sequence=decisions, owner=owner, requested=requested, applied=action.record(), fallback=fallback)
                audit.append(entry)
                if action.kind == 'read':
                    previous = history.active(action.tool)
                    if previous:
                        old = previous[-1]
                        if old.value is None or old.record()['status'] != 'success': retry_reads += 1
                        elif not history.invalid_reason(old, NOW): avoidable += 1
                        else: renewed += 1
                    obs = read(action.tool, history)
                    counts[action.tool] += 1
                    history.append(obs, supersedes=previous[-1].id if previous else None)
                    entry.update(observation_id=obs.id, result=obs.record()['status'], reason=obs.record()['reason'])
                    continue
                if action.kind == 'request_review':
                    entry['stop_reason'] = 'requested_review'
                    break
                if snapshot['drift'] and not drifted:
                    connection.execute(db.inventory.update().values(on_hand=0))
                    drifted = True
                safety = History(history.request)
                changed = []
                # All modes get identical mandatory safety policy. This harness
                # uses a full reread, conservatively more than subset blockers.
                for tool in ORDER:
                    obs = read(tool, safety); safety_reads += 1; safety.append(obs)
                    if not history.active(tool): continue  # An unread fact is never filled by safety.
                    try:
                        if history.select(tool, NOW).version != safety.select(tool, NOW).version: changed.append(tool)
                    except ValueError:
                        changed.append(tool)
                if changed:
                    invalidated = {o.id for tool in changed for o in history.active(tool)}
                    rebuilt = History(history.request, invalidated=invalidated)
                    predecessors = {new: old for old, new in history.supersessions}
                    for obs in history.observations: rebuilt.append(obs, supersedes=predecessors.get(obs.id))
                    history = rebuilt
                    entry.update(result='safety_drift', refresh_required=changed)
                    continue
                outcome = 'proposed' if action.kind == 'propose' else 'blocked'
                entry['stop_reason'] = 'complete_proposal' if outcome == 'proposed' else 'verified_blocker'
                break
            assessment = history.assess(NOW)
            valid = all(o.record()['request'] == history.request for o in history.observations)
            complete = all(v is not None for v in assessment['facts'].values()) and assessment['scope_complete'] and not assessment['scope_reasons']
            reads = sum(counts.values())
            elapsed = (time.perf_counter()-started)*1000
            return dict(case=case.name, mode=mode, attack=attack, expected=case.expected, outcome=outcome,
                        correct=outcome == case.expected, source_sha256=sha256(canonical(snapshot).encode()).hexdigest(),
                        budgets=dict(BUDGETS), policy_reads=reads, safety_reads=safety_reads,
                        repeated_reads=sum(max(0, n-1) for n in counts.values()),
                        avoidable_reads=avoidable,
                        stale_fact_renewals=renewed, retries=retry_reads,
                        fallbacks=fallbacks, invalid_actions=invalid_actions, timeouts=timeouts,
                        evidence_valid=valid, evidence_complete=complete, decisions=decisions,
                        latency_ms=round(elapsed, 3), policy='simulated', model_calls=0, observed_api_cost_usd=0,
                        followup_case_handling='separate_staff_acceptance',
                        facts=assessment['facts'], audit=audit)
    finally:
        engine.dispose()


def compare(*, adversarial=False):
    results = [evaluate(case, mode) for case in CASES for mode in MODES]
    if adversarial:
        results.extend(evaluate(CASES[0], mode, attack=attack) for mode in MODES
                       for attack in ('invalid_action', 'early_review', 'timeout'))
    summary = {}
    for mode in MODES:
        rows = [r for r in results if r['mode'] == mode]
        timings = sorted(r['latency_ms'] for r in rows)
        summary[mode] = dict(cases=len(rows), correct=sum(r['correct'] for r in rows),
                            incorrect=sum(not r['correct'] for r in rows),
                            policy_reads=sum(r['policy_reads'] for r in rows), safety_reads=sum(r['safety_reads'] for r in rows),
                            fallbacks=sum(r['fallbacks'] for r in rows), retries=sum(r['retries'] for r in rows),
                            latency_ms={'p50': statistics.median(timings), 'p95': timings[math.ceil(len(timings)*.95)-1], 'max': max(timings)})
    return dict(contract='commerce-frozen-comparison/v1', modes=list(MODES), clock=NOW.isoformat(),
                source_boundary='frozen SQLite source mirror; production SQL readers and policy/evidence contracts',
                timing_boundary='observed local simulation wall time; excludes PostgreSQL graph, network and live inference',
                safety_boundary='full private seven-tool reread on terminal proposal/blocker; counted separately',
                live_model_quality='unmeasured', live_model_cost_usd='unmeasured',
                future_live='Requires separate authorization; use these source hashes, budgets and expected labels unchanged with an explicit bounded transport; retain failed/early-review runs and record actual usage/cost.',
                results=results, summary=summary)


def compare_postgres(url):
    """Run the real fixed/cue services and specialist graph on identical sources.

    Every run owns and drops a freshly migrated schema. No source table in an
    existing application schema is touched. Expected outcomes remain frozen even
    when a controller stops early; those differences are scored as incorrect.
    """
    from contextlib import ExitStack
    from pathlib import Path
    from threading import Lock
    from unittest.mock import patch
    import uuid
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from .database import database_engine
    from . import adaptive_investigations as service, multi_agent as multi, multi_agent_workflow as graph, adaptive_jobs as jobs
    from .cases import open_case

    admin = database_engine(url)
    source_clock = datetime.now(timezone.utc)
    results = []
    try:
        for case in CASES:
            source = source_snapshot(case)
            for row in source['rows']['shipments']:
                prior = datetime.fromisoformat(row['carrier_observed_at'])
                row['carrier_observed_at'] = (source_clock+(prior-NOW)).isoformat()
            source['clock'] = source_clock.isoformat()
            source_hash = sha256(canonical(source).encode()).hexdigest()
            for mode in MODES:
                namespace = 'commerce_comparison_'+uuid.uuid4().hex
                with admin.begin() as c: c.exec_driver_sql('CREATE SCHEMA "'+namespace+'"')
                engine = database_engine(make_url(url).update_query_dict({'options': '-csearch_path='+namespace}))
                checkpoint_namespace = None
                try:
                    config = Config(str(Path(__file__).resolve().parents[2]/'alembic.ini'))
                    with engine.begin() as c:
                        config.attributes['connection'] = c
                        command.upgrade(config, 'head')
                        for name, rows in source['rows'].items():
                            records = json.loads(json.dumps(rows))
                            for record in records:
                                if 'carrier_observed_at' in record: record['carrier_observed_at'] = datetime.fromisoformat(record['carrier_observed_at'])
                            if records: c.execute(db.metadata.tables[name].insert(), records)
                    with engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
                        bound = open_case(c, AssessmentRequest(**source['request']))
                    measured = Counter(); guard = Lock(); drifted = [False]
                    original_reader = service.read_tool
                    original_bundled = service.read_assessment
                    def classify(connection):
                        while not hasattr(connection, 'info') and hasattr(connection, 'connection'):
                            connection = connection.connection
                        return 'policy' if getattr(connection, 'info', {}).get('adaptive_tool') else 'safety'
                    def measured_read(connection, tool, *args, **kwargs):
                        with guard: measured[classify(connection)+'_reads'] += 1
                        return original_reader(connection, tool, *args, **kwargs)
                    def measured_bundle(*args, **kwargs):
                        with guard: measured['safety_bundled_assessments'] += 1
                        return original_bundled(*args, **kwargs)
                    def outage(connection, clause, *args):
                        if (source['outage'] and isinstance(clause, sa.sql.Select)
                            and any(col.table is db.shipments and col.name == 'carrier_status' for col in clause.selected_columns)):
                            raise sa.exc.SQLAlchemyError('Simulated carrier source outage')
                    sa.event.listen(engine, 'before_execute', outage)
                    original_safety = service.safety_check
                    def drift_before_safety(connection, run, history):
                        if source['drift'] and not drifted[0]:
                            # A separate committed change before the production
                            # safety snapshot; no evidence or guard is fabricated.
                            with engine.begin() as other:
                                other.execute(db.inventory.update().values(on_hand=0))
                            drifted[0] = True
                        return original_safety(connection, run, history)
                    started = time.perf_counter()
                    with ExitStack() as stack:
                        stack.enter_context(patch.object(service, 'read_tool', measured_read))
                        stack.enter_context(patch.object(multi, 'read_tool', measured_read))
                        stack.enter_context(patch.object(service, 'read_assessment', measured_bundle))
                        stack.enter_context(patch.object(service, 'safety_check', drift_before_safety))
                        if mode == 'specialists':
                            run = multi.start(engine, bound['id'], case.report)
                            owned = jobs.claim(engine, job_id=run['job']['id'], action=jobs.SPECIALIST_ACTION)
                            checkpoint_namespace = graph.checkpoint_url(engine)[0]
                            saved = graph.run(engine, jobs.Fence(owned['id'], owned['token']))
                        else:
                            run = service.start(engine, bound['id'], case.report, policy='fixed' if mode == 'rules' else 'cue')
                            saved = service.drive(engine, run['id'])
                    elapsed = (time.perf_counter()-started)*1000
                    with service.transaction(engine, readonly=True) as c:
                        history, steps, observations, _, counts = service.snapshot(c, saved)
                        assessment = history.assess(datetime.now(timezone.utc))
                    outcome = 'proposed' if saved['state'] == 'proposed' else 'blocked' if saved['terminal'] and saved['terminal']['case_status'] == 'blocked' else 'review'
                    invalidations = {identifier for step in steps if step['kind'] == 'safety_drift' for identifier in step['data']['invalidated_ids']}
                    renewals = sum(old in invalidations for old, new in history.supersessions)
                    audit = [dict(sequence=step['sequence'], kind=step['kind'], data={k:v for k,v in step['data'].items() if k in
                             ('action','tool','status','reason','source','branches','fallback','unknowns','blockers','changed_tools','safety_tools','outcome')}) for step in steps]
                    results.append(dict(case=case.name, mode=mode, expected=case.expected, outcome=outcome,
                        correct=outcome == case.expected, state=saved['state'], source_sha256=source_hash,
                        budgets=dict(BUDGETS), policy_reads=saved['tool_attempts'], measured_policy_reads=measured['policy_reads'],
                        safety_reads=measured['safety_reads'], safety_bundled_assessments=measured['safety_bundled_assessments'],
                        repeated_reads=sum(max(0,n-1) for n in counts.values()),
                        avoidable_reads=sum(before['source_version']==after['source_version'] and before['value'] is not None and before['id'] not in invalidations
                            for tool in counts for before,after in zip(
                                [r['record'] for r in observations if r['applied'] and r['record']['tool']==tool],
                                [r['record'] for r in observations if r['applied'] and r['record']['tool']==tool][1:])),
                        expired_observations=sum(history.invalid_reason(o,datetime.now(timezone.utc))=='expired' for o in history.observations),
                        discarded_observations=sum(not r['applied'] for r in observations),
                        stale_fact_renewals=renewals,
                        retries=max(0,sum(max(0,n-1) for n in counts.values())-renewals),
                        fallbacks=sum(bool(step['data'].get('fallback')) for step in steps if step['kind']=='decision_reserved'),
                        invalid_actions=sum(step['kind']=='choice_rejected' for step in steps),
                        decisions=saved['decision_attempts'], latency_ms=round(elapsed,3),
                        evidence_valid=not saved.get('evidence_error') and all(row['record']['request']==saved['request'] for row in observations if row['applied']),
                        evidence_complete=assessment['scope_complete'] and not assessment['scope_reasons'] and all(v is not None for v in assessment['facts'].values()),
                        facts=assessment['facts'], terminal=saved['terminal'], audit=audit,
                        followup_case_handling='separate_staff_acceptance', model_calls=0, observed_api_cost_usd=0))
                finally:
                    engine.dispose()
                    with admin.begin() as c:
                        if checkpoint_namespace: c.exec_driver_sql('DROP SCHEMA IF EXISTS "'+checkpoint_namespace+'" CASCADE')
                        c.exec_driver_sql('DROP SCHEMA "'+namespace+'" CASCADE')
    finally:
        admin.dispose()
    summary = {}
    for mode in MODES:
        rows = [r for r in results if r['mode']==mode]
        timings = sorted(r['latency_ms'] for r in rows)
        summary[mode] = dict(cases=len(rows),correct=sum(r['correct'] for r in rows),incorrect=sum(not r['correct'] for r in rows),
            policy_reads=sum(r['policy_reads'] for r in rows), safety_reads=sum(r['safety_reads'] for r in rows),
            safety_bundled_assessments=sum(r['safety_bundled_assessments'] for r in rows),
            latency_ms={'p50':statistics.median(timings),'p95':timings[math.ceil(len(timings)*.95)-1],'max':max(timings)})
    return dict(contract='commerce-postgres-comparison/v1',modes=list(MODES),clock=source_clock.isoformat(),
        source_boundary='identical frozen authoritative rows in freshly migrated isolated PostgreSQL schemas',
        timing_boundary='observed local product service/graph latency, including specialist checkpoint setup; excludes migration and source loading',
        safety_boundary='actual projected safety tool calls and bundled safety assessments counted separately; no hidden evidence completion',
        evidence_validity_boundary='evidence_valid measures admitted provenance/scope; expiry, discarded rows and completeness are reported separately',
        live_model_quality='unmeasured',live_model_cost_usd='unmeasured',results=results,summary=summary)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adversarial', action='store_true')
    parser.add_argument('--postgres', action='store_true', help='Actual services/graph on isolated COMMERCE_TEST_DATABASE_URL schemas')
    args = parser.parse_args()
    if args.postgres:
        import os
        url = os.environ.get('COMMERCE_TEST_DATABASE_URL')
        if not url: parser.error('--postgres requires COMMERCE_TEST_DATABASE_URL')
        report = compare_postgres(url)
        if args.adversarial: report['adversarial_policy_simulation'] = compare(adversarial=True)
    else: report = compare(adversarial=args.adversarial)
    print(json.dumps(report, indent=2, default=str))


if __name__ == '__main__': main()
