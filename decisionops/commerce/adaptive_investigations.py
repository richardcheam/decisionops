"""Durable optional model-free investigation; no provider, queue or graph.

Case -> run -> business lock order. Tool work occurs outside those locks in a
separate READ ONLY transaction. PostgreSQL is authoritative for steps and limits.
"""
from contextlib import contextmanager
from datetime import timedelta
import json
import math
import time

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError, TimeoutError as QueryDeadline

from . import schema as db
from .adaptive_evidence import CONTRACT, History, Observation, TOOLS, SCOPE_TOOLS, canonical, observation
from .adaptive_tools import DEPENDENCIES, read_tool
from .adaptive_policies import ACTION_CONTRACT, Action, PolicyRequest, FixedOrder, CueRules, FakePolicy, REVIEW_REASONS
from .cases import clock, event, identifier, lock_case, lock_business
from .read_tools import AssessmentRequest, read_assessment
from .proposals import build_proposal, document_hash


class DeadlineConnection:
    """Real server statement/lock timeouts, recomputed before every statement."""
    def __init__(self, connection, deadline):
        self.connection=connection
        remaining=(deadline-clock(connection)).total_seconds()
        self.end=time.monotonic()+max(0,remaining)

    def __getattr__(self,name):
        return getattr(self.connection,name)

    def limits(self):
        remaining=self.end-time.monotonic()
        if remaining<=0:raise QueryDeadline('Investigation deadline reached')
        milliseconds=max(1,min(5000,int(remaining*1000)))
        self.connection.exec_driver_sql(f"SET LOCAL statement_timeout = {milliseconds}")
        self.connection.exec_driver_sql(f"SET LOCAL lock_timeout = {milliseconds}")

    def execute(self,*args,**kwargs):
        self.limits();return self.connection.execute(*args,**kwargs)

    def exec_driver_sql(self,*args,**kwargs):
        self.limits();return self.connection.exec_driver_sql(*args,**kwargs)


@contextmanager
def transaction(engine, *, readonly=False):
    isolation='REPEATABLE READ' if readonly else 'READ COMMITTED'
    with engine.connect().execution_options(isolation_level=isolation) as c,c.begin():
        c.exec_driver_sql('SET LOCAL statement_timeout = 5000')
        c.exec_driver_sql('SET LOCAL lock_timeout = 5000')
        if readonly:c.exec_driver_sql('SET TRANSACTION READ ONLY')
        yield c


def row(connection,run_id,lock=False):
    q=sa.select(db.adaptive_runs).where(db.adaptive_runs.c.id==run_id)
    if lock:q=q.with_for_update()
    saved=connection.execute(q).mappings().one_or_none()
    if saved is None:raise ValueError('Adaptive run not found')
    return dict(saved)


def bounded_active(connection,run_id):
    """Bootstrap immutable deadline without row locks; expired runs get audit cleanup only.

    Cleanup/inspection has a separate five-second statement bound and may never
    dispatch business reads. A lock timeout rolls back; inspect/recover explicitly.
    """
    saved=row(connection,run_id)
    if saved['state']=='active' and clock(connection)<saved['deadline']:
        return DeadlineConnection(connection,saved['deadline'])
    return connection


def locked(connection,run_id):
    first=row(connection,run_id)
    case=lock_case(connection,first['case_id'])
    return row(connection,run_id,True),case


def step(connection,run,kind,data,**updates):
    version=run['context_version']+1
    values={'context_version':version,**updates}
    updated=connection.execute(db.adaptive_runs.update().where(sa.and_(
        db.adaptive_runs.c.id==run['id'],db.adaptive_runs.c.context_version==run['context_version']))
        .values(**values).returning(db.adaptive_runs)).mappings().one()
    connection.execute(db.adaptive_steps.insert().values(run_id=run['id'],sequence=version,
                        kind=kind,data=json.loads(canonical(data)),created_at=clock(connection)))
    return dict(updated)


def snapshot(connection,run):
    steps=[dict(r) for r in connection.execute(sa.select(db.adaptive_steps).where(
        db.adaptive_steps.c.run_id==run['id']).order_by(db.adaptive_steps.c.sequence)).mappings()]
    observations=[dict(r) for r in connection.execute(sa.select(db.adaptive_observations).where(
        db.adaptive_observations.c.run_id==run['id']).order_by(db.adaptive_observations.c.step_sequence)).mappings()]
    edges=[dict(r) for r in connection.execute(sa.select(db.adaptive_supersessions).where(
        db.adaptive_supersessions.c.run_id==run['id'])).mappings()]
    invalidated={identifier for s in steps if s['kind']=='safety_drift' for identifier in s['data']['invalidated_ids']}
    history=History(run['request'],invalidated=invalidated)
    predecessors={edge['new_id']:edge['old_id'] for edge in edges}
    for saved in observations:
        if not saved['applied']:continue
        record=dict(saved['record']);identifier=record.pop('id');observed=record.pop('observed_at');expires=record.pop('expires_at')
        version=record.pop('source_version')
        obs=Observation(identifier,canonical(record),observed,expires)
        if obs.version!=version:raise ValueError('Stored observation content hash mismatch')
        history.append(obs,supersedes=predecessors.get(identifier))
    active={(o.record()['tool'],o.record()['stream']):o.id for o in history.active()}
    pointers={(r['tool'],r['stream']):r['observation_id'] for r in connection.execute(
        sa.select(db.adaptive_active).where(db.adaptive_active.c.run_id==run['id'])).mappings()}
    if active!=pointers:raise ValueError('Active observation pointers do not match immutable history')
    counts={r['tool']:r['attempts'] for r in connection.execute(sa.select(db.adaptive_tool_counts).where(
        db.adaptive_tool_counts.c.run_id==run['id'])).mappings()}
    return history,steps,observations,edges,counts


def matches(run,case):
    return (case['generation']==run['generation'] and case['case_revision']==run['case_revision']
            and case['request']==run['request'] and case['order_id']==run['request']['order_id']
            and case['status']=='needs_review')


def summary(history,now):
    assessment=history.assess(now)
    return dict(decision=assessment['decision'],unknowns=assessment['decision']['unknowns'],
                unread_tools=[tool for tool in TOOLS if not history.active(tool)],
                unresolved_scope=[tool for tool in SCOPE_TOOLS if not history.active(tool)
                    or any(history.invalid_reason(o,now) or not o.record()['scope_known']
                           or history.content_conflict(tool) for o in history.active(tool))],
                scope_reasons=assessment['scope_reasons'],scope_complete=assessment['scope_complete'])


class BlockerValidationConnection:
    """Lock only the projected rows of already-collected selected tools."""
    def __init__(self,connection):self.connection=connection
    def execute(self,query,*args,**kwargs):
        return self.connection.execute(query.with_for_update(),*args,**kwargs)


def validate_blocker(connection,run,history):
    """Private subset confirmation; never gather unread conditions or publish facts."""
    now=clock(connection);assessment=history.assess(now)
    needed={tool for tool,fact in TOOLS.items() if fact in assessment['decision']['blockers']}
    if assessment['scope_complete'] and not assessment['scope_reasons']:
        needed.update(SCOPE_TOOLS)
    # Expired false observations cannot become a report just because selection
    # saw them earlier. Retain their IDs as explicit invalidation feedback.
    expired={o.record()['tool'] for o in history.active() if o.value is False and history.invalid_reason(o,now)}
    if not assessment['decision']['blockers']:return sorted(expired),[]
    def dependencies(tool):
        for dep in DEPENDENCIES[tool]:
            if dep not in needed:needed.add(dep);dependencies(dep)
    for tool in tuple(needed):dependencies(tool)
    selected=[tool for tool in DEPENDENCIES if tool in needed]
    changed=set(expired)
    bounded=DeadlineConnection(connection,run['deadline'])
    private=History(run['request'])
    for tool in selected:
        before=history.select(tool,clock(bounded))
        obs=read_tool(BlockerValidationConnection(bounded),tool,AssessmentRequest(**run['request']),
                      private,clock(bounded),dependencies=tuple(private.select(dep,clock(bounded)) for dep in DEPENDENCIES[tool]))
        private.append(obs)
        if obs.version!=before.version:changed.add(tool)
    # Recheck collected and private freshness after all locks/reads have completed.
    now=clock(bounded)
    for tool in selected:
        try:
            if history.select(tool,now).version!=private.select(tool,now).version:changed.add(tool)
        except ValueError:changed.add(tool)
    return sorted(changed),selected


def finish(connection,run,case,history,reason, *, blocker=False,stale=False):
    if blocker and not stale:
        changed=[];selected=[]
        try:
            with connection.begin_nested() as guard:
                try:changed,selected=validate_blocker(connection,run,history)
                except (SQLAlchemyError,ValueError):
                    guard.rollback()
                    changed=list({o.record()['tool'] for o in history.active() if o.value is False}
                                 | {tool for tool in SCOPE_TOOLS if history.active(tool)})
        finally:
            # Once work expires, only separately bounded audit cleanup is allowed.
            raw=connection.connection if isinstance(connection,DeadlineConnection) else connection
            if clock(raw)>=run['deadline']:
                raw.exec_driver_sql('SET LOCAL statement_timeout = 5000')
                raw.exec_driver_sql('SET LOCAL lock_timeout = 5000')
                connection=raw
        if changed:
            run=step(connection,run,'safety_drift',{'reason':'blocker_binding_changed',
                     'changed_tools':changed,'safety_tools':selected,
                     'invalidated_ids':[o.id for tool in changed for o in history.active(tool)]})
            history,_,_,_,counts=snapshot(connection,run)
            now=clock(connection)
            refresh=(all(counts.get(tool,0)<2 for tool in changed)
                     and len(changed)<=12-run['tool_attempts']
                     and len(changed)<16-run['decision_attempts'])
            if now<run['deadline'] and run['decision_attempts']<16 and refresh:return run
            blocker=False
    now=clock(connection);report=summary(history,now)
    blocker=blocker and not stale and now<run['deadline'] and bool(report['decision']['blockers'])
    supported=report['scope_complete'] and not report['scope_reasons']
    case_status='blocked' if blocker and supported else 'needs_review'
    if not stale:
        connection.execute(db.cases.update().where(db.cases.c.id==case['id']).values(
            status=case_status,approval_id=None,updated_at=now))
        event(connection,case['id'],'adaptive_finished',{'run_id':run['id'],'reason':reason,'blocker_report':blocker},now)
    terminal={**report,'reason':reason,'case_status':case['status'] if stale else case_status,
              'execution_authorized':False,'outcome':'stale' if stale else ('observed_blocker' if blocker else 'review')}
    state='stale' if stale else ('blocker_reported' if blocker else 'review')
    return step(connection,run,'terminal',terminal,state=state,pending_token=None,pending_context=None,terminal=terminal)


def start(engine,case_id,report, *, deadline_seconds=240,policy='fixed'):
    if not isinstance(report,str) or len(report.encode('utf-8'))>2000:raise ValueError('Report must be at most 2000 UTF-8 bytes')
    if type(deadline_seconds) not in (int,float) or not math.isfinite(deadline_seconds) or not 0<deadline_seconds<=240:
        raise ValueError('Deadline must be positive and at most 240 seconds')
    if policy not in ('fixed','cue','fake-override','fake-invalid','fake-unavailable','fake-refuse'):
        raise ValueError('Unknown model-free policy')
    with transaction(engine) as c:
        case=lock_case(c,case_id)
        if case['status']=='executed':raise ValueError('Executed cases cannot start adaptive investigation')
        if c.execute(sa.select(db.adaptive_runs.c.id).where(sa.and_(
            db.adaptive_runs.c.case_id==case_id,db.adaptive_runs.c.state=='active'))).first():
            raise ValueError('Case already has an active adaptive run')
        request=AssessmentRequest(**case['request'])
        if request.order_id!=case['order_id']:raise ValueError('Case/order request binding mismatch')
        now=clock(c)
        updated=c.execute(db.cases.update().where(db.cases.c.id==case_id).values(
            generation=case['generation']+1,status='needs_review',investigation_id=None,
            proposal_id=None,approval_id=None,updated_at=now).returning(db.cases)).mappings().one()
        run_id=identifier('ARUN')
        c.execute(db.adaptive_runs.insert().values(id=run_id,case_id=case_id,generation=updated['generation'],
            case_revision=updated['case_revision'],request=json.loads(canonical(case['request'])),report=report,
            contracts={'observations':CONTRACT,'actions':ACTION_CONTRACT,'policy':policy},
            state='active',created_at=now,deadline=now+timedelta(seconds=deadline_seconds)))
        run=row(c,run_id)
        step(c,run,'started',{'superseded_approval_id':case['approval_id'],'case_revision':updated['case_revision']})
        event(c,case_id,'adaptive_started',{'run_id':run_id,'generation':updated['generation'],
              'superseded_approval_id':case['approval_id']},now)
    return inspect(engine,run_id)


def allowed(history,counts,run,now):
    choices=[];assessment=history.assess(now)
    if assessment['decision']['status']=='eligible_to_propose':choices.append(Action('propose'))
    if assessment['decision']['blockers']:choices.append(Action('report_blocker'))
    if run['tool_attempts']<12:
        for tool,deps in DEPENDENCIES.items():
            if counts.get(tool,0)>=2:continue
            active=history.active(tool)
            if active and all(not history.invalid_reason(o,now) and o.record()['status']=='success'
                              and o.value is not None for o in active) and not history.content_conflict(tool):continue
            try:
                for dep in deps:history.select(dep,now)
            except ValueError:continue
            choices.append(Action('read',tool))
    choices.extend(Action('request_review',reason=reason) for reason in REVIEW_REASONS)
    return tuple(choices)


def request_for(run,history,steps,counts,now):
    attempts=tuple({'tool':s['data']['action']['tool'],'status':'attempted'} for s in steps
                   if s['kind']=='decision_reserved' and s['data']['action']['kind']=='read')
    feedback=tuple(s['data']['reason'] for s in steps if s['kind'] in ('choice_rejected','safety_drift'))[-8:]
    return PolicyRequest(run['id'],run['context_version'],run['report'],history.policy_view(now),
        allowed(history,counts,run,now),attempts,
        {'tools':12-run['tool_attempts'],'decisions':16-run['decision_attempts'],
         'seconds':max(0,(run['deadline']-now).total_seconds())},feedback)


def inspect(engine,run_id):
    with transaction(engine,readonly=True) as c:
        run=row(c,run_id);history,steps,observations,edges,counts=snapshot(c,run);now=clock(c)
        return {**run,'steps':steps,'observations':[r['record'] for r in observations],
                'supersessions':edges,'tool_counts':counts,'assessment':history.assess(now)}


def policy_request(engine,run_id):
    with transaction(engine,readonly=True) as c:
        c=bounded_active(c,run_id)
        run=row(c,run_id);history,steps,observations,edges,counts=snapshot(c,run)
        return request_for(run,history,steps,counts,clock(c))


def safety_check(connection,run,history):
    """Private safety attestation: return changed names, never replacement observations."""
    bounded=DeadlineConnection(connection,run['deadline'])
    lock_business(bounded,AssessmentRequest(**run['request']))
    safety=History(run['request'])
    for tool,deps in DEPENDENCIES.items():
        obs=read_tool(bounded,tool,AssessmentRequest(**run['request']),safety,clock(bounded),
                      dependencies=tuple(safety.select(dep,clock(bounded)) for dep in deps))
        safety.append(obs)
    changed=[tool for tool in TOOLS if history.select(tool,clock(bounded)).version
             != safety.select(tool,clock(bounded)).version]
    return changed,bounded


def publish(connection,run,case,history):
    try:
        changed,bounded=safety_check(connection,run,history)
    except (SQLAlchemyError,ValueError):
        # A failed safety transaction must roll back its savepoint before audit writes.
        raise
    if changed:
        ids=[o.id for tool in changed for o in history.active(tool)]
        return step(connection,run,'safety_drift',{'reason':'safety_binding_changed','changed_tools':changed,
                    'invalidated_ids':ids,'safety_tools':list(TOOLS)},pending_token=None,pending_context=None)
    now=clock(bounded)
    if history.assess(now)['decision']['status']!='eligible_to_propose':
        return step(connection,run,'safety_drift',{'reason':'evidence_expired','changed_tools':list(TOOLS),
                    'invalidated_ids':[o.id for o in history.active()]},pending_token=None,pending_context=None)
    current=read_assessment(bounded,AssessmentRequest(**run['request']),now)
    document=build_proposal(current)
    if document is None:
        return step(connection,run,'safety_drift',{'reason':'legacy_safety_unresolved','changed_tools':list(TOOLS),
                    'invalidated_ids':[o.id for o in history.active()]},pending_token=None,pending_context=None)
    # Check a fresh clock immediately before publishing the immutable legacy snapshot.
    now=clock(bounded)
    if now>=run['deadline'] or history.assess(now)['decision']['status']!='eligible_to_propose':
        return finish(connection,run,case,history,'deadline_or_expiry')
    investigation_id=identifier('INV');proposal_id=identifier('PROP')
    bounded.execute(db.investigations.insert().values(id=investigation_id,order_id=run['request']['order_id'],
                    created_at=now,assessment=json.loads(canonical(current))))
    bounded.execute(db.proposals.insert().values(id=proposal_id,investigation_id=investigation_id,
                    created_at=now,document=document,content_hash=document_hash(document)))
    bounded.execute(db.cases.update().where(db.cases.c.id==case['id']).values(status='awaiting_review',
                    investigation_id=investigation_id,proposal_id=proposal_id,approval_id=None,updated_at=now))
    event(bounded,case['id'],'adaptive_proposed',{'run_id':run['id'],'proposal_id':proposal_id},now)
    terminal={**summary(history,now),'case_status':'awaiting_review','outcome':'proposal',
              'proposal_id':proposal_id,'investigation_id':investigation_id,'execution_authorized':False}
    return step(bounded,run,'terminal',terminal,state='proposed',pending_token=None,pending_context=None,terminal=terminal)


def advance(engine,run_id,raw_action, *, expected_context,fallback=False):
    dispatch=None
    with transaction(engine) as c:
        c=bounded_active(c,run_id)
        run,case=locked(c,run_id)
        if run['state']!='active':return inspect(engine,run_id)
        if run['context_version']!=expected_context or run['pending_token']:
            raise ValueError('Stale context or pending read; inspect/recover before advancing')
        history,steps,observations,edges,counts=snapshot(c,run);now=clock(c)
        if not matches(run,case):finish(c,run,case,history,'case_changed',stale=True)
        elif now>=run['deadline']:finish(c,run,case,history,'run_deadline')
        elif run['decision_attempts']>=16:finish(c,run,case,history,'decision_budget_exhausted',
            blocker=bool(history.assess(now)['decision']['blockers']))
        elif run['tool_attempts']>=12 and history.assess(now)['decision']['status']!='eligible_to_propose':
            finish(c,run,case,history,'tool_budget_exhausted',blocker=bool(history.assess(now)['decision']['blockers']))
        else:
            try:
                request=request_for(run,history,steps,counts,now)
            except ValueError:
                finish(c,run,case,history,'policy_context_too_large')
            else:
                try:
                    action=raw_action if isinstance(raw_action,Action) else Action.from_record(raw_action)
                    if action not in request.allowed:raise ValueError('Choice not eligible')
                except (ValueError,TypeError):
                    step(c,run,'choice_rejected',{'reason':'policy_unavailable' if isinstance(raw_action,dict) and raw_action.get('kind')=='policy_unavailable' else 'invalid_or_ineligible_action',
                         'submitted_kind':str(raw_action.get('kind',''))[:64] if isinstance(raw_action,dict) else 'typed_action', 'fallback':fallback,
                         'features':request.features()},decision_attempts=run['decision_attempts']+1)
                else:
                    token=identifier('READ') if action.kind=='read' else None
                    run=step(c,run,'decision_reserved',{'action':action.record(),'fallback':fallback,
                         'features':request.features(),'token':token},decision_attempts=run['decision_attempts']+1,
                         tool_attempts=run['tool_attempts']+(action.kind=='read'),pending_token=token,
                         pending_context=run['context_version']+1 if token else None)
                    if action.kind=='read':
                        c.execute(insert(db.adaptive_tool_counts).values(run_id=run_id,tool=action.tool,attempts=1)
                            .on_conflict_do_update(index_elements=['run_id','tool'],set_={'attempts':db.adaptive_tool_counts.c.attempts+1}))
                        dependencies=tuple(history.select(name,now) for name in DEPENDENCIES[action.tool])
                        old=next(iter(history.active(action.tool)),None)
                        dispatch=(run,action.tool,dependencies,old.id if old else None)
                    elif action.kind=='propose':
                        with c.begin_nested() as guard:
                            try:publish(c,run,case,history)
                            except (SQLAlchemyError,ValueError):
                                guard.rollback()
                                step(c,run,'safety_drift',{'reason':'safety_unavailable','changed_tools':list(TOOLS),
                                     'invalidated_ids':[o.id for o in history.active()]},pending_token=None,pending_context=None)
                    else:finish(c,run,case,history,action.reason or 'established_blocker',blocker=action.kind=='report_blocker')
    if dispatch:
        reserved,tool,dependencies,old_id=dispatch
        with transaction(engine,readonly=True) as c:
            c.info['adaptive_tool']=tool
            try:
                now=clock(c)
                if now>=reserved['deadline']:
                    obs=observation(tool,reserved['request'],now,value=None,payload={},status='unavailable',reason='run_deadline',
                                    dependencies=tuple(dep.dependency() for dep in dependencies))
                else:
                    obs=read_tool(DeadlineConnection(c,reserved['deadline']),tool,AssessmentRequest(**reserved['request']),
                                  history,now,dependencies=dependencies)
                    if obs.record()['status']=='unavailable':c.rollback()
            finally:
                c.info.pop('adaptive_tool',None)
        with transaction(engine) as c:
            c=bounded_active(c,run_id)
            run,case=locked(c,run_id)
            owns_claim=(run['state']=='active' and run['pending_token']==reserved['pending_token']
                        and run['pending_context']==reserved['pending_context'])
            applicable=owns_claim and matches(run,case) and clock(c)<run['deadline']
            if run['state']=='active':
                run=step(c,run,'tool_result' if applicable else 'tool_result_discarded',
                         {'tool':tool,'status':obs.record()['status'],'reason':obs.record()['reason'],'observation_id':obs.id},
                         pending_token=None if applicable else run['pending_token'],
                         pending_context=None if applicable else run['pending_context'])
                c.execute(db.adaptive_observations.insert().values(id=obs.id,run_id=run_id,step_sequence=run['context_version'],
                          record=obs.record(),applied=applicable))
                if applicable:
                    if old_id:c.execute(db.adaptive_supersessions.insert().values(run_id=run_id,old_id=old_id,new_id=obs.id))
                    c.execute(insert(db.adaptive_active).values(run_id=run_id,tool=tool,stream='primary',observation_id=obs.id)
                        .on_conflict_do_update(index_elements=['run_id','tool','stream'],set_={'observation_id':obs.id}))
                history,steps,observations,edges,counts=snapshot(c,run)
                if owns_claim and not matches(run,case):finish(c,run,case,history,'case_changed',stale=True)
                elif owns_claim and clock(c)>=run['deadline']:finish(c,run,case,history,'run_deadline')
            else:
                sequence=c.execute(sa.select(sa.func.max(db.adaptive_steps.c.sequence)).where(
                    db.adaptive_steps.c.run_id==run_id)).scalar_one()+1
                c.execute(db.adaptive_steps.insert().values(run_id=run_id,sequence=sequence,
                    kind='tool_result_discarded',data={'tool':tool,'observation_id':obs.id,'reason':'run_terminal'},created_at=clock(c)))
                c.execute(db.adaptive_observations.insert().values(id=obs.id,run_id=run_id,step_sequence=sequence,
                    record=obs.record(),applied=False))
    return inspect(engine,run_id)


def recover(engine,run_id, *, expected_context):
    """Explicit interruption of an abandoned read; no automatic redispatch or reset."""
    with transaction(engine) as c:
        c=bounded_active(c,run_id)
        run,case=locked(c,run_id)
        if run['state']!='active' or not run['pending_token']:return inspect(engine,run_id)
        if run['context_version']!=expected_context:raise ValueError('Stale recovery context')
        history,steps,observations,edges,counts=snapshot(c,run)
        if not matches(run,case):finish(c,run,case,history,'case_changed',stale=True)
        elif clock(c)>=run['deadline']:finish(c,run,case,history,'run_deadline')
        else:step(c,run,'read_interrupted',{'token':run['pending_token'],'reason':'operator_recovery'},pending_token=None,pending_context=None)
    return inspect(engine,run_id)


def drive(engine,run_id):
    fallback=False
    for _ in range(17):
        run=inspect(engine,run_id)
        if run['state']!='active':return run
        if run['pending_token']:raise ValueError('Pending read requires explicit inspect/recover')
        try:request=policy_request(engine,run_id)
        except ValueError:
            return advance(engine,run_id,{'kind':'request_review','reason':'manual_review'},expected_context=run['context_version'])
        mode=run['contracts']['policy']
        policy=FixedOrder() if fallback or mode=='fixed' else (CueRules() if mode=='cue' else FakePolicy(mode[5:]))
        try:action=policy.choose(request)
        except RuntimeError:action={'kind':'policy_unavailable'}
        run=advance(engine,run_id,action,expected_context=request.context_version,fallback=fallback)
        if run['steps'][-1]['kind']=='choice_rejected':fallback=True
    return advance(engine,run_id,{'kind':'request_review','reason':'unknown_evidence'},expected_context=run['context_version'])
