"""Bounded opt-in model-free worker. No inference transaction or model session."""
from datetime import datetime,timezone
from queue import Queue,Empty
from threading import Thread,Event
import time
from . import adaptive_jobs as jobs,adaptive_accounting as ledger,adaptive_investigations as service
from .adaptive_recommendations import FakeAdapter,Cancelled
from .jobs import LeaseLost

class Interrupted(RuntimeError):pass

def tick(engine,fence,adapter=None,fault=None,cancel=None):
    with service.transaction(engine,readonly=True) as c:
        job=jobs.get(c,fence.job_id);run=service.row(c,job['run_id'])
    if run['state']=='active':
        with service.transaction(engine,readonly=True) as c:fence.check(c,run,False)
    if cancel is not None and cancel.is_set():
        # A worker stop signal has no unfenced operator cancellation authority.
        return {'event':'worker_stopped','state':run['state']}
    if run['state']!='active':
        if job['status']=='running':jobs.complete(engine,fence)
        return {'event':'terminal','state':run['state']}
    if run['pending_token']:return {'event':'interrupted_read','run_id':run['id']}
    with service.transaction(engine,readonly=True) as c:call=ledger.latest(c,run['id'])
    if call and call['application_status']=='pending' and call['state'] in ('dispatching','uncertain'):
        return {'event':'uncertain_decision','call_id':call['id']}
    if adapter is not None and hasattr(adapter,'ensure_ready') and run['contracts'].get('session'):
        needs_new=(call is None or call['application_status']!='pending')
        fallback=bool(call and (call['application_status']=='stale' or call['result'] and call['result']['status']!='success' or call['request']['configuration'].get('source')=='rules'))
        if needs_new and not fallback and len(service.policy_request(engine,run['id']).allowed)>1:
            try:ready=adapter.ensure_ready()
            except ValueError as error:
                if cancel is not None and cancel.is_set():return {'event':'worker_stopped','state':run['state']}
                return {'event':'session_requires_review','reason':str(error)}
            if cancel is not None and cancel.is_set():return {'event':'worker_stopped','state':run['state']}
            if not ready and adapter.row is not None:
                with service.transaction(engine,readonly=True) as c:
                    from .adaptive_sessions import records
                    phase=next(r for r in records(c,run['id']) if r['id']==adapter.row['id'])
                if phase['state']=='uncertain':return {'event':'uncertain_session','session_id':phase['id']}
    if call is None or call['application_status']!='pending':
        try:call=ledger.prepare(engine,run['id'],fence)
        except ValueError as error:
            if isinstance(error,LeaseLost):raise
            if cancel is not None and cancel.is_set():return {'event':'worker_stopped','state':run['state']}
            current=service.inspect(engine,run['id'])
            service.advance(engine,run['id'],{'kind':'request_review','reason':'manual_review'},expected_context=current['context_version'],fence=fence)
            return {'event':'review_budget'}
    if cancel is not None and cancel.is_set():return {'event':'worker_stopped','state':run['state']}
    if fault=='after_reservation':raise Interrupted(fault)
    if call['state']=='reserved':
        call=ledger.claim(engine,call['id'],fence)
        if call is None:return {'event':'claimed_elsewhere'}
        if cancel is not None and cancel.is_set():
            with service.transaction(engine) as c:ledger.uncertain(c,call['id'],'worker_shutdown_before_adapter')
            return {'event':'worker_stopped','state':run['state']}
        if fault=='after_dispatch':raise Interrupted(fault)
        request=ledger.request_from(call);shutdown=cancel;call_cancel=Event();queue=Queue(maxsize=1)
        adapter=(adapter if adapter is not None and (request.session is not None or not hasattr(adapter,'ensure_ready')) else FakeAdapter())
        if not isinstance(adapter,FakeAdapter):raise ValueError('Stage 3 admits model-free fake adapters only')
        def invoke():
            try:queue.put(('result',adapter.choose(request,call_cancel)))
            except Exception as error:queue.put(('error',type(error).__name__))
        if shutdown is not None and shutdown.is_set():
            with service.transaction(engine) as c:ledger.uncertain(c,call['id'],'worker_shutdown_before_adapter')
            return {'event':'worker_stopped','state':run['state']}
        child=Thread(target=invoke,daemon=True);child.start()
        received=None;reason='interrupted_decision'
        while not call_cancel.is_set() and not (shutdown is not None and shutdown.is_set()):
            remaining=(call['deadline']-datetime.now(timezone.utc)).total_seconds()
            if remaining<=0:reason='decision_deadline';break
            try:
                kind,raw=queue.get(timeout=min(.05,remaining))
                if kind=='result':received=raw
                else:reason=raw
                break
            except Empty:
                try:
                    with service.transaction(engine,readonly=True) as c:
                        current=service.row(c,run['id']);fence.check(c,current,False)
                        from . import schema as db
                        import sqlalchemy as sa
                        actual=c.execute(sa.select(db.cases).where(db.cases.c.id==current['case_id'])).mappings().one()
                        if not service.matches(current,actual):raise LeaseLost('Staff changed case')
                except Exception:reason='lease_or_state_lost';break
        call_cancel.set();child.join(timeout=1)
        with service.transaction(engine) as c:
            if received is None:ledger.uncertain(c,call['id'],reason)
            else:
                try:ledger.settle(c,call['id'],received)
                except ValueError:ledger.uncertain(c,call['id'],'malformed_result')
        if shutdown is not None and shutdown.is_set():return {'event':'worker_stopped','state':run['state']}
        if received is None:return {'event':'uncertain_decision','call_id':call['id'],'reason':reason}
        if fault=='after_result':raise Interrupted(fault)
        with service.transaction(engine,readonly=True) as c:call=ledger.get(c,call['id'])
    if call['state']!='settled':return {'event':'uncertain_decision','call_id':call['id']}
    if cancel is not None and cancel.is_set():return {'event':'worker_stopped','state':run['state']}
    current=service.inspect(engine,run['id'])
    if (current['context_version']!=call['context_version'] or datetime.now(timezone.utc)>=call['deadline']):
        with service.guarded(engine,run['id'],fence) as (c,bound,case):
            ledger.disposition(c,call['id'],'stale')
            service.step(c,bound,'recommendation_rejected',{'call_id':call['id'],'reason':'context_or_deadline_changed'})
        return {'event':'stale_recommendation'}
    result=service.advance(engine,run['id'],None,expected_context=current['context_version'],fence=fence,
                           recommendation_id=call['id'],fallback=bool(call['request']['configuration'].get('fallback')) or call['request']['configuration']['mode']!=current['contracts']['policy'])
    if fault=='after_application':raise Interrupted(fault)
    if result['state']!='active':jobs.complete(engine,fence)
    return {'event':'step','state':result['state'],'run_id':run['id'],'call_id':call['id']}

def _run_until_pause(engine,fence,cancel=None,adapter=None):
    for _ in range(34):
        result=tick(engine,fence,cancel=cancel,adapter=adapter)
        if result['event'] not in ('step','stale_recommendation','review_budget'):return result
        with service.transaction(engine,readonly=True) as c:job=jobs.get(c,fence.job_id)
        run=service.inspect(engine,job['run_id'])
        if run['state']!='active':return run
        jobs.renew(engine,fence.job_id,fence.token,30)
    return {'event':'bounded_worker_pause'}


def run_until_pause(engine,fence,cancel=None):
    from .adaptive_sessions import scope
    with scope(engine,fence,cancel) as adapter:
        return _run_until_pause(engine,fence,cancel,adapter)
