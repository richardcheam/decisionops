"""One bounded model transport, separate role contracts, no business authority."""
from dataclasses import dataclass
import json
import re
from threading import BoundedSemaphore, Thread
from queue import Queue, Empty
from .adaptive_policies import Action, FixedOrder

CUSTOMER_KINDS=('delivery_status','report_nonreceipt','case_status','clarify')
STAFF_KINDS=('weekly_deliveries','problems','investigate','status','clarify')

KINDS=STAFF_KINDS

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
        if 'how many' in text and any(w in text for w in ('deliver','week')):kind='weekly_deliveries'
        elif any(w in text for w in ('problem','exception')):kind='problems'
        elif any(w in text for w in ('fix','investigate')):kind='investigate'
        elif any(w in text for w in ('missing','status','progress')):kind='status'
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
    text=message.lower().replace('’',"'")
    if re.search(r"\b(what if|if |don't|do not|not to|cancel|hypothetical|whether)\b",text):return False
    explicit=bool(re.search(r"\b(report|file)\b.*\b(missing|nonreceipt|not received)\b",text))
    if explicit:
        return not bool(re.search(r"\b(how do|should i|can i|how would|what happens)\b",text))
    if '?' in text or re.search(r"\b(check|can|could|would|suppose|wonder)\b",text):return False
    return bool(re.search(r"\b(never arrived|not received|haven't received|didn't arrive|hasn't arrived)\b",text))

class DemoCustomerRouter:
    def choose(self,message):
        text=message.lower().replace('’',"'")
        if clear_report_intent(message):kind='report_nonreceipt'
        elif re.search(r"\b(what if|do not|don't|whether|hypothetical)\b",text):kind='clarify'
        elif any(w in text for w in ('case','progress','update','replacement')):kind='case_status'
        elif any(w in text for w in ('status','delivery','where','arrive','tracking')):kind='delivery_status'
        else:kind='clarify'
        return CustomerAction(kind)

class ModelActionAdapter:
    """Injected transport only: no provider URL, credentials or implicit paid path.

    Callers explicitly supply a transport for an authorized evaluation. Defaults
    and fallback use rules. All outputs pass the role's exact typed allowlist.
    """
    def __init__(self,transport,*,timeout_seconds=1):
        if type(timeout_seconds) not in (float,int) or not 0<timeout_seconds<=5:raise ValueError('Bounded timeout required')
        self.transport=transport;self.timeout_seconds=timeout_seconds
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
            except (ValueError,TypeError,TimeoutError):return MockSpecialist().choose(request,cancel)
        try:
            action=Action.from_record(self._call({'role':'investigator','features':request.features()}))
            if action not in request.allowed:raise ValueError('Tool unavailable in current state')
            return action
        except (ValueError,TypeError,TimeoutError):return FixedOrder().choose(request)

class _CustomerRouter:
    def __init__(self,adapter):self.adapter=adapter
    def choose(self,message):
        if not isinstance(message,str) or len(message.encode())>2000:raise ValueError('Bounded message required')
        try:return CustomerAction.from_record(self.adapter._call({'role':'customer','message':message,'allowed_actions':list(CUSTOMER_KINDS)}))
        except (ValueError,TypeError,TimeoutError):return DemoCustomerRouter().choose(message)

class _StaffRouter:
    def __init__(self,adapter):self.adapter=adapter
    def choose(self,message):
        if not isinstance(message,str) or len(message.encode())>2000:raise ValueError('Bounded message required')
        try:
            raw=self.adapter._call({'role':'staff','message':message,'allowed_actions':list(STAFF_KINDS)})
            if not isinstance(raw,dict) or set(raw)!={'kind'} or raw['kind'] not in STAFF_KINDS:raise ValueError('Invalid staff action')
            return StaffAction(raw['kind'])
        except (ValueError,TypeError,TimeoutError):return DemoStaffRouter().choose(message)
