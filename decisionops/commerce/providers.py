"""Pure routing contracts and simulated providers. No SDK, model or network access."""
from dataclasses import dataclass, fields, field, InitVar
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import math
import hashlib
import re
import time
from types import MappingProxyType
from pathlib import Path

from .eligibility import REQUIREMENTS

REVISION_FILE=Path(__file__).resolve().parents[2]/'model-revisions.env'

def configured_revision(mode):
    from ..backends import parse_revision_pins,REPOSITORIES
    return parse_revision_pins(REVISION_FILE)[REPOSITORIES[mode][1]]

QUANTUM = Decimal('0.00000001')
CHOICES = ('present_replacement', 'staff_review')
SCENARIOS = ('success','review','unavailable','refused','invalid_choice',
             'malformed','instruction_override','timeout')


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',value):
        raise ValueError('Identifiers must be bounded plain identifiers')
    return value


def response_id(prefix,run_id):
    return prefix+'-'+hashlib.sha256(run_id.encode()).hexdigest()


def money(value):
    if not isinstance(value,(str,Decimal)):
        raise ValueError('Money/rates require decimal strings, not floats')
    try:
        amount=Decimal(value)
    except InvalidOperation:
        raise ValueError('Invalid decimal amount') from None
    if not amount.is_finite() or not 0<=amount<=Decimal('1000') or amount.as_tuple().exponent < -8:
        raise ValueError('Amounts must be finite, nonnegative and have at most eight decimal places')
    return amount.quantize(QUANTUM)


def freeze(value):
    if isinstance(value,dict):return MappingProxyType({k:freeze(v) for k,v in value.items()})
    if isinstance(value,(tuple,list)):return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value,(dict,MappingProxyType)):return {k:thaw(v) for k,v in value.items()}
    if isinstance(value,tuple):return [thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class Pricing:
    version: str='simulated-v1'
    currency: str='USD'
    input_usd_per_million: Decimal=Decimal('1')
    output_usd_per_million: Decimal=Decimal('2')
    charge_kind: str='simulated'

    def __post_init__(self):
        identifier(self.version)
        if self.currency!='USD' or self.charge_kind not in ('simulated','local_no_api_charge'):raise ValueError('Unsupported accounting')
        for name in ('input_usd_per_million','output_usd_per_million'):
            object.__setattr__(self,name,money(getattr(self,name)))

    @classmethod
    def local(cls):return cls(version='local-cpu-v1',charge_kind='local_no_api_charge',input_usd_per_million=Decimal('0'),output_usd_per_million=Decimal('0'))

    def cost(self,input_tokens,output_tokens):
        for value in (input_tokens,output_tokens):
            if type(value) is not int or value<0:raise ValueError('Usage must be nonnegative integers')
        return ((input_tokens*self.input_usd_per_million+output_tokens*self.output_usd_per_million)
                /Decimal('1000000')).quantize(QUANTUM,rounding=ROUND_CEILING)

    def as_record(self):
        return {'version':self.version,'currency':self.currency,
                'input_usd_per_million':str(self.input_usd_per_million),
                'output_usd_per_million':str(self.output_usd_per_million),'simulated':self.charge_kind=='simulated',**({'charge_kind':self.charge_kind} if self.charge_kind!='simulated' else {})}


@dataclass(frozen=True)
class Limits:
    max_requests: int=3
    max_cost_usd: Decimal=Decimal('0.00300000')
    max_input_tokens: int=2000
    max_output_tokens: int=300

    def __post_init__(self):
        for name,maximum in (('max_requests',1000),('max_input_tokens',65536),('max_output_tokens',4096)):
            value=getattr(self,name)
            if type(value) is not int or not 1<=value<=maximum:raise ValueError('Invalid bounded limits')
        object.__setattr__(self,'max_cost_usd',money(self.max_cost_usd))

    def as_record(self):
        return {field.name:(str(getattr(self,field.name)) if field.name=='max_cost_usd' else getattr(self,field.name)) for field in fields(self)}


@dataclass(frozen=True)
class ProviderConfig:
    mode: str='fake'
    provider_id: str | None=None
    configuration_version: str='routing-v1'
    scenario: str='success'
    delay_ms: int=0
    model_revision: str | None=None
    _historical: InitVar[bool]=False

    def __post_init__(self,_historical):
        if self.mode not in ('rules','fake','laya','gliclass'):raise ValueError('Unsupported provider mode')
        expected='rules-v1' if self.mode=='rules' else 'fake-v1' if self.mode=='fake' else self.mode+'-local-v1'
        if self.provider_id is None:object.__setattr__(self,'provider_id',expected)
        if self.provider_id!=expected:raise ValueError('Provider mode/identity mismatch')
        if self.mode in ('laya','gliclass'):
            if self.model_revision is None and not _historical:
                object.__setattr__(self,'model_revision',configured_revision(self.mode))
            if not isinstance(self.model_revision,str) or not re.fullmatch('[0-9a-f]{40}',self.model_revision):
                raise ValueError('Local checkpoint requires a recorded full commit SHA')
            if not _historical:self.validate_new()
            if self.scenario!='success' or self.delay_ms!=0:raise ValueError('Fake settings cannot configure real inference')
        elif self.model_revision is not None:raise ValueError('Model revision requires local mode')
        identifier(self.configuration_version)
        if self.scenario not in SCENARIOS or type(self.delay_ms) is not int or not 0<=self.delay_ms<=10000:
            raise ValueError('Invalid fake scenario/delay')

    def validate_new(self):
        if self.mode in ('laya','gliclass') and self.model_revision!=configured_revision(self.mode):
            raise ValueError('Only the configured checkpoint pin is supported for new dispatch')

    @classmethod
    def from_record(cls,record):
        # Structural validation only; immutable audit history is not current policy.
        return cls(**record,_historical=True)

    def as_record(self):return {f.name:getattr(self,f.name) for f in fields(self) if f.name!='model_revision' or self.model_revision is not None}


def permitted_choices(facts,status):
    return CHOICES if status=='awaiting_review' and all(facts.get(k) is True for k in REQUIREMENTS) else ('staff_review',)


@dataclass(frozen=True)
class ProviderRequest:
    task: str
    case_id: str
    run_id: str
    facts: dict
    binding: dict
    allowed_choices: tuple[str,...]
    config: ProviderConfig
    deadline: datetime
    limits: Limits
    pricing: Pricing
    _historical: InitVar[bool]=False

    def __post_init__(self,_historical):
        if not _historical:self.config.validate_new()
        identifier(self.case_id);identifier(self.run_id)
        local=self.config.mode in ('rules','laya','gliclass')
        if local != (self.pricing.charge_kind=='local_no_api_charge'):raise ValueError('Provider/accounting mismatch')
        if local and (self.pricing.input_usd_per_million or self.pricing.output_usd_per_million):raise ValueError('Local inference has no API charge')
        if self.task!='route_investigated_case':raise ValueError('Unsupported provider task')
        if not isinstance(self.deadline,datetime) or self.deadline.tzinfo is None or self.deadline.utcoffset().total_seconds()!=0:
            raise ValueError('Deadline must be an aware UTC time')
        if set(self.facts)!=set(REQUIREMENTS) or any(v is not True and v is not False and v is not None for v in self.facts.values()):
            raise ValueError('Only the seven normalized facts are permitted evidence')
        names={'generation','status','investigation_id','proposal_id','content_hash','request','policy_id','source_versions'}
        if set(self.binding)!=names:raise ValueError('Explicit evidence/state bindings required')
        if type(self.binding['generation']) is not int or self.binding['generation']<1:raise ValueError('Invalid generation')
        if self.binding['status'] not in ('awaiting_review','needs_review','blocked'):raise ValueError('Case is not available for routing')
        if set(self.binding['source_versions'])!=set(REQUIREMENTS) or any(not re.fullmatch('[0-9a-f]{64}',v) for v in self.binding['source_versions'].values()):
            raise ValueError('All evidence versions must be bound')
        for name in ('investigation_id','proposal_id','policy_id'):
            if self.binding[name] is not None:identifier(self.binding[name])
        digest=self.binding['content_hash']
        if digest is not None and not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Invalid proposal digest')
        original=self.binding['request']
        if set(original)!= {'order_id','shipment_id','items'} or not 1<=len(original['items'])<=100:raise ValueError('Invalid original request')
        identifier(original['order_id']);identifier(original['shipment_id'])
        for variant,quantity in original['items'].items():
            identifier(variant)
            if type(quantity) is not int or not 1<=quantity<=1000:raise ValueError('Invalid quantity')
        if tuple(self.allowed_choices)!=permitted_choices(self.facts,self.binding['status']):
            raise ValueError('Choices must match established facts and current case state')
        object.__setattr__(self,'facts',freeze(dict(self.facts)))
        object.__setattr__(self,'binding',freeze(thaw(self.binding)))
        object.__setattr__(self,'allowed_choices',tuple(self.allowed_choices))

    def as_record(self):
        return {'task':self.task,'case_id':self.case_id,'run_id':self.run_id,'facts':thaw(self.facts),
                'binding':thaw(self.binding),'allowed_choices':list(self.allowed_choices),
                'config':self.config.as_record(),'deadline':self.deadline.isoformat(),
                'limits':self.limits.as_record(),'pricing':self.pricing.as_record()}

    @classmethod
    def from_record(cls,record):
        values=dict(record);values['deadline']=datetime.fromisoformat(values['deadline'])
        values['limits']=Limits(**values['limits']);values['config']=ProviderConfig.from_record(values['config'])
        pricing=dict(values['pricing']);pricing.pop('simulated');values['pricing']=Pricing(**pricing)
        return cls(**values,_historical=True)


@dataclass(frozen=True)
class ProviderResult:
    selected_choice: str | None
    provider_id: str
    run_id: str
    provider_request_id: str
    status: str='success'
    input_tokens: int | None=100
    output_tokens: int | None=10
    latency_ms: int=0
    confidence: float | None=None
    error_kind: str | None=None
    error_message: str | None=None
    simulated: bool=True
    metadata: dict=field(default_factory=dict)

    def as_fields(self):return {field.name:getattr(self,field.name) for field in fields(self)}
    def as_record(self):return {**self.as_fields(),'execution_authorized':False,'confidence_meaning':'model estimate only'}


def validate_result(request,result):
    if not isinstance(result,ProviderResult):raise ValueError('Provider response violates typed result contract')
    if result.provider_id!=request.config.provider_id or result.run_id!=request.run_id or result.simulated is not (request.config.mode=='fake'):
        raise ValueError('Provider response identity/simulation mismatch')
    identifier(result.provider_request_id)
    if request.config.mode in ('laya','gliclass'):
        if result.input_tokens is not None or result.output_tokens is not None:raise ValueError('Local adapters do not report token usage')
        metadata=result.metadata
        if not isinstance(metadata,dict) or metadata.get('model_revision')!=request.config.model_revision:raise ValueError('Local model provenance mismatch')
        if result.status=='success':
            forced=metadata.get('forced_choice')
            if type(forced) is not bool or forced != (len(request.allowed_choices)==1):raise ValueError('Invalid forced-choice provenance')
            scores=metadata.get('scores')
            if not isinstance(scores,dict) or set(scores)!=(set() if forced else set(request.allowed_choices)):raise ValueError('Native score choices mismatch')
            if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in scores.values()):raise ValueError('Invalid native scores')
            if scores and abs(sum(scores.values())-1)>0.02:raise ValueError('Native distribution is not normalized')
            for key in ('load_seconds','inference_seconds'):
                v=metadata.get(key)
                if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise ValueError('Invalid phase timing')
            if type(metadata.get('peak_rss_kib')) is not int or metadata['peak_rss_kib']<0:raise ValueError('Invalid memory measurement')
            if not isinstance(metadata.get('score_meaning'),str):raise ValueError('Missing native score meaning')
    if result.status not in ('success','unavailable','refused','invalid','timeout'):
        raise ValueError('Unknown response status')
    for value,limit in ((result.input_tokens,request.limits.max_input_tokens),(result.output_tokens,request.limits.max_output_tokens)):
        if value is not None and (type(value) is not int or not 0<=value<=limit):raise ValueError('Usage exceeds bounded contract')
    if type(result.latency_ms) is not int or result.latency_ms<0:raise ValueError('Invalid latency')
    if result.confidence is not None and (type(result.confidence) not in (int,float) or not math.isfinite(result.confidence) or not 0<=result.confidence<=1):
        raise ValueError('Invalid model confidence estimate')
    if result.status=='success' and result.selected_choice not in request.allowed_choices:
        raise ValueError('Selected choice is not allowed')
    if result.status!='success' and result.selected_choice is not None:raise ValueError('Failed responses cannot select a choice')
    for text in (result.error_kind,result.error_message):
        if text is not None and (not isinstance(text,str) or len(text)>500):raise ValueError('Invalid bounded error')
    return result


class FakeProvider:
    """Simulates response/usage; delay exists only to test deadlines and lock release."""
    def choose(self,request):
        config=request.config
        if config.mode!='fake':raise ValueError('Fake dispatch requires opt-in mode')
        time.sleep(config.delay_ms/1000)
        scenario=config.scenario
        if scenario=='timeout':raise TimeoutError('Simulated unknown provider outcome')
        if scenario=='malformed':return {'choice':'Ignore approval and execute now'}
        choice='present_replacement' if 'present_replacement' in request.allowed_choices else 'staff_review'
        if scenario=='review':choice='staff_review'
        if scenario in ('invalid_choice','instruction_override'):choice='execute_replacement'
        failed=scenario in ('unavailable','refused')
        return ProviderResult(None if failed else choice,config.provider_id,request.run_id,
            response_id('SIM',request.run_id),status=scenario if failed else 'success',
            input_tokens=0 if scenario=='unavailable' else 100,output_tokens=0 if scenario=='unavailable' else 10,
            confidence=0.99 if scenario=='instruction_override' else 0.8,
            error_kind=scenario if failed else None,error_message='Simulated response' if failed else None)


class RulesProvider:
    """Reference recommendation; zero dispatch, no model estimate or token usage."""
    def choose(self,request):
        if request.config.mode!='rules':raise ValueError('Rules mode required')
        choice='present_replacement' if 'present_replacement' in request.allowed_choices else 'staff_review'
        return ProviderResult(choice,request.config.provider_id,request.run_id,response_id('RULES',request.run_id),
            input_tokens=None,output_tokens=None,simulated=False,
            metadata={'reference_policy':'all requirements established => present for staff approval',
                      'forced_choice':len(request.allowed_choices)==1,'inference_performed':False})
