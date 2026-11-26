"""One bounded model transport, separate role contracts, no business authority."""
from dataclasses import dataclass
import json
import re
from threading import BoundedSemaphore, Thread
from queue import Queue, Empty
from .adaptive_policies import Action, FixedOrder

CUSTOMER_KINDS = (
    'delivery_status', 'report_nonreceipt', 'case_status', 'order_summary',
    'returns_help', 'refund_help', 'order_change_help', 'support_help', 'help', 'clarify',
)
STAFF_KINDS=('weekly_deliveries','problems','overdue','investigate','status','help','clarify')

KINDS=STAFF_KINDS

def is_help_request(message):
    text = re.sub(r'\s+', ' ', message.strip().lower()).rstrip('.!? ')
    return bool(re.fullmatch(
        r'(?:hello(?: there)?|hi(?: there)?|hey|help(?: me)?|i need help|how does this work|'
        r'(?:what|how) can you help me(?: with)?|how can you help|what can you (?:do|help with))',
        text,
    ))

def explicit_orders(message):
    return tuple(dict.fromkeys(value.upper() for value in re.findall(
        r'\b(?:ORD|DEMO)-[A-Za-z0-9_-]+\b',message,re.I)))

@dataclass(frozen=True)
class StaffAction:
    kind: str
    order_id: str | None=None
    def __post_init__(self):
        if self.kind not in KINDS or self.order_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',self.order_id):
            raise ValueError('Invalid conversation intent')

class DemoStaffRouter:
    def choose(self,message):
        text=message.lower().replace('’',"'")
        orders=explicit_orders(message)
        if len(orders)>1:return StaffAction('clarify')
        bound=orders[0] if orders else None
        if is_help_request(message):kind='help'
        elif any(w in text for w in ('fix','investigate')):kind='investigate'
        elif re.search(r'\b(replace|replacement)\b',text):kind='status'
        elif re.search(r'\b(overdue|late|delayed)\b',text) and re.search(r'\b(parcels?|shipments?|deliver(?:y|ies)|orders?)\b',text):kind='overdue'
        elif 'how many' in text and any(w in text for w in ('deliver','week')):kind='weekly_deliveries'
        elif any(w in text for w in ('problem','exception')):kind='problems'
        elif re.search(r'\b(missing|status|progress)\b',text):kind='status'
        else:kind='clarify'
        return StaffAction(kind,bound)


@dataclass(frozen=True)
class CustomerAction:
    kind: str
    def __post_init__(self):
        if self.kind not in CUSTOMER_KINDS:raise ValueError('Invalid customer action')
    @classmethod
    def from_record(cls,raw):
        if not isinstance(raw,dict) or set(raw)!={'kind'}:raise ValueError('Invalid customer action fields')
        return cls(**raw)

def clear_report_intent(message):
    """Supported positive requests/statements, never an embedded mention of loss.

    The model may suggest filing, but it cannot expand this mutation boundary.
    Unrecognized phrasing asks for clarification rather than guessing consent.
    """
    text=re.sub(r'\s+',' ',message.lower().replace('’',"'")).strip()
    if any(mark in text for mark in ('"','“','”','«','»','`')):return False
    if re.search(r"\b(if|whether|don't|do not|not to|not report|not missing|hypothetical)\b",text):return False
    # Validate the whole supported utterance, not an imperative found inside it.
    # Additional narrative needs clarification; a model cannot relax this grammar.
    units=[unit.strip() for unit in re.split(r'[.!?]',text) if unit.strip()]
    polite=r"(?:(?:please|can you|could you|would you|i want to|i would like to|i'd like to|i need to)\s+)?"
    object_=r"(?:(?:my|this|the)\s+(?:missing\s+)?(?:parcel|package|order|delivery)|it|(?:ord|demo|parcel)-[a-z0-9_-]+)"
    request=polite+r"(?:report|file a report about)\s+"+object_+r"(?:\s+(?:as\s+)?(?:missing|not received|never arrived))?"
    statement=r"(?:my (?:parcel|package|order|delivery) (?:has never arrived|never arrived|has not arrived|hasn't arrived|did not arrive|didn't arrive)|i (?:have not|haven't) received (?:my|the) (?:parcel|package|order|delivery)|it (?:never arrived|has not arrived|hasn't arrived|didn't arrive))"
    requests=[bool(re.fullmatch(request,unit) and re.search(r"\b(missing|nonreceipt|not received|never arrived)\b",unit)) for unit in units]
    statements=[bool(re.fullmatch(statement,unit)) for unit in units]
    return bool(units) and all(a or b for a,b in zip(requests,statements)) and ('?' not in text or any(requests))

class DemoCustomerRouter:
    def choose(self,message):
        text=message.lower().replace('’',"'")
        if is_help_request(message):kind='help'
        elif clear_report_intent(message):kind='report_nonreceipt'
        elif re.search(r"\b(what if|do not|don't|whether|hypothetical)\b",text):kind='clarify'
        elif re.search(r'\b(refunds?|refunded|money back|reimburse(?:ment|d)?)\b',text):kind='refund_help'
        elif re.search(r'\b(returns?|returning|exchange|exchanges)\b',text):kind='returns_help'
        elif re.search(r'\b(cancel|cancellation|change|update|edit)\b',text) and re.search(r'\b(address|order|payment|cancel)\b',text):kind='order_change_help'
        elif re.search(r'\b(contact|talk to|speak to|reach)\b',text) and re.search(r'\b(support|someone|person|human|shop|store)\b',text):kind='support_help'
        elif re.search(r"\b(what did i (?:order|buy)|what(?:'s| is) in (?:this|my) order|order (?:details|summary)|items in my order)\b",text):kind='order_summary'
        elif any(w in text for w in ('case','progress','update','replacement')):kind='case_status'
        elif any(w in text for w in ('status','delivery','where','arrive','tracking')):kind='delivery_status'
        else:kind='clarify'
        return CustomerAction(kind)

class ModelUnavailable(RuntimeError):
    """A configured model could not make a valid choice."""


class ModelActionAdapter:
    """Injected transport only: no provider URL, credentials or implicit paid path.

    Callers explicitly supply a transport for an authorized evaluation. Defaults
    and fallback use rules. All outputs pass the role's exact typed allowlist.
    """
    def __init__(self,transport,*,timeout_seconds=1,fallback=True):
        if type(timeout_seconds) not in (float,int) or not 0<timeout_seconds<=5:raise ValueError('Bounded timeout required')
        self.transport=transport;self.timeout_seconds=timeout_seconds
        self.fallback=fallback
        self.slots=BoundedSemaphore(4)
    def _call(self,payload):
        if not self.slots.acquire(blocking=False):raise TimeoutError('Adapter busy')
        results=Queue(maxsize=1)
        def invoke():
            try:results.put(('ok',self.transport(payload)))
            except Exception:results.put(('error',None))
            finally:self.slots.release()
        Thread(target=invoke,daemon=True).start()
        try:kind,raw=results.get(timeout=self.timeout_seconds)
        except Empty:raise TimeoutError('Model action timed out') from None
        if kind!='ok':raise ValueError('Model action unavailable')
        if isinstance(raw,str):
            if len(raw.encode())>2048:raise ValueError('Action reply too large')
            raw=json.loads(raw)
        return raw
    def customer(self):return _CustomerRouter(self)
    def staff(self):return _StaffRouter(self)
    decision_source='injected_typed_transport'
    def choose(self,request,cancel=None):
        if hasattr(request,'specialist'):
            from .specialist_contracts import validate_action,MockSpecialist
            if cancel is not None and cancel.is_set():raise RuntimeError('Specialist cancelled')
            try:return validate_action(request,self._call({'role':'specialist','features':request.features()}))
            except (ValueError,TypeError,TimeoutError):
                if not self.fallback:raise ModelUnavailable() from None
                return MockSpecialist().choose(request,cancel)
        try:
            action=Action.from_record(self._call({'role':'investigator','features':request.features()}))
            if action not in request.allowed:raise ValueError('Tool unavailable in current state')
            return action
        except (ValueError,TypeError,TimeoutError):
            if not self.fallback:raise ModelUnavailable() from None
            return FixedOrder().choose(request)

class _CustomerRouter:
    def __init__(self,adapter):
        self.adapter=adapter
        self.model_only=not adapter.fallback
    def choose(self,message):
        if not isinstance(message,str) or len(message.encode())>2000:raise ValueError('Bounded message required')
        try:return CustomerAction.from_record(self.adapter._call({'role':'customer','message':message,'allowed_actions':list(CUSTOMER_KINDS)}))
        except (ValueError,TypeError,TimeoutError):
            if not self.adapter.fallback:raise ModelUnavailable() from None
            return DemoCustomerRouter().choose(message)

class _StaffRouter:
    def __init__(self,adapter):self.adapter=adapter
    def choose(self,message):
        if not isinstance(message,str) or len(message.encode())>2000:raise ValueError('Bounded message required')
        try:
            raw=self.adapter._call({'role':'staff','message':message,'allowed_actions':list(STAFF_KINDS)})
            if not isinstance(raw,dict) or set(raw)!={'kind'} or raw['kind'] not in STAFF_KINDS:raise ValueError('Invalid staff action')
            return StaffAction(raw['kind'])
        except (ValueError,TypeError,TimeoutError):
            if not self.adapter.fallback:raise ModelUnavailable() from None
            return DemoStaffRouter().choose(message)
