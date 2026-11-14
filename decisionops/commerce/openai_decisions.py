"""Versioned POST /v1/decisions contract; no optional imports until dispatch."""
from dataclasses import dataclass,asdict
from decimal import Decimal,ROUND_CEILING
import json,math,re
from .api_decisions import OpenAIAdapter,ApiUncertain,INSTRUCTIONS
from .adaptive_recommendations import Result
from .session_protocol import strict_json

VERSION='commerce-decisions/v1'
QUESTION='investigation_action'

@dataclass(frozen=True)
class DecisionsConfig:
    budget_id:str
    endpoint:str='https://api.openai.com/v1'
    model:str='gpt-6-luna'
    pricing_version:str='openai-decisions-standard-20261016'
    input_per_million:str='0.10'
    max_requests:int=12
    max_cost_usd:str='0.03'
    max_input_tokens:int=24576
    request_byte_limit:int=20480
    protocol_token_margin:int=4096
    version:str=VERSION
    execution:str='mock'
    def __post_init__(self):
        if self.version!=VERSION or self.endpoint!='https://api.openai.com/v1' or self.model!='gpt-6-luna':raise ValueError('Unsupported Decisions endpoint/model/version')
        if self.execution not in ('mock','live'):raise ValueError('Explicit execution required')
        if not all(isinstance(s,str) and re.fullmatch('[A-Za-z0-9_.-]{1,128}',s) for s in (self.budget_id,self.pricing_version)):raise ValueError('Invalid Decisions identity')
        if self.input_per_million!='0.10':raise ValueError('Unsupported Decisions input price')
        if any(type(v) is not int or v!=n for v,n in ((self.max_input_tokens,24576),(self.request_byte_limit,20480),(self.protocol_token_margin,4096))):raise ValueError('Invalid complete request bound')
        if type(self.max_requests) is not int or not 1<=self.max_requests<=12:raise ValueError('Invalid request count')
        if not isinstance(self.max_cost_usd,str) or not Decimal(self.max_cost_usd).is_finite() or not 0<Decimal(self.max_cost_usd)<=Decimal('0.03'):raise ValueError('Invalid monetary cap')
    def record(self):return asdict(self)
    def pricing(self):return {'version':self.pricing_version,'endpoint':'/v1/decisions','input_per_million':self.input_per_million,'basis':'complete-request-input-only'}
    def cost(self,input_tokens):
        if type(input_tokens) is not int or input_tokens<0:raise ValueError('Invalid measured Decisions input usage')
        return (Decimal(input_tokens)*Decimal(self.input_per_million)/1000000).quantize(Decimal('.00000001'),rounding=ROUND_CEILING)
    def maximum(self):return self.cost(self.max_input_tokens)

def choices(request):
    """The immutable allowed-action order defines stable, request-local values."""
    return {f'c{i:03d}':action.record() for i,action in enumerate(request.policy.allowed)}

def wire_request(request):
    cfg=DecisionsConfig(**request.api)
    body={'model':cfg.model,'input':json.dumps(request.policy.features(),ensure_ascii=False,separators=(',',':'),allow_nan=False),
          'questions':[{'type':'choice','name':QUESTION,'instructions':INSTRUCTIONS.replace('action index','choice value'),
                        'choices':[{'value':value,'description':json.dumps(action,sort_keys=True,separators=(',',':'))} for value,action in choices(request).items()]}]}
    # Includes evidence, fixed question instructions, choice descriptions and all JSON
    # framing/model fields, rather than bounding the policy input string alone.
    if len(json.dumps(body,ensure_ascii=False,allow_nan=False).encode())>cfg.request_byte_limit:raise ValueError('Complete Decisions request byte cap exceeded')
    return body

class DecisionsAdapter(OpenAIAdapter):
    version=VERSION
    async def dispatch(self,client,body,request):
        raw=await client.decisions.with_raw_response.create(**body,extra_headers={'X-Client-Request-Id':request.id})
        # Parse the capped SDK transport body strictly, including duplicate-key and
        # non-finite-number rejection; permissive SDK construction is not authority.
        try:return strict_json(raw.http_response.content)
        except (ValueError,TypeError):raise ApiUncertain('malformed_decision_document') from None
    def parse_response(self,request,config,response,elapsed):
        if not isinstance(response,dict):raise ApiUncertain('malformed_decision_document')
        usage=response.get('usage')
        if (not isinstance(usage,dict) or type(usage.get('input_tokens')) is not int or usage['input_tokens']<0
            or type(usage.get('output_tokens')) is not int or usage['output_tokens']!=0
            or type(usage.get('total_tokens')) is not int or usage['total_tokens']!=usage['input_tokens']):raise ApiUncertain('usage_unavailable_or_inconsistent')
        # No output price/count is invented. Native zero-output usage stays in audit.
        measured={'input_tokens':usage['input_tokens']}
        metadata={'usage':measured,'native_usage':usage,'provider':'openai','model':response.get('model'),
                  'api_version':VERSION,'endpoint':'/v1/decisions','question':QUESTION,
                  'inference_performed':True,'simulated_transport':config.execution=='mock'}
        status='invalid';action=None;error='invalid_decision_answer'
        try:
            answers=response['answers']
            if response.get('model')!=config.model or not isinstance(answers,list) or len(answers)!=1:raise ValueError('Answer/model mismatch')
            answer=answers[0]
            if not isinstance(answer,dict) or answer.get('name')!=QUESTION:raise ValueError('Question identity mismatch')
            if answer.get('type')=='refusal':
                error='decision_refused';raise ValueError('Refused')
            if set(answer)!={'type','name','choice','confidence','probabilities'} or answer['type']!='choice':raise ValueError('Choice schema mismatch')
            mapping=choices(request);selected=answer['choice']
            if type(selected) is not str or selected not in mapping:raise ValueError('Unknown choice')
            def probability(value):return type(value) in (int,float) and math.isfinite(value) and 0<=value<=1
            if not probability(answer['confidence']):raise ValueError('Invalid confidence')
            probs=answer['probabilities']
            if not isinstance(probs,list) or len(probs)!=len(mapping):raise ValueError('Incomplete probabilities')
            seen=[]
            for prob in probs:
                if not isinstance(prob,dict) or set(prob)!={'value','probability'} or type(prob['value']) is not str or prob['value'] not in mapping or not probability(prob['probability']):raise ValueError('Invalid probability')
                seen.append(prob['value'])
            if len(set(seen))!=len(mapping) or not math.isclose(sum(p['probability'] for p in probs),1,abs_tol=1e-5):raise ValueError('Invalid distribution')
            if usage['input_tokens']>config.max_input_tokens:raise ValueError('Usage exceeded reserved bound')
            # A model estimate is audit metadata, never evidence or permission.
            metadata.update(confidence=answer['confidence'],probabilities=probs,selected_choice=selected)
            status='success';action=mapping[selected];error=None
        except (ValueError,KeyError,TypeError):pass
        return Result(request.id,action,elapsed,status,error,metadata)
