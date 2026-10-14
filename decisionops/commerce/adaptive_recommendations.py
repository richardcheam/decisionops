"""Pure task-specific, model-free recommendation boundary. No model imports."""
from dataclasses import dataclass
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
    def __post_init__(self):
        if self.task!=TASK or self.mode not in MODES or type(self.max_runtime_ms) is not int or not 1<=self.max_runtime_ms<=20000:
            raise ValueError('Unsupported task/configuration/resources')
    def record(self):
        return {'id':self.id,'task':self.task,'run_id':self.run_id,'generation':self.generation,
                'case_revision':self.case_revision,'context_version':self.policy.context_version,
                'features':self.policy.features(),'configuration':{'mode':self.mode,'version':CONFIG_VERSION},
                'max_runtime_ms':self.max_runtime_ms,'api_charge_kind':'no_api_charge'}

@dataclass(frozen=True)
class Result:
    request_id:str
    action:dict|None
    elapsed_ms:int
    status:str='success'
    error:str|None=None
    def record(self):return dict(request_id=self.request_id,action=self.action,elapsed_ms=self.elapsed_ms,status=self.status,error=self.error)

def validate(request,result):
    if (not isinstance(result,Result) or result.request_id!=request.id
        or type(result.elapsed_ms) is not int or not 0<=result.elapsed_ms<=request.max_runtime_ms
        or result.status not in ('success','invalid','unavailable')):raise ValueError('Malformed recommendation identity/usage')
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
