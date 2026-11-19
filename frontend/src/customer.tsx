import React, { useEffect, useRef, useState } from 'react';
import './customer.css';

type CustomerSession = { customer_id: string; display_name: string; store_id: string; role: 'customer' };
type Parcel = { shipment_id: string; status?: string; promised_at?: string };
type CustomerOrder = { id: string; parcels: Parcel[] };
type CustomerReply = { intent: string; text: string; case_id?: string; parcels?: Parcel[] };
type CaseUpdate = { case_id: string; order_id: string; shipment_id: string; status: string; text: string; replacement_created: boolean; shipped: boolean };
type CustomerConversation = {
  id: string;
  selected_order_id: string | null;
  selected_shipment_id: string | null;
  messages: { message: string; response: CustomerReply }[];
  cases: CaseUpdate[];
};

class CustomerRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

/** Authentication and ownership are resolved by the server; this component only presents its allowlisted customer views. */
export function CustomerPortal() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [auth, setAuth] = useState<string | null>(null);
  const [session, setSession] = useState<CustomerSession | null>(null);
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const [conversation, setConversation] = useState<CustomerConversation | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const currentLogin = useRef(0);
  const composer = useRef<HTMLInputElement>(null);

  async function request<T>(path: string, credentials: string, body?: object): Promise<T> {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch('/customer-api' + path, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { Authorization: credentials, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: controller.signal,
        cache: 'no-store',
      });
      if (!response.ok) {
        if (response.status === 401) throw new CustomerRequestError('Please check your customer username and password.', response.status);
        if (response.status === 404) throw new CustomerRequestError('That order or conversation is not available to this account.', response.status);
        throw new CustomerRequestError('We could not finish that request. Please try again.', response.status);
      }
      return await response.json() as T;
    } finally { window.clearTimeout(timer); }
  }

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    const login = ++currentLogin.current;
    setBusy(true); setError('');
    try {
      // UTF-8 encoding keeps non-ASCII credentials from crashing the form.
      const bytes = new TextEncoder().encode(username + ':' + password);
      const credentials = 'Basic ' + btoa(Array.from(bytes, value => String.fromCharCode(value)).join(''));
      const customer = await request<CustomerSession>('/session', credentials);
      const owned = await request<CustomerOrder[]>('/orders', credentials);
      const key = 'decisionops-customer:' + customer.customer_id + ':conversation';
      let saved: CustomerConversation | null = null;
      const identity = localStorage.getItem(key);
      if (identity) {
        try { saved = await request<CustomerConversation>('/conversations/' + encodeURIComponent(identity), credentials); }
        catch (failure) {
          // Only a confirmed missing/foreign conversation permits a fresh thread.
          // A transient outage must preserve the original conversation for retry.
          if (failure instanceof CustomerRequestError && failure.status === 404) localStorage.removeItem(key);
          else throw failure;
        }
      }
      if (!saved) saved = await request<CustomerConversation>('/conversations', credentials, {});
      if (login !== currentLogin.current) return;
      localStorage.setItem(key, saved.id);
      setAuth(credentials); setSession(customer); setOrders(owned); setConversation(saved); setPassword('');
    } catch (failure) {
      if (login === currentLogin.current) setError(failure instanceof Error ? failure.message : 'Sign-in failed.');
    } finally { if (login === currentLogin.current) setBusy(false); }
  }

  useEffect(() => {
    if (!auth || !conversation || busy) return;
    let cancelled = false;
    const identity = conversation.id;
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        const next = await request<CustomerConversation>('/conversations/' + encodeURIComponent(identity), auth);
        if (!cancelled) setConversation(next);
      } catch {
        if (!cancelled) setError('Updates are temporarily unavailable. Your conversation is saved; please try again shortly.');
      } finally { refreshing = false; }
    };
    const timer = window.setInterval(() => void refresh(), 2_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [auth, conversation?.id, busy]);

  async function select(order: CustomerOrder, parcel: string | null) {
    if (!auth || !conversation || busy) return;
    const login = currentLogin.current;
    setBusy(true); setError('');
    try {
      const next = await request<CustomerConversation>('/conversations/' + conversation.id + '/select', auth,
        { order_id: order.id, shipment_id: parcel });
      if (login === currentLogin.current) setConversation(next);
    } catch (failure) { if (login === currentLogin.current) setError(failure instanceof Error ? failure.message : 'Selection failed.'); }
    finally { if (login === currentLogin.current) setBusy(false); }
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!auth || !conversation || busy || !message.trim()) return;
    const text = message.trim();
    const login = currentLogin.current;
    setBusy(true); setError('');
    try {
      await request<CustomerReply>('/conversations/' + conversation.id + '/messages', auth,
        { message: text, request_id: crypto.randomUUID() });
      if (login !== currentLogin.current) return;
      const next = await request<CustomerConversation>('/conversations/' + conversation.id, auth);
      if (login === currentLogin.current) { setMessage(''); setConversation(next); }
    } catch (failure) { if (login === currentLogin.current) setError(failure instanceof Error ? failure.message : 'Message failed.'); }
    finally { if (login === currentLogin.current) setBusy(false); }
  }

  function signOut() {
    ++currentLogin.current;
    setAuth(null); setSession(null); setConversation(null); setOrders([]); setMessage(''); setPassword(''); setError(''); setBusy(false);
  }

  const selected = orders.find(order => order.id === conversation?.selected_order_id);
  const splitPending = selected && selected.parcels.length > 1 && !conversation?.selected_shipment_id;

  return <div className="customer-portal">
    <header className="customer-header">
      <div><p className="customer-brand">Maison Paris</p><h1>Delivery help</h1></div>
      <nav aria-label="Application entry points"><a href="/customer">Customer help</a><a href="/staff">Staff workspace</a></nav>
    </header>
    <p className="customer-disclosure">Fictional store</p>
    {error && <p role="alert" className="customer-error">{error}</p>}
    {!session ? <main className="customer-login card">
      <h2>Customer sign in</h2>
      <form onSubmit={event => void signIn(event)}>
        <label>Customer username<input autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required disabled={busy} /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required disabled={busy} /></label>
        <button className="primary" disabled={busy} type="submit">{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </main> : <main>
      <div className="customer-greeting"><p>Signed in as <strong>{session.display_name}</strong></p><button onClick={signOut}>Sign out</button></div>
      <div className="customer-columns">
        <section className="card customer-orders" aria-label="Your orders">
          <h2>Your orders</h2>
          {orders.length === 0 && <p>No orders are linked to this account.</p>}
          {orders.map(order => <button key={order.id} className={selected?.id === order.id ? 'customer-order selected' : 'customer-order'}
            aria-label={'Open order ' + order.id} aria-pressed={selected?.id === order.id} disabled={busy}
            onClick={() => void select(order, order.parcels.length === 1 ? order.parcels[0].shipment_id : null)}>
            <strong>{order.id}</strong><span>{order.parcels.length} {order.parcels.length === 1 ? 'parcel' : 'parcels'}</span>
          </button>)}
        </section>
        <div className="customer-main">
          <section className="card" aria-label="Your delivery conversation" data-testid="customer-conversation" data-conversation-id={conversation?.id}>
            <h2>Shop support</h2>
            <p className="muted">{selected ? selected.id : 'Select an order to get help.'}{conversation?.selected_shipment_id && selected?.parcels.length !== 1 ? ' · ' + conversation.selected_shipment_id : ''}</p>
            {splitPending && <div className="customer-parcels" role="group" aria-label="Choose a parcel">
              <p>This order has more than one parcel. Which one do you mean?</p>
              {selected.parcels.map(parcel => <button key={parcel.shipment_id} disabled={busy}
                onClick={() => void select(selected, parcel.shipment_id)}>{parcel.shipment_id}</button>)}
            </div>}
            <div className="customer-messages" role="log" aria-label="Conversation messages" aria-live="polite">
              {conversation?.messages.map((entry, index) => <div className="customer-message-pair" key={index}>
                <p className="customer-said"><strong>You</strong><br />{entry.message}</p>
                <p className="customer-reply"><strong>Shop support</strong><br />{entry.response.text}{entry.response.case_id && <><br /><span>Case reference: {entry.response.case_id}</span></>}</p>
              </div>)}
            </div>
            {selected && !splitPending && <div className="customer-shortcuts">
              <button type="button" onClick={() => { setMessage('What is my delivery status?'); composer.current?.focus(); }} disabled={busy}>Check delivery status</button>
              <button type="button" onClick={() => { setMessage('My parcel never arrived. Please report it missing.'); composer.current?.focus(); }} disabled={busy}>Report a missing parcel</button>
            </div>}
            <form className="customer-composer" onSubmit={event => void send(event)}>
              <label>Your message<input ref={composer} value={message} onChange={event => setMessage(event.target.value)} maxLength={2000} required disabled={busy} autoComplete="off" /></label>
              <button className="primary" disabled={busy || !message.trim()} type="submit">Send message</button>
            </form>
          </section>
          <section className="card" aria-label="Your case updates" aria-live="polite">
            <h2>Your case updates</h2>
            {conversation?.cases.length === 0 && <p className="muted">No cases yet.</p>}
            {conversation?.cases.map(update => <article className="customer-case" key={update.case_id}>
              <h3>Case {update.case_id}</h3><p>{update.order_id} · {update.shipment_id}</p><p>{update.text}</p>
            </article>)}
          </section>
        </div>
      </div>
    </main>}
  </div>;
}
