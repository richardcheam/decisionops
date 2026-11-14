"""Opt-in bounded mocked specialists. PostgreSQL owns effects, never model output.

Decisions are reserved/claimed/settled separately from read execution/admission.
Only the latter serializes on case/run; independent read transactions may overlap.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from queue import Queue, Empty
from threading import Event, Thread
import time
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from . import schema as db, adaptive_investigations as service, adaptive_jobs as jobs
from .adaptive_evidence import Observation, canonical
from .adaptive_tools import read_tool, DEPENDENCIES, PROJECTIONS
from .read_tools import AssessmentRequest
from .cases import clock, identifier
from .jobs import LeaseLost
from .adaptive_policies import Action

CONTRACT = 'commerce-specialists/v1'
OWNED = {'order': ('payment', 'fulfilment'), 'shipment': ('carrier_loss', 'fulfilment')}
REQUIRED = {'order': ('fulfilment', 'payment'), 'shipment': ('carrier_loss',)}


def start(engine, case_id, report, **kwargs):
    return service.start(engine, case_id, report, scheduled=True, specialists=True, **kwargs)


def calls(c, run_id, specialist=None):
    q = sa.select(db.specialist_calls).where(db.specialist_calls.c.run_id == run_id)
    if specialist: q = q.where(db.specialist_calls.c.specialist == specialist)
    return [dict(r) for r in c.execute(q.order_by(db.specialist_calls.c.created_at, db.specialist_calls.c.id)).mappings()]


def get(c, call_id):
    return dict(c.execute(sa.select(db.specialist_calls).where(db.specialist_calls.c.id == call_id).with_for_update()).mappings().one())


def current(engine, fence):
    with service.transaction(engine, readonly=True) as c:
        job = jobs.get(c, fence.job_id)
    return service.inspect(engine, job['run_id'])


def stopped(cancel):
    return cancel is not None and cancel.is_set()


def ready(history, tool, now):
    try:
        obs = history.select(tool, now)
        return obs.record()['status'] == 'success' and obs.value is not None
    except ValueError:
        return False


def result_status(c, run, specialist):
    rows = calls(c, run['id'], specialist)
    if any(r['state'] in ('dispatching', 'uncertain') for r in rows): return 'uncertain'
    if any(r['error'] or r['disposition'] == 'discarded' for r in rows): return 'review'
    history = service.snapshot(c, run)[0]
    if all(ready(history, tool, clock(c)) for tool in REQUIRED[specialist]): return 'complete'
    for obs in history.active():
        if obs.record()['tool'] not in REQUIRED[specialist]:continue
        if history.content_conflict(obs.record()['tool']):return 'conflicting'
        if history.invalid_reason(obs,clock(c)):return 'stale'
        if obs.record()['status']=='unavailable':return 'unavailable'
        if obs.value is None:return 'missing'
    return 'pending'


def specialist_result(c,run,specialist):
    from .specialist_contracts import SpecialistResult
    rows=calls(c,run['id'],specialist)
    ids=tuple(r['observation']['id'] for r in rows if r['observation'] and r['disposition']=='applied')
    return SpecialistResult(specialist,run['id'],run['generation'],run['case_revision'],result_status(c,run,specialist),ids,
        clock(c).isoformat(),min(run['deadline'],(rows[0]['created_at']+timedelta(seconds=60)) if rows else run['deadline']).isoformat(),
        next((r['error'] for r in rows if r['error']),None))


def support(engine, fence, tools=('order_manifest', 'replacement_policy'), cancel=None):
    for tool in tools:
        if stopped(cancel): return current(engine, fence)
        run = current(engine, fence)
        if run['state'] != 'active': return run
        with service.transaction(engine, readonly=True) as c:
            history = service.snapshot(c, run)[0]
            if ready(history, tool, clock(c)): continue
        # Supporting reads are explicit, deterministic, counted and separately labelled.
        if run['pending_token']: return run  # Interrupted coordinator read needs explicit recovery.
        run = service.advance(engine, run['id'], {'kind': 'read', 'tool': tool},
                              expected_context=run['context_version'], fence=fence)
        jobs.renew(engine, fence.job_id, fence.token)
    return current(engine, fence)


def reserve(engine, fence, specialist):
    from .specialist_contracts import SpecialistRequest
    if specialist not in OWNED: raise ValueError('Unknown specialist')
    run_id = current(engine, fence)['id']
    with service.guarded(engine, run_id, fence) as (c, run, case):
        if run['contracts'].get('specialists') != CONTRACT: raise ValueError('Wrong workflow contract')
        if run['state'] != 'active' or not service.matches(run, case): return None
        rows = calls(c, run_id, specialist)
        if rows and (rows[-1]['state'] != 'settled' or rows[-1]['disposition']=='pending'):
            return rows[-1]  # Reuse reservation, never repeat an unknown dispatch.
        if result_status(c, run, specialist) != 'pending': return None
        now = clock(c)
        branch_end = (rows[0]['created_at'] if rows else now) + timedelta(seconds=60)
        if len(rows) >= 4 or run['decision_attempts'] >= 16 or run['tool_attempts'] >= 12 or now >= branch_end: return None
        history, _, _, _, counts = service.snapshot(c, run)
        allowed = []
        for tool in OWNED[specialist]:
            # Shipment may explicitly refresh fulfilment; the returned carrier fact
            # still depends on that new observation. No hidden dependency queries.
            if ready(history, tool, now) and not (specialist == 'shipment' and tool == 'fulfilment'): continue
            if counts.get(tool, 0) >= 2: continue
            try:
                for dep in DEPENDENCIES[tool]: history.select(dep, now)
            except ValueError: continue
            allowed.append(Action('read', tool))
        if not allowed: return None
        allowed.append(Action('request_review', reason='unknown_evidence'))
        call_id = identifier('SCALL')
        projection = history.policy_view(now)
        visible = {'order_manifest', 'replacement_policy', *OWNED[specialist]}
        projection['observations'] = [o for o in projection['observations'] if o['tool'] in visible]
        request = SpecialistRequest(run_id, call_id, specialist, len(rows)+1, fence.token,
            run['generation'], run['case_revision'], run['report'], projection, tuple(allowed),
            tuple({'tool': r['tool'], 'status': r['tool_state']} for r in rows if r['tool']),
            {'decisions': 4-len(rows), 'remaining_ms': min(5000, max(1, int((min(run['deadline'], branch_end)-now).total_seconds()*1000)))})
        bound = {'policy': request.record(), 'dependencies': {a.tool: [list(history.select(dep, now).dependency()) for dep in DEPENDENCIES[a.tool]] for a in allowed if a.kind == 'read'},
                 'predecessors': {a.tool: next((o.id for o in history.active(a.tool)), None) for a in allowed if a.kind == 'read'}}
        c.execute(db.specialist_calls.insert().values(id=call_id, run_id=run_id, specialist=specialist, ordinal=len(rows)+1,
            created_token=fence.token, generation=run['generation'], case_revision=run['case_revision'],
            request=bound, request_hash=sha256(canonical(bound).encode()).hexdigest(), state='reserved',
            deadline=min(run['deadline'], branch_end, now+timedelta(seconds=5)), created_at=now))
        service.step(c, run, 'specialist_reserved', {'specialist': specialist, 'call_id': call_id,
            'source': 'mock_specialist', 'allowed_actions': [a.record() for a in allowed]}, decision_attempts=run['decision_attempts']+1)
        return get(c, call_id)


def bindings_valid(call, run, case, history, now, tool=None):
    if not service.matches(run, case) or run['state'] != 'active': return False
    if call['generation'] != run['generation'] or call['case_revision'] != run['case_revision']: return False
    if sha256(canonical(call['request']).encode()).hexdigest() != call['request_hash']: return False
    names = (tool,) if tool else call['request']['dependencies']
    for name in names:
        for dep in call['request']['dependencies'][name]:
            try:
                if list(history.select(dep[0], now).dependency()) != dep: return False
            except ValueError: return False
        old = next((o.id for o in history.active(name)), None)
        if old != call['request']['predecessors'][name]: return False
    return True


def uncertain(engine, call_id, token, reason):
    # Audit cleanup can settle only this already-dispatched call, never job/case authority.
    with service.transaction(engine) as c:
        call = get(c, call_id)
        if call['state'] == 'dispatching' and call['dispatch_token'] == token:
            c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == call_id).values(state='uncertain', error=reason[:80]))


def choose(engine, fence, call, adapter, cancel=None):
    from .specialist_contracts import SpecialistRequest, validate_action
    with service.guarded(engine, call['run_id'], fence) as (c, run, case):
        saved = get(c, call['id']); now = clock(c); history = service.snapshot(c, run)[0]
        if saved['state'] != 'reserved': return saved
        if stopped(cancel): return saved
        if now >= saved['deadline'] or not bindings_valid(saved, run, case, history, now):
            c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(state='settled', disposition='discarded', error='stale_before_dispatch'))
            return get(c, saved['id'])
        c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(
            state='dispatching', dispatch_count=1, dispatch_token=fence.token))
        service.step(c, run, 'specialist_dispatched', {'specialist': saved['specialist'], 'call_id': saved['id'], 'source': 'mock_specialist'})
    if stopped(cancel):
        uncertain(engine, call['id'], fence.token, 'shutdown_before_adapter'); return None
    signal = Event(); queue = Queue(maxsize=1); started = time.monotonic()
    request = SpecialistRequest.from_record(call['request']['policy'])
    def invoke():
        try: queue.put(('result', adapter.choose(request, signal)))
        except Exception as error: queue.put(('error', type(error).__name__))
    thread = Thread(target=invoke, daemon=True); thread.start(); received = None; error = None
    while not stopped(cancel):
        remaining = (call['deadline']-datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0: error = 'decision_deadline'; break
        try:
            kind, value = queue.get(timeout=min(.05, remaining))
            if kind == 'result': received = value
            else: error = value
            break
        except Empty:
            try:
                with service.transaction(engine, readonly=True) as c:
                    run = service.row(c, call['run_id']); fence.check(c, run, False)
                    case = c.execute(sa.select(db.cases).where(db.cases.c.id == run['case_id'])).mappings().one()
                    if not service.matches(run, case): raise LeaseLost('Case changed')
            except Exception: error = 'lease_or_state_lost'; break
    signal.set(); thread.join(timeout=.25)
    if received is None:
        uncertain(engine, call['id'], fence.token, error or 'worker_shutdown'); return None
    try: decision = validate_action(request, received).record()
    except (ValueError, TypeError): decision = {'kind': 'invalid'}; error = 'invalid_choice'
    try:
        with service.guarded(engine, call['run_id'], fence) as (c, run, case):
            saved = get(c, call['id']); history = service.snapshot(c, run)[0]
            if saved['state'] != 'dispatching' or saved['dispatch_token'] != fence.token: return None
            valid = clock(c) < saved['deadline'] and bindings_valid(saved, run, case, history, clock(c))
            c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(state='settled', decision=decision,
                elapsed_ms=int((time.monotonic()-started)*1000), error=error if valid else 'late_or_stale_result',
                disposition='pending' if valid and not error else 'discarded'))
            service.step(c, run, 'specialist_decision', {'specialist': saved['specialist'], 'call_id': saved['id'], 'action': decision,'tool':decision.get('tool'),
                'status': 'accepted' if valid and not error else 'discarded', 'source': 'mock_specialist'})
            return get(c, call['id'])
    except (LeaseLost, TimeoutError):
        uncertain(engine, call['id'], fence.token, 'late_or_unowned_result'); return None


def read(engine, fence, call, cancel=None):
    if stopped(cancel): return
    with service.guarded(engine, call['run_id'], fence) as (c, run, case):
        saved = get(c, call['id']); history, _, _, _, counts = service.snapshot(c, run); now = clock(c)
        action = saved['decision'] or {}
        if saved['state'] != 'settled' or saved['disposition'] != 'pending': return
        if action.get('kind') != 'read':
            c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(disposition='discarded', error='specialist_requested_review')); return
        tool = action['tool']
        if saved['tool_state'] != 'none': return  # Reserved/read interruptions require recovery, never redispatch.
        if (now>=saved['deadline'] or not bindings_valid(saved, run, case, history, now, tool) or run['tool_attempts'] >= 12 or counts.get(tool, 0) >= 2):
            c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(disposition='discarded', error='stale_read_binding')); return
        c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(tool=tool, tool_state='reserved'))
        run = service.step(c, run, 'specialist_read_reserved', {'specialist': saved['specialist'], 'call_id': saved['id'], 'tool': tool}, tool_attempts=run['tool_attempts']+1)
        c.execute(insert(db.adaptive_tool_counts).values(run_id=run['id'], tool=tool, attempts=1).on_conflict_do_update(
            index_elements=['run_id', 'tool'], set_={'attempts': db.adaptive_tool_counts.c.attempts+1}))
        c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(tool_state='reading'))
        branch_end = min(run['deadline'], calls(c, run['id'], saved['specialist'])[0]['created_at']+timedelta(seconds=60))
        dependencies = tuple(history.select(dep, now) for dep in DEPENDENCIES[tool])
    if stopped(cancel): return  # Persisted reading remains interrupted, no guessed result.
    with service.transaction(engine, readonly=True) as c:
        c.info['adaptive_tool'] = tool
        bounded = service.DeadlineConnection(c, branch_end)
        fence.check(bounded, run, False)
        obs = read_tool(bounded, tool, AssessmentRequest(**run['request']), history, clock(bounded), dependencies=dependencies)
    # Result history is immutable even when late, wrong-bound, or ownership changed.
    with service.transaction(engine) as raw:
        c = service.bounded_active(raw, run['id']); actual, case = service.locked(c, run['id'])
        try: fence.check(c, actual); owned = True
        except LeaseLost: owned = False
        saved = get(c, call['id']); now = clock(c); history = service.snapshot(c, actual)[0]
        applicable = (owned and not stopped(cancel) and now < branch_end and saved['tool_state'] == 'reading'
            and saved['disposition'] == 'pending' and bindings_valid(saved, actual, case, history, now, tool))
        try:
            record=obs.record()
            applicable=applicable and (record['tool']==tool and record['stream']=='primary'
                and canonical(record['request'])==canonical(actual['request'])
                and sorted(record['dependencies'])==sorted(saved['request']['dependencies'][tool]))
            if applicable:
                history.append(obs, supersedes=saved['request']['predecessors'][tool])
                if history.invalid_reason(obs, clock(c)): applicable = False
        except ValueError: applicable = False
        data = {'specialist': saved['specialist'], 'call_id': saved['id'], 'tool': tool,
                'observation_id': obs.id, 'status': obs.record()['status'], 'reason': obs.record()['reason'], 'applied': applicable}
        if actual['state'] == 'active':
            actual = service.step(c, actual, 'specialist_read_result', data); sequence = actual['context_version']
        else:
            sequence = c.execute(sa.select(sa.func.max(db.adaptive_steps.c.sequence)).where(db.adaptive_steps.c.run_id == actual['id'])).scalar_one()+1
            c.execute(db.adaptive_steps.insert().values(run_id=actual['id'], sequence=sequence, kind='specialist_read_result', data=data, created_at=now))
        c.execute(db.adaptive_observations.insert().values(id=obs.id, run_id=actual['id'], step_sequence=sequence, record=obs.record(), applied=applicable))
        if saved['observation'] is None and saved['tool_state']=='reading':
            c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(observation=obs.record(), tool_state='completed',
                disposition='applied' if applicable else 'discarded', error=None if applicable else 'late_or_stale_observation'))
        if applicable:
            old = saved['request']['predecessors'][tool]
            if old: c.execute(db.adaptive_supersessions.insert().values(run_id=actual['id'], old_id=old, new_id=obs.id))
            c.execute(insert(db.adaptive_active).values(run_id=actual['id'], tool=tool, stream='primary', observation_id=obs.id).on_conflict_do_update(
                index_elements=['run_id', 'tool', 'stream'], set_={'observation_id': obs.id}))
            fence.check(c, actual)


def branch(engine, fence, specialist, adapter=None, until_binding=False, cancel=None):
    from .specialist_contracts import MockSpecialist
    adapter = adapter or MockSpecialist()
    for _ in range(4):
        if stopped(cancel): break
        run = current(engine, fence)
        if run['state'] != 'active': break
        with service.transaction(engine, readonly=True) as c:
            history = service.snapshot(c, run)[0]
            if until_binding and ready(history, 'fulfilment', clock(c)): break
        jobs.renew(engine, fence.job_id, fence.token)
        call = reserve(engine, fence, specialist)
        if call is None: break
        if call['state'] == 'reserved': call = choose(engine, fence, call, adapter, cancel)
        if call is None or call['state'] != 'settled' or call['error']: break
        read(engine, fence, call, cancel)
    return current(engine, fence)


def recover(engine, fence):
    run = current(engine, fence)
    if run['pending_token']:
        service.recover(engine, run['id'], expected_context=run['context_version'], fence=fence)
    with service.guarded(engine, run['id'], fence) as (c, run, case):
        if run['state'] != 'active': return run
        for saved in calls(c, run['id']):
            updates = {}
            if saved['state'] == 'dispatching': updates.update(state='uncertain', error='interrupted_decision')
            if saved['tool_state'] in ('reserved', 'reading'):
                if saved['tool_state'] == 'reserved':
                    c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(tool_state='reading'))
                updates.update(tool_state='interrupted', error='interrupted_read', disposition='discarded')
            if updates:
                c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id == saved['id']).values(**updates))
                run = service.step(c, run, 'specialist_recovery', {'specialist': saved['specialist'], 'call_id': saved['id'], 'reason': updates['error'], 'source': 'operator_recovery'})
    return current(engine, fence)


def join(engine, fence, cancel=None):
    if stopped(cancel): return current(engine, fence)
    run = current(engine, fence)
    if run['state'] != 'active': return run
    with service.transaction(engine, readonly=True) as c:
        states = {name: result_status(c, run, name) for name in OWNED}
    if all(v == 'complete' for v in states.values()):
        run = support(engine, fence, ('compensation_history', 'inventory'), cancel)
    if stopped(cancel) or run['state'] != 'active': return run
    with service.guarded(engine, run['id'], fence) as (c, run, case):
        history = service.snapshot(c, run)[0]
        assessment = history.assess(clock(c))
        run = service.step(c, run, 'specialist_join', {'branches': states, 'unknowns': assessment['decision']['unknowns'],
            'blockers': assessment['decision']['blockers'], 'scope_complete': assessment['scope_complete'], 'source': 'deterministic'})
    if not all(v == 'complete' for v in states.values()): action = {'kind': 'request_review', 'reason': 'manual_review'}
    elif assessment['decision']['status'] == 'eligible_to_propose': action = {'kind': 'propose'}
    elif assessment['decision']['blockers']: action = {'kind': 'report_blocker'}
    else: action = {'kind': 'request_review', 'reason': 'unknown_evidence'}
    result = service.advance(engine, run['id'], action, expected_context=run['context_version'], fence=fence)
    # Drift may return active to permit explicit refresh. Specialists never silently
    # fill safety gaps; publish an honest review after the recorded invalidation.
    if result['state'] == 'active':
        result = service.advance(engine, run['id'], {'kind': 'request_review', 'reason': 'manual_review'}, expected_context=result['context_version'], fence=fence)
    if result['state'] != 'active': jobs.complete(engine, fence)
    return result


def trace(engine, run_id):
    with service.transaction(engine,readonly=True) as c:
        run=service.inspect_connection(c,run_id)
        saved=calls(c,run_id)
        history=service.snapshot(c,run)[0]
        active={o.id:o for o in history.active()}
        branches=[specialist_result(c,run,name).record() for name in OWNED]
    return {'specialists':branches,'contract': CONTRACT, 'mode': 'mocked-model-choices', 'run_id': run_id, 'case_id': run['case_id'],
        'generation': run['generation'], 'case_revision': run['case_revision'], 'request':run['request'],'state': run['state'],
        'elapsed_ms': int(((run['steps'][-1]['created_at'] if run['state']!='active' else datetime.now(timezone.utc))-run['created_at']).total_seconds()*1000),
        'budgets': {k:run[k] for k in ('decision_attempts','tool_attempts')}, 'terminal': run['terminal'],
        'steps': [{k:s[k] for k in ('sequence','kind','created_at')} | {'data':{k:v for k,v in s['data'].items() if k in ('specialist','call_id','action','tool','observation_id','status','reason','applied','source','branches','unknowns','blockers','scope_complete','outcome')}} for s in run['steps']],
        'calls': [{k:r[k] for k in ('id','specialist','ordinal','request_hash','state','dispatch_count','decision','tool','tool_state','disposition','error','elapsed_ms')} for r in saved],
        'evidence': [{'id':o['id'],'tool':o['tool'],'value':o['value'] if o['id'] in active and not history.invalid_reason(active[o['id']],datetime.now(timezone.utc)) and not history.content_conflict(o['tool']) else None,'status':o['status'],
            'applicability':'current' if o['id'] in active and not history.invalid_reason(active[o['id']],datetime.now(timezone.utc)) and not history.content_conflict(o['tool']) else 'unapplied_or_invalid','source_version':o['source_version'],'observed_at':o['observed_at'],'expires_at':o['expires_at'],
            'source':{'order_id':o['request']['order_id'],'shipment_id':o['request']['shipment_id'],
                'declared_queries':[{'table':table,'columns':list(columns)} for table,columns in PROJECTIONS[o['tool']]]}} for o in run['observations']],
        'api_charge_usd': '0', 'export_enabled': False}


def main():
    """Explicit local inspection/recovery; never loads a provider or model."""
    import argparse, json
    from .database import database_engine
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('inspect','resume','recover'))
    p.add_argument('identity',help='run ID for inspect; job ID for resume/recover')
    args=p.parse_args();engine=database_engine()
    try:
        if args.action=='inspect':result=trace(engine,args.identity)
        else:
            owned=jobs.claim(engine,job_id=args.identity,action=jobs.SPECIALIST_ACTION)
            if owned is None:raise ValueError('Not claimable: inspect lease, deadline or terminal state; no token override')
            fence=jobs.Fence(owned['id'],owned['token'])
            if args.action=='recover':result=recover(engine,fence)
            else:
                from .multi_agent_workflow import run
                result=run(engine,fence)
            result=trace(engine,result['id'])
        print(json.dumps(result,indent=2,default=str))
    finally:engine.dispose()
if __name__=='__main__':main()
