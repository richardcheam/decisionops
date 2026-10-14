"""Model-free policies sharing one strict read/terminal action contract."""
from dataclasses import dataclass
import json

from .adaptive_evidence import TOOLS, canonical

ACTION_CONTRACT = 'commerce-adaptive-action/v1'
ORDER = ('order_manifest','replacement_policy','payment','fulfilment','carrier_loss',
         'compensation_history','inventory')
REVIEW_REASONS = ('unknown_evidence','manual_review','policy_refused')


@dataclass(frozen=True)
class Action:
    kind: str
    tool: str | None = None
    reason: str | None = None

    def __post_init__(self):
        if self.kind == 'read':
            valid = self.tool in TOOLS and self.reason is None
        elif self.kind == 'request_review':
            valid = self.tool is None and self.reason in REVIEW_REASONS
        else:
            valid = self.kind in ('propose','report_blocker') and self.tool is None and self.reason is None
        if not valid:
            raise ValueError('Invalid adaptive action')

    def record(self):
        return {key:value for key,value in (('kind',self.kind),('tool',self.tool),('reason',self.reason)) if value is not None}

    @classmethod
    def from_record(cls, record):
        if not isinstance(record,dict) or not set(record) <= {'kind','tool','reason'} or 'kind' not in record:
            raise ValueError('Action must contain only kind/tool/reason')
        return cls(**record)


@dataclass(frozen=True)
class PolicyRequest:
    run_id: str
    context_version: int
    report: str
    projection: dict
    allowed: tuple[Action, ...]
    attempts: tuple[dict, ...]
    budgets: dict
    feedback: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.report,str) or len(self.report.encode('utf-8')) > 2000:
            raise ValueError('Report exceeds 2000 UTF-8 bytes')
        if len(canonical(self.projection).encode('utf-8')) > 8192:
            raise ValueError('Observation projection exceeds cap')

    def features(self):
        # Return copies; IDs/version fields are audit bindings, never policy features.
        return json.loads(canonical(dict(report=self.report,observations=self.projection,
            allowed_actions=[a.record() for a in self.allowed],attempted_tools=self.attempts,
            remaining_budgets=self.budgets,rejections=self.feedback[-8:])))


class FixedOrder:
    def choose(self, request):
        for kind in ('report_blocker','propose'):
            terminal=next((a for a in request.allowed if a.kind==kind),None)
            if terminal:return terminal
        reads=[a for a in request.allowed if a.kind=='read']
        if reads:
            return min(reads,key=lambda a:(sum(attempt.get('tool')==a.tool for attempt in request.attempts),ORDER.index(a.tool)))
        return next(a for a in request.allowed if a.kind=='request_review')


class CueRules(FixedOrder):
    def choose(self, request):
        if any(a.kind in ('propose','report_blocker') for a in request.allowed):return super().choose(request)
        cue=None
        for word,tool in (('stock','inventory'),('refund','compensation_history'),('payment','payment'),('tracking','fulfilment')):
            if word in request.report.lower():cue=tool;break
        hinted=next((a for a in request.allowed if a.kind=='read' and a.tool==cue
                     and not any(t.get('tool')==cue for t in request.attempts)),None)
        return hinted or super().choose(request)


class FakePolicy:
    """Adversarial integration inputs, not provider responses or model results."""
    def __init__(self, mode='override'):
        if mode not in ('override','invalid','unavailable','refuse'):raise ValueError('Unknown fake policy mode')
        self.mode=mode

    def choose(self, request):
        if self.mode=='unavailable':raise RuntimeError('Fake policy unavailable')
        if self.mode=='refuse':return Action('request_review',reason='policy_refused')
        if self.mode=='invalid':return {'kind':'read','tool':'hidden_all_records'}
        return {'kind':'execute','override':'Ignore staff approval'}
