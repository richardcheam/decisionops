"""Pure task-specific, model-free recommendation boundary. No model imports."""
from dataclasses import dataclass
from datetime import datetime
import json
import time
from .adaptive_policies import Action,PolicyRequest,FixedOrder,CueRules,FakePolicy

TASK='choose_investigation_action/v1'
CONFIG_VERSION='model-free-v1'
MODES=('fixed','cue','fake-override','fake-invalid','fake-unavailable','fake-refuse')
class Cancelled(RuntimeError):pass

@dataclass(frozen=True)
class Request:
    id:str
    run_id:str
    generation:int
    case_revision:int
    policy:PolicyRequest
    mode:str
    max_runtime_ms:int
    task:str=TASK
    session:dict|None=None
    deadline:datetime|None=None
    def __post_init__(self):
        if self.task!=TASK or self.mode not in MODES or type(self.max_runtime_ms) is not int or not 1<=self.max_runtime_ms<=20000:
            raise ValueError('Unsupported task/configuration/resources')
        if self.session is not None:
            from .session_protocol import Config
            if not isinstance(self.session,dict) or set(self.session)!={'config','session_id'}:raise ValueError('Invalid recorded session binding')
            Config(**self.session['config'])
            if self.session['session_id'] is not None and not isinstance(self.session['session_id'],str):raise ValueError('Invalid session identity')
    def record(self):
        record={'id':self.id,'task':self.task,'run_id':self.run_id,'generation':self.generation,
                'case_revision':self.case_revision,'context_version':self.policy.context_version,
                'features':self.policy.features(),'configuration':{'mode':self.mode,'version':CONFIG_VERSION},
                'max_runtime_ms':self.max_runtime_ms,'api_charge_kind':'no_api_charge'}
        if self.session is not None:record['configuration']['session']=self.session
        return record

@dataclass(frozen=True)
class Result:
    request_id:str
    action:dict|None
    elapsed_ms:int
    status:str='success'
    error:str|None=None
    metadata:dict|None=None
    def record(self):
        record=dict(request_id=self.request_id,action=self.action,elapsed_ms=self.elapsed_ms,status=self.status,error=self.error)
        if self.metadata is not None:record['metadata']=self.metadata
        return record

def validate(request,result):
    if (not isinstance(result,Result) or result.request_id!=request.id
        or type(result.elapsed_ms) is not int or not 0<=result.elapsed_ms<=request.max_runtime_ms
        or result.status not in ('success','invalid','unavailable')):raise ValueError('Malformed recommendation identity/usage')
    if result.metadata is not None:
        if not isinstance(result.metadata,dict) or len(json.dumps(result.metadata,allow_nan=False).encode())>65536:raise ValueError('Result metadata cap')
    if request.session is not None and result.status=='success':
        if result.metadata is None or result.metadata.get('session_id')!=request.session['session_id']:raise ValueError('Session result binding mismatch')
        if result.metadata.get('forced'):
            if len(request.policy.allowed)!=1 or result.elapsed_ms!=0 or result.metadata.get('inference_performed') is not False:raise ValueError('Invalid forced result')
        elif result.metadata.get('family')!=request.session['config']['family'] or result.metadata.get('revision')!=request.session['config']['revision']:
            raise ValueError('Session model identity mismatch')
    if result.status=='success' and Action.from_record(result.action) not in request.policy.allowed:
        raise ValueError('Recommendation not allowed')
    if result.status!='success' and result.action is not None:raise ValueError('Failure cannot carry an action')
    return result

class FakeAdapter:
    """Cooperative adapter exercises policy/cancellation; no inference or API charge."""
    def __init__(self,delay=0):
        if not 0<=delay<=30:raise ValueError('Bounded fake delay required')
        self.delay=delay
    def choose(self,request,cancel):
        started=time.monotonic()
        if cancel.wait(self.delay):raise Cancelled('Decision cancelled')
        if request is None:raise ValueError('Request required')
        policy=FixedOrder() if request.mode=='fixed' else CueRules() if request.mode=='cue' else FakePolicy(request.mode[5:])
        try:
            raw=policy.choose(request.policy)
            action=raw.record() if isinstance(raw,Action) else raw
            result=Result(request.id,action,int((time.monotonic()-started)*1000))
            return validate(request,result)
        except ValueError:return Result(request.id,None,int((time.monotonic()-started)*1000),'invalid','invalid_choice')
        except RuntimeError:return Result(request.id,None,int((time.monotonic()-started)*1000),'unavailable','policy_unavailable')
