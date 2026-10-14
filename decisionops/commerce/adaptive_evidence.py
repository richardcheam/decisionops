"""V2 selectable-read observations. No database, model, proposal or case writes."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import uuid

from .evidence import assess_evidence, utc_timestamp
from .eligibility import evaluate_eligibility

CONTRACT = 'commerce-adaptive-observation/v2'
TOOLS = {
    'order_manifest': 'quantities_valid',
    'replacement_policy': 'policy_permits',
    'payment': 'paid',
    'fulfilment': 'shipped',
    'carrier_loss': 'loss_confirmed',
    'compensation_history': 'no_previous_compensation',
    'inventory': 'stock_available',
}
SCOPE_TOOLS = ('order_manifest', 'fulfilment', 'compensation_history')
TRUSTED_SOURCES = {fact: 'postgres-adaptive-v2-' + tool for tool, fact in TOOLS.items()}

POLICY_REASONS = frozenset({
    'order_or_lines_missing', 'conflicting_records', 'policy_missing', 'payment_missing',
    'shipment_missing_or_wrong_order', 'shipment_lines_missing', 'carrier_record_missing',
    'carrier_event_stale_or_future', 'loss_not_confirmed', 'history_marker_missing',
    'history_incomplete', 'inventory_missing', 'database_error', 'malformed_records',
    'dependency_cycle', 'future_timestamp', 'expired', 'dependency_changed',
    'dependency_ambiguous', 'dependency_unresolved', 'conflicting_active_contents',
})
POLICY_SCOPE_REASONS = frozenset({
    'partial_request', 'split_shipment', 'partial_shipment',
    'shipment_order_mismatch', 'partial_compensation',
})


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False,
                      default=lambda value: value.isoformat())


@dataclass(frozen=True)
class Observation:
    id: str
    content: str
    observed_at: str
    expires_at: str

    def record(self):
        """Deserialize a fresh copy; callers cannot mutate retained history."""
        return {**json.loads(self.content), 'id': self.id,
                'observed_at': self.observed_at, 'expires_at': self.expires_at,
                'source_version': self.version}

    @property
    def version(self):
        # Dependency observation IDs are provenance, not content identity.
        content = json.loads(self.content)
        content['dependencies'] = sorted(dep[:3] for dep in content['dependencies'])
        return hashlib.sha256(canonical(content).encode()).hexdigest()

    @property
    def value(self):
        return json.loads(self.content)['value']

    def dependency(self):
        record = self.record()
        return (record['tool'], record['stream'], self.version, self.id)


def observation(tool, request, now, *, value, payload, status='success', stream='primary',
                dependencies=(), scope_known=False, scope_reasons=(), reason=None, expires_at=None):
    if tool not in TOOLS or status not in ('success', 'missing', 'unavailable'):
        raise ValueError('Unknown tool or status')
    if value is not True and value is not False and value is not None:
        raise ValueError('Fact must be boolean or unknown')
    utc_timestamp(now.isoformat())
    expiry = expires_at or now + timedelta(days=1)
    utc_timestamp(expiry.isoformat())
    if type(scope_known) is not bool or not isinstance(stream, str) or not stream:
        raise ValueError('Invalid scope or stream')
    content = canonical(dict(contract=CONTRACT, tool=tool, request=request, value=value,
                             payload=payload, status=status, stream=stream,
                             dependencies=dependencies, scope_known=scope_known,
                             scope_reasons=scope_reasons, reason=reason))
    return Observation('OBS-' + uuid.uuid4().hex, content, now.isoformat(), expiry.isoformat())


class History:
    """Append-only observations plus explicit supersession edges; no SQL on inspection."""
    def __init__(self, request, *, streams=('primary',)):
        self._request = canonical(request)
        self._streams = frozenset(streams)
        self._observations = ()
        self._supersessions = ()

    @property
    def request(self):
        return json.loads(self._request)

    @property
    def streams(self):
        return self._streams

    @property
    def observations(self):
        return self._observations

    @property
    def supersessions(self):
        return self._supersessions

    def active(self, tool=None):
        retired = {old for old, new in self._supersessions}
        return tuple(obs for obs in self._observations if obs.id not in retired
                     and (tool is None or obs.record()['tool'] == tool))

    def append(self, obs, *, supersedes=None):
        record = obs.record()
        if (record.get('contract') != CONTRACT or record.get('tool') not in TOOLS
                or canonical(record['request']) != self._request
                or record['stream'] not in self._streams):
            raise ValueError('Wrong request, contract or untrusted stream')
        if any(old.id == obs.id for old in self._observations):
            raise ValueError('Observation ID already recorded')
        utc_timestamp(obs.observed_at)
        utc_timestamp(obs.expires_at)
        for tool, stream, version, identifier in record['dependencies']:
            if not any(old.id == identifier and old.dependency()[:3] == (tool, stream, version)
                       for old in self._observations):
                raise ValueError('Dependency not recorded in this history')
        if supersedes is not None:
            predecessor = next((old for old in self.active() if old.id == supersedes), None)
            if predecessor is None or predecessor.dependency()[:2] != obs.dependency()[:2]:
                raise ValueError('Refresh must name an active predecessor in the same stream/tool')
            if utc_timestamp(obs.observed_at) < utc_timestamp(predecessor.observed_at):
                raise ValueError('Refresh cannot predate its predecessor')
            self._supersessions += ((predecessor.id, obs.id),)
        self._observations += (obs,)

    def invalid_reason(self, obs, now, trail=()):
        record = obs.record()
        if obs.id in trail:
            return 'dependency_cycle'
        if now < utc_timestamp(obs.observed_at):
            return 'future_timestamp'
        if ((now - utc_timestamp(obs.observed_at)).total_seconds() > 86400
                or now > utc_timestamp(obs.expires_at)):
            return 'expired'
        for tool, stream, version, identifier in record['dependencies']:
            current = self.active(tool)
            bound = [dep for dep in current if dep.dependency()[:3] == (tool, stream, version)]
            if not bound:
                return 'dependency_changed'
            if len({dep.version for dep in current}) != 1:
                return 'dependency_ambiguous'
            values = {dep.value for dep in current}
            if (len(values) != 1 or None in values
                    or any(dep.record()['status'] != 'success'
                           or self.invalid_reason(dep, now, trail + (obs.id,)) for dep in current)):
                return 'dependency_unresolved'
        return None

    def select(self, tool, now):
        """A dependency must have a single current content binding, not just a majority value."""
        candidates = self.active(tool)
        if (not candidates or any(self.invalid_reason(obs, now)
                                  or obs.record()['status'] != 'success'
                                  or obs.value is None for obs in candidates)
                or len({obs.version for obs in candidates}) != 1):
            raise ValueError('Dependency missing, conflicting, expired or changed: ' + tool)
        return candidates[-1]

    def content_conflict(self, tool):
        return len({obs.version for obs in self.active(tool)}) > 1

    def policy_view(self, now, *, max_bytes=8192):
        """Bounded selected observations only; no audit IDs, rows, hashes or assessment.

        This is a data projection, not an adaptive policy or decision loop. Oversize
        contexts fail explicitly rather than silently truncating business evidence.
        """
        utc_timestamp(now.isoformat())
        if type(max_bytes) is not int or not 1 <= max_bytes <= 8192:
            raise ValueError('Policy view limit must be 1..8192 bytes')
        selected = []
        for obs in self.active():
            record = obs.record()
            invalid = self.invalid_reason(obs, now)
            if not invalid and self.content_conflict(record['tool']):
                invalid = 'conflicting_active_contents'
            reason = invalid or record['reason']
            if reason is not None and reason not in POLICY_REASONS:
                reason = 'unclassified_read_failure'
            selected.append({
                'tool':record['tool'], 'value':None if invalid else record['value'],
                'status':'unavailable' if invalid else record['status'], 'reason':reason,
                'scope_known':record['scope_known'] and not invalid,
                'scope_reasons':[code if code in POLICY_SCOPE_REASONS else 'unresolved_scope'
                                 for code in record['scope_reasons']],
            })
        view = {'requested_items':self.request['items'], 'observations':selected}
        if len(canonical(view).encode('utf-8')) > max_bytes:
            raise ValueError('Policy view exceeds byte budget')
        return view

    def assess(self, now):
        records = []
        scopes = []
        scope_complete = True
        for tool in SCOPE_TOOLS:
            active = self.active(tool)
            if not active or self.content_conflict(tool) or any(self.invalid_reason(obs, now) or not obs.record()['scope_known']
                                 or obs.record()['status'] != 'success' for obs in active):
                scope_complete = False
            for obs in active:
                if not self.invalid_reason(obs, now):
                    scopes.extend(obs.record()['scope_reasons'])
        for obs in self.active():
            record = obs.record()
            invalid = self.invalid_reason(obs, now)
            records.append(dict(requirement=TOOLS[record['tool']], value=None if invalid else record['value'],
                                status='unavailable' if invalid else record['status'],
                                source_id=TRUSTED_SOURCES[TOOLS[record['tool']]], source_version=obs.version,
                                order_id=self.request['order_id'], observed_at=obs.observed_at,
                                details={'observation_id':obs.id, 'reason':invalid or record['reason']}))
        scopes = sorted(set(scopes))
        result = assess_evidence(records, order_id=self.request['order_id'],
                                 supported_case=scope_complete and not scopes, now=now,
                                 trusted_sources=TRUSTED_SOURCES, max_age_seconds=86400)
        for tool, requirement in TOOLS.items():
            if self.content_conflict(tool):
                result['facts'][requirement] = None
                result['issues'][requirement].append('conflicting_active_contents')
        result['decision'] = evaluate_eligibility(result['facts'])
        if not scope_complete or scopes:
            result['decision']['status'] = 'needs_review'
        result.update(contract=CONTRACT, request=self.request, scope_complete=scope_complete,
                      scope_reasons=scopes, observations=[obs.record() for obs in self._observations],
                      supersessions=list(self._supersessions))
        if not scope_complete and not scopes:
            result['scope_issue'] = 'scope_unresolved'
        return result
