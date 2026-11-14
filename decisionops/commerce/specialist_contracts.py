"""Pure bounded specialist requests and decisions; no execution authority."""
from dataclasses import dataclass
import json

from .adaptive_policies import Action

CONTRACT = 'commerce-specialist-action/v1'
MAX_DECISIONS = 4
MAX_DECISION_MS = 5000
SPECIALIST_TOOLS = {'order': ('payment', 'fulfilment'),
                    'shipment': ('carrier_loss', 'fulfilment')}
OBSERVATION_FEATURES = {'tool', 'value', 'status', 'reason', 'scope_known', 'scope_reasons'}


def _copy(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError, RecursionError):
        raise ValueError('Specialist input must be finite JSON') from None


def _bounded(value, limit):
    result = _copy(value)
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > limit:
        raise ValueError('Specialist input exceeds byte cap')
    return result


def _scoped_action(specialist, action):
    if not isinstance(action, Action):
        try:
            action = Action.from_record(action)
        except (TypeError, KeyError):
            raise ValueError('Malformed specialist action') from None
    if not (action.kind == 'request_review' or
            action.kind == 'read' and action.tool in SPECIALIST_TOOLS[specialist]):
        raise ValueError('Specialist action exceeds read/review authority')
    return action


@dataclass(frozen=True)
class SpecialistRequest:
    run_id: str
    call_id: str
    specialist: str
    ordinal: int
    created_token: str
    generation: int
    case_revision: int
    report: str
    projection: dict
    allowed: tuple[Action, ...]
    attempts: tuple[dict, ...]
    budgets: dict

    def __post_init__(self):
        if not isinstance(self.specialist, str) or self.specialist not in SPECIALIST_TOOLS:
            raise ValueError('Unknown specialist')
        for value in (self.run_id, self.call_id, self.created_token):
            if not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 256:
                raise ValueError('Invalid specialist audit identity')
        if (type(self.ordinal) is not int or not 1 <= self.ordinal <= MAX_DECISIONS or
            type(self.generation) is not int or self.generation < 1 or
            type(self.case_revision) is not int or self.case_revision < 0):
            raise ValueError('Invalid specialist binding')
        if not isinstance(self.report, str) or len(self.report.encode('utf-8')) > 2000:
            raise ValueError('Report exceeds 2000 UTF-8 bytes')
        if not isinstance(self.projection, dict):
            raise ValueError('Projection must be an object')
        projection = _bounded(self.projection, 8192)
        if not isinstance(projection.get('observations', []), list) or any(
                not isinstance(row, dict) for row in projection.get('observations', [])):
            raise ValueError('Observations must be objects')
        if not isinstance(self.allowed, tuple) or not 1 <= len(self.allowed) <= 5:
            raise ValueError('Allowed actions must be a bounded tuple')
        allowed = tuple(_scoped_action(self.specialist, a) for a in self.allowed)
        if len(set(allowed)) != len(allowed):
            raise ValueError('Duplicate allowed action')
        if not isinstance(self.attempts, tuple) or len(self.attempts) > MAX_DECISIONS:
            raise ValueError('Attempts exceed specialist cap')
        attempts = _bounded(self.attempts, 2048)
        if any(not isinstance(row, dict) or row.get('tool') not in SPECIALIST_TOOLS[self.specialist]
               for row in attempts):
            raise ValueError('Attempt outside specialist scope')
        if not isinstance(self.budgets, dict) or not {'decisions', 'remaining_ms'} <= self.budgets.keys() or not self.budgets.keys() <= {'decisions', 'remaining_ms', 'tools'}:
            raise ValueError('Invalid specialist budget keys')
        budgets = _copy(self.budgets)
        for key, cap in (('decisions', MAX_DECISIONS), ('remaining_ms', MAX_DECISION_MS), ('tools', MAX_DECISIONS)):
            if key in budgets and (type(budgets[key]) is not int or not 0 <= budgets[key] <= cap):
                raise ValueError('Invalid specialist budget')
        object.__setattr__(self, 'projection', projection)
        object.__setattr__(self, 'allowed', allowed)
        object.__setattr__(self, 'attempts', tuple(attempts))
        object.__setattr__(self, 'budgets', budgets)

    def features(self):
        observations = [{k: v for k, v in row.items() if k in OBSERVATION_FEATURES}
                        for row in self.projection.get('observations', [])
                        if row.get('tool') in ('order_manifest', 'replacement_policy') + SPECIALIST_TOOLS[self.specialist]]
        projection = {'observations': observations}
        if 'requested_items' in self.projection:
            projection['requested_items'] = self.projection['requested_items']
        return _copy(dict(specialist=self.specialist, report=self.report, observations=projection,
                          allowed_actions=[a.record() for a in self.allowed],
                          attempted_tools=[{k: v for k, v in row.items() if k in ('tool', 'status', 'reason')}
                                           for row in self.attempts],
                          remaining_budgets=self.budgets))

    def record(self):
        return _copy(dict(contract=CONTRACT, run_id=self.run_id, call_id=self.call_id,
                          specialist=self.specialist, ordinal=self.ordinal, created_token=self.created_token,
                          generation=self.generation, case_revision=self.case_revision,
                          report=self.report, projection=self.projection,
                          allowed=[a.record() for a in self.allowed], attempts=self.attempts, budgets=self.budgets))

    @classmethod
    def from_record(cls, raw):
        keys = {'contract', 'run_id', 'call_id', 'specialist', 'ordinal', 'created_token', 'generation',
                'case_revision', 'report', 'projection', 'allowed', 'attempts', 'budgets'}
        if not isinstance(raw, dict) or set(raw) != keys or raw['contract'] != CONTRACT:
            raise ValueError('Invalid specialist request record')
        if not isinstance(raw['allowed'], list) or not isinstance(raw['attempts'], list):
            raise ValueError('Invalid specialist action/attempt arrays')
        fields = {k: v for k, v in raw.items() if k != 'contract'}
        fields['allowed'] = tuple(raw['allowed'])
        fields['attempts'] = tuple(raw['attempts'])
        return cls(**fields)


def validate_action(request, raw):
    action = _scoped_action(request.specialist, raw)
    if action not in request.allowed:
        raise ValueError('Specialist selected an unlisted action')
    return action


class MockSpecialist:
    """Deterministic simulated specialist; report cues change actual read choices."""
    def choose(self, request, cancel=None):
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Specialist cancelled')
        if request.budgets['decisions'] <= 0 or request.budgets['remaining_ms'] <= 0:
            raise RuntimeError('Specialist budget exhausted')
        report = request.report.lower()
        if request.specialist == 'order':
            preferred = ('payment', 'fulfilment') if 'payment' in report else ('fulfilment', 'payment')
        else:
            preferred = ('fulfilment', 'carrier_loss') if 'refresh' in report else ('carrier_loss', 'fulfilment')
        reads = [a for a in request.allowed if a.kind == 'read']
        if reads:
            selected = min(reads, key=lambda a: (sum(row['tool'] == a.tool for row in request.attempts), preferred.index(a.tool)))
        else:
            selected = next(a for a in request.allowed if a.kind == 'request_review')
        return validate_action(request, selected)


RESULT_STATUSES = frozenset({'complete', 'missing', 'unavailable', 'stale',
                             'conflicting', 'review', 'uncertain', 'pending'})


def _timestamp(value):
    from datetime import datetime
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValueError('Specialist result timestamp must be ISO text')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid specialist result timestamp') from None
    if 'T' not in value or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Specialist result timestamp requires time and timezone')
    return parsed


@dataclass(frozen=True)
class SpecialistResult:
    specialist: str
    run_id: str
    generation: int
    case_revision: int
    status: str
    observation_ids: tuple[str, ...]
    observed_at: str
    deadline: str
    reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.specialist, str) or self.specialist not in SPECIALIST_TOOLS:
            raise ValueError('Unknown result specialist')
        if not isinstance(self.run_id, str) or not 1 <= len(self.run_id.encode('utf-8')) <= 256:
            raise ValueError('Invalid specialist result run binding')
        if (type(self.generation) is not int or self.generation < 1 or
                type(self.case_revision) is not int or self.case_revision < 0):
            raise ValueError('Invalid specialist result generation/revision')
        if not isinstance(self.status, str) or self.status not in RESULT_STATUSES:
            raise ValueError('Invalid specialist result status')
        if not isinstance(self.observation_ids, tuple) or len(self.observation_ids) > MAX_DECISIONS:
            raise ValueError('Invalid specialist result observation list')
        if any(not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 256
               for value in self.observation_ids):
            raise ValueError('Invalid specialist result observation identity')
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError('Duplicate specialist result observation')
        _timestamp(self.observed_at)
        _timestamp(self.deadline)
        # Stale/uncertain results may be collected after their bound deadline.
        if self.reason is not None and (not isinstance(self.reason, str) or
                not 1 <= len(self.reason.encode('utf-8')) <= 512):
            raise ValueError('Invalid specialist result reason')

    def record(self):
        return dict(specialist=self.specialist, run_id=self.run_id, generation=self.generation,
                    case_revision=self.case_revision, status=self.status,
                    observation_ids=list(self.observation_ids), observed_at=self.observed_at,
                    deadline=self.deadline, reason=self.reason)

    @classmethod
    def from_record(cls, raw):
        keys = {'specialist', 'run_id', 'generation', 'case_revision', 'status',
                'observation_ids', 'observed_at', 'deadline', 'reason'}
        if not isinstance(raw, dict) or set(raw) != keys or not isinstance(raw['observation_ids'], list):
            raise ValueError('Invalid specialist result record')
        return cls(**dict(raw, observation_ids=tuple(raw['observation_ids'])))
