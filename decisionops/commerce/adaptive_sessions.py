"""Durable run-scoped session phases. Database locks never span child work."""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import os
import threading
import time
import sqlalchemy as sa
from . import schema as db,adaptive_investigations as service,adaptive_jobs as jobs
from .cases import clock,identifier
from .proposals import document_hash
from .session_protocol import Config,Session,SessionFailure,KnownFailure
from .adaptive_recommendations import FakeAdapter,Result

class RecoveryRequired(ValueError):pass

class StopSignals:
    def __init__(self,*signals):self.signals=signals
    def is_set(self):return any(s.is_set() for s in self.signals)


def records(c,run_id):
    saved=[dict(r) for r in c.execute(sa.select(db.adaptive_sessions).where(db.adaptive_sessions.c.run_id==run_id).order_by(db.adaptive_sessions.c.ordinal)).mappings()]
    for r in saved:
        if document_hash(r['config'])!=r['config_hash']:raise ValueError('Session configuration hash mismatch')
        Config(**r['config'])  # Historical syntax only; never consult current pins.
    return saved

def phase_charge(c,run_id):
    return c.execute(sa.select(sa.func.coalesce(sa.func.sum(sa.func.coalesce(db.adaptive_sessions.c.actual_charge_ms,db.adaptive_sessions.c.reserved_ms)),0)).where(db.adaptive_sessions.c.run_id==run_id)).scalar_one()

def audit(c,sid,kind,data):
    n=c.execute(sa.select(sa.func.coalesce(sa.func.max(db.adaptive_session_events.c.sequence),0)).where(db.adaptive_session_events.c.session_id==sid)).scalar_one()+1
    c.execute(db.adaptive_session_events.insert().values(session_id=sid,sequence=n,kind=kind,data=data,created_at=clock(c)))

def reserve(engine,fence):
    with service.transaction(engine,readonly=True) as c:job=jobs.get(c,fence.job_id)
    with service.guarded(engine,job['run_id'],fence) as (c,run,case):
        cfg=Config(**run['contracts']['session']);history=records(c,run['id'])
        if any(not r['retired'] and r['state'] in ('waiting','loading','ready','uncertain') for r in history):raise RecoveryRequired('Unresolved session: explicit recover required; no automatic reload')
        if len(history)>=3:raise ValueError('Session reload cap exhausted')
        decision_charge=c.execute(sa.select(sa.func.coalesce(sa.func.sum(sa.case((db.adaptive_calls.c.state=='settled',db.adaptive_calls.c.actual_ms),else_=db.adaptive_calls.c.reserved_ms)),0)).where(db.adaptive_calls.c.run_id==run['id'])).scalar_one()
        now=clock(c);maximum=min(cfg.slot_ms+cfg.preload_ms,240000-phase_charge(c,run['id'])-decision_charge,int((run['deadline']-now).total_seconds()*1000))
        if maximum<=0:raise ValueError('Session resource budget exhausted')
        sid=identifier('ASES');values=dict(id=sid,run_id=run['id'],job_id=fence.job_id,token=fence.token,ordinal=len(history)+1,config=cfg.record(),config_hash=document_hash(cfg.record()),
             generation=run['generation'],case_revision=run['case_revision'],state='waiting',reserved_ms=maximum,deadline=now+timedelta(milliseconds=maximum),created_at=now)
        c.execute(db.adaptive_sessions.insert().values(**values));audit(c,sid,'reserved',{'maximum_ms':maximum,'api_charge_kind':'no_api_charge','reload':len(history)})
        return records(c,run['id'])[-1]

def update(engine,sid,kind,**values):
    # Audit-only original-session telemetry: cannot change case/job/run or bindings.
    with service.transaction(engine) as c:
        old=c.execute(sa.select(db.adaptive_sessions).where(db.adaptive_sessions.c.id==sid).with_for_update()).mappings().one()
        if old['state'] in ('closed','uncertain','failed'):
            values={k:v for k,v in values.items() if k not in ('state','actual_charge_ms')}
        c.execute(db.adaptive_sessions.update().where(db.adaptive_sessions.c.id==sid).values(**values))
        audit(c,sid,kind,values)

def recover(c,run):
    for r in records(c,run['id']):
        if not r['retired'] and r['state'] in ('waiting','loading','ready','uncertain'):
            c.execute(db.adaptive_sessions.update().where(db.adaptive_sessions.c.id==r['id']).values(state='uncertain',retired=True))
            audit(c,r['id'],'operator_recovery',{'reservation_retained':True,'no_redispatch':True})

class Adapter(FakeAdapter):
    def __init__(self,engine,fence,stop=None):
        self.engine=engine;self.fence=fence;self.stop=stop or threading.Event();self.cancel=threading.Event()
        self.done=threading.Event();self.child=None;self.row=None;self.failure=None;self.pulse=None
        with service.transaction(engine,readonly=True) as c:
            job=jobs.get(c,fence.job_id);self.run=service.row(c,job['run_id']);self.lease_until=job['lease_until']
        self.config=Config(**self.run['contracts']['session'])
    def _heartbeat(self):
        renewed=0
        while not self.done.wait(.05):
            if self.stop.is_set() or datetime.now(timezone.utc)>=self.run['deadline']:
                self.cancel.set();return
            if time.monotonic()-renewed<.5:continue
            try:
                with service.transaction(self.engine,readonly=True) as raw:
                    c=service.DeadlineConnection(raw,min(self.run['deadline'],self.lease_until))
                    run=service.row(c,self.run['id']);self.fence.check(c,run,False)
                    phase=c.execute(sa.select(db.adaptive_sessions.c.retired).where(db.adaptive_sessions.c.id==self.row['id'])).scalar_one()
                    if phase:raise ValueError('Session explicitly retired')
                    case=c.execute(sa.select(db.cases).where(db.cases.c.id==run['case_id'])).mappings().one()
                    if run['state']=='active' and not service.matches(run,case):raise ValueError('Staff state changed')
                    if run['state']!='active':self.cancel.set();return
                owned=jobs.renew(self.engine,self.fence.job_id,self.fence.token,30);self.lease_until=owned['lease_until']
                if self.child is not None:self.child.lease_deadline=time.monotonic()+max(0,(self.lease_until-datetime.now(timezone.utc)).total_seconds())
                renewed=time.monotonic()
            except Exception as error:self.failure=type(error).__name__;self.cancel.set();return
    def ensure_ready(self):
        if self.child is not None:
            try:self.config.admit()
            except SessionFailure as error:self.failure=str(error);self.child._kill();return False
            if self.child.process is not None and self.child.process.poll() is not None:
                self.failure='child_exited_before_request';return False
            return self.child.ready is not None and self.child.failed is None
        if self.failure is not None:return False
        self.row=reserve(self.engine,self.fence)
        try:
            self.config.admit()
        except SessionFailure as error:
            self.failure=str(error);update(self.engine,self.row['id'],'not_dispatched',state='failed',actual_charge_ms=0,diagnostics={'reason':self.failure,'process_reaped':True});return False
        self.pulse=threading.Thread(target=self._heartbeat,daemon=True);self.pulse.start()
        run_end=time.monotonic()+max(0,(self.run['deadline']-datetime.now(timezone.utc)).total_seconds())
        phase_end=time.monotonic()+max(0,(self.row['deadline']-datetime.now(timezone.utc)).total_seconds())
        self.child=Session(self.config,self.row['id'],run_end,cancel=StopSignals(self.cancel,self.stop),preload_deadline=phase_end,
                           lease_deadline=time.monotonic()+max(0,(self.lease_until-datetime.now(timezone.utc)).total_seconds()),
                           python=os.environ.get('COMMERCE_MODEL_PYTHON') if self.config.family!='fake' else None,
                           on_launch=lambda:update(self.engine,self.row['id'],'launch_intent',state='loading'),
                           on_started=lambda:update(self.engine,self.row['id'],'launched',diagnostics=self.child.diagnostics()))
        try:
            self.child.start()
            if self.stop.is_set() or self.cancel.is_set():raise SessionFailure('cancelled')
            with service.transaction(self.engine,readonly=True) as c:
                self.fence.check(c,service.row(c,self.run['id']),False)
                if c.execute(sa.select(db.adaptive_sessions.c.retired).where(db.adaptive_sessions.c.id==self.row['id'])).scalar_one():raise SessionFailure('session_retired')
            charge=int((datetime.now(timezone.utc)-self.row['created_at']).total_seconds()*1000)
            if charge>self.row['reserved_ms']:raise SessionFailure('phase_resource_exceeded')
            update(self.engine,self.row['id'],'ready',state='ready',actual_charge_ms=charge,waiting_ms=max(self.child.wait_ms,charge-self.child.load_ms),load_ms=self.child.load_ms,diagnostics=self.child.diagnostics())
            return True
        except (SessionFailure,OSError,ValueError) as error:
            self.failure=str(error);self.cancel.set();self.child.close()
            known=isinstance(error,KnownFailure) or self.child.process is None
            values={'actual_charge_ms':min(self.row['reserved_ms'],self.child.wait_ms+self.child.load_ms)} if known else {}
            update(self.engine,self.row['id'],'failed' if known else 'uncertain',state='failed' if known else 'uncertain',**values,waiting_ms=self.child.wait_ms,load_ms=self.child.load_ms,diagnostics=self.child.diagnostics())
            return False
    def choose(self,request,cancel):
        if request.session is None:return FakeAdapter().choose(request,cancel)
        features=request.policy.features()
        if len(request.policy.allowed)==1:
            return Result(request.id,request.policy.allowed[0].record(),0,metadata={'forced':True,'inference_performed':False,'session_id':None,'api_charge_kind':'no_api_charge'})
        try:self.config.admit()
        except SessionFailure as error:
            if self.child:self.child._kill()
            return Result(request.id,None,0,'unavailable',str(error))
        if self.row is None and request.session['session_id'] is not None:
            return Result(request.id,None,0,'unavailable','recorded_session_not_live')
        if not self.ensure_ready():return Result(request.id,None,0,'unavailable',self.failure or 'session_unavailable')
        if self.row['id']!=request.session['session_id']:return Result(request.id,None,0,'unavailable','recorded_session_not_live')
        begun=time.monotonic();end=min(time.monotonic()+request.max_runtime_ms/1000,
                time.monotonic()+max(0,(request.deadline-datetime.now(timezone.utc)).total_seconds()))
        local_stop=threading.Event()
        def watch():
            while not local_stop.wait(.01):
                if cancel.is_set():self.cancel.set();return
        watcher=threading.Thread(target=watch,daemon=True);watcher.start()
        try:
            raw=self.child.choose(request.id,features,end)
            elapsed=int((time.monotonic()-begun)*1000)
            return Result(request.id,request.policy.allowed[raw['action_index']].record(),elapsed,metadata={'session_id':self.row['id'],
                 'family':self.config.family,'revision':self.config.revision,'native':raw,'inference_performed':True,'simulated':self.config.family=='fake','api_charge_kind':'no_api_charge'})
        except KnownFailure as error:
            return Result(request.id,None,int((time.monotonic()-begun)*1000),'unavailable',str(error),metadata={'session_id':self.row['id'],'simulated':self.config.family=='fake','api_charge_kind':'no_api_charge'})
        finally:local_stop.set();watcher.join(.1)
    def close(self):
        self.done.set()
        if self.child is not None:
            self.child.close();d=self.child.diagnostics();d['run_wall_ms']=int((datetime.now(timezone.utc)-self.run['created_at']).total_seconds()*1000)
            update(self.engine,self.row['id'],'closed',state='closed' if self.child.ready else 'uncertain',
                   inference_ms=d['inference_ms'],total_ms=d['total_ms'],diagnostics=d)
        self.cancel.set()
        if self.pulse:self.pulse.join(.2)

@contextmanager
def scope(engine,fence,stop=None):
    with service.transaction(engine,readonly=True) as c:
        job=jobs.get(c,fence.job_id);run=service.row(c,job['run_id'])
    adapter=Adapter(engine,fence,stop) if run['contracts'].get('session') else None
    try:yield adapter
    finally:
        if adapter:adapter.close()
