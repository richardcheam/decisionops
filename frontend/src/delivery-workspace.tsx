import React, { useEffect, useRef, useState } from 'react';

export type CaseLink = { case_id: string; order_id: string; shipment_id: string };
export type DeliveryReport = {
  timezone: string; start: string; end: string; as_of: string;
  completed: number; open: number; overdue: number; exceptions: number;
  case_links: CaseLink[];
  semantics: { completed: string; open: string; overdue: string };
};
type Exception = CaseLink & {
  city: string; triggers: string[]; carrier_status: string;
};
export type ChatReply = {
  intent: string; text: string; selected_case_id: string | null;
  report?: DeliveryReport; case_links?: CaseLink[]; evidence_current?: boolean; case_generation?: number;
};
type Message = { id: string; speaker: 'You' | 'Assistant'; text: string; links?: CaseLink[] };
type Props = {
  children: React.ReactNode;
  conversationId: string;
  request: <T>(path: string, body?: unknown) => Promise<T>;
  selected: string;
  selectedOrder?: string;
  disabled: boolean;
  onSelect: (id: string) => Promise<void>;
  onMessage: (message: string, requestId: string) => Promise<ChatReply>;
};
const stamp = (value: string) => new Date(value).toLocaleString('en-GB', { timeZone: 'Europe/Paris', dateStyle: 'medium', timeStyle: 'short' });
const plain = (value: string) => value.replaceAll('_', ' ');

export function DeliveryWorkspace({ conversationId, request, selected, selectedOrder, disabled, onSelect, onMessage, children }: Props) {
  const [report, setReport] = useState<DeliveryReport | null>(null);
  const [queue, setQueue] = useState<Exception[]>([]);
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const log = transcript.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages.length]);
  const messageFlight = useRef(false);
  const latestRequest = useRef(request);
  latestRequest.current = request;
  useEffect(() => {
    let disposed = false;
    async function load() {
      try {
        const [summary, exceptions] = await Promise.all([
          latestRequest.current<DeliveryReport>('/api/deliveries'),
          latestRequest.current<Exception[]>('/api/exceptions'),
        ]);
        if (!disposed) { setReport(summary); setQueue(exceptions); setError(''); }
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [conversationId]);
  async function choose(id: string) {
    setError('');
    try {
      await onSelect(id);
      if (window.matchMedia('(max-width: 760px)').matches) {
        document.getElementById('staff-case')?.focus();
      }
    } catch (e) { setError((e as Error).message); }
  }
  async function send(event: React.FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || disabled || messageFlight.current) return;
    messageFlight.current = true;
    setSending(true);
    setError('');
    const id = crypto.randomUUID();
    setMessages(rows => [...rows, { id, speaker: 'You', text: message }]);
    setDraft('');
    try {
      const reply = await onMessage(message, id);
      setMessages(rows => [...rows, { id: id + '-reply', speaker: 'Assistant', text: reply.text, links: reply.case_links || reply.report?.case_links }]);
      if (reply.report) setReport(reply.report);
    } catch (e) {
      setError((e as Error).message);
      setDraft(message);
    } finally { messageFlight.current = false; setSending(false); }
  }
  const parcelsPerOrder = new Map<string, number>();
  for (const row of queue) parcelsPerOrder.set(row.order_id, (parcelsPerOrder.get(row.order_id) ?? 0) + 1);

  return <>
    {error && <p role="alert" className="error workspace-error">{error}</p>}
    <section className="delivery-overview" aria-label="Delivery overview">
      {!report ? <p role="status">Loading delivery totals…</p> : <>
        <dl className="delivery-metrics">
          <div><dt>Delivered this week</dt><dd>{report.completed}</dd></div>
          <div><dt>Open parcels</dt><dd>{report.open}</dd></div>
          <div><dt>Overdue parcels</dt><dd>{report.overdue}</dd></div>
          <div><dt>Exceptions</dt><dd>{report.exceptions}</dd></div>
        </dl>
        <div className="report-period"><span>Paris time · <time data-testid="report-start" dateTime={report.start}>{stamp(report.start)}</time>–<time data-testid="report-end" dateTime={report.end}>{stamp(report.end)}</time></span><span>Updated <time data-testid="report-freshness" dateTime={report.as_of}>{stamp(report.as_of)}</time></span></div>
        <details className="report-details">
          <summary>Report details</summary>
          <p className="muted">Times use {report.timezone}. The end time is exclusive.</p>
          <ul className="report-definitions">
            <li>{report.semantics.completed}</li>
            <li>{report.semantics.open}</li>
            <li>{report.semantics.overdue}</li>
          </ul>
          <div className="case-links">{report.case_links.map(link => <button key={link.case_id} disabled={disabled} onClick={() => void choose(link.case_id)}>Open {link.order_id} · {link.shipment_id}</button>)}</div>
        </details>
      </>}
    </section>
    <section className="card delivery-queue" aria-label="Exception queue">
      <div className="sectionhead"><h2>Exception queue</h2><span className="count">{queue.length}</span></div>
      {!queue.length ? <p className="muted">No exceptions.</p> : <ul className="queue-list">
        {queue.map(row => <li key={row.case_id}>
          <button type="button" disabled={disabled} aria-pressed={row.case_id === selected} onClick={() => void choose(row.case_id)}>
            <strong>{row.order_id}</strong>
            {(parcelsPerOrder.get(row.order_id) ?? 0) > 1 && <small>{row.shipment_id}</small>}
            <span>{row.city} · {plain(row.carrier_status)}</span>
            <small>{row.triggers.map(plain).join(' · ')}</small>
          </button>
        </li>)}
      </ul>}
    </section>
    {children}
    <section className="card delivery-chat" aria-label="Workspace chat">
      <h2>Assistant</h2>
      <p data-testid="selected-case" className="selection-summary">{selected ? <><strong>{selectedOrder || 'Selected case'}</strong><small>{selected}</small></> : 'No case selected'}</p>
      <div ref={transcript} role="log" aria-label="Conversation" aria-live="polite" className="conversation">
        {messages.map(row => <div key={row.id} className={'chat-message ' + (row.speaker === 'You' ? 'from-staff' : '')}><strong>{row.speaker}</strong><p>{row.text}</p>{!!row.links?.length && <div className="case-links">{row.links.map(link => <button key={link.case_id} disabled={disabled} onClick={() => void choose(link.case_id)}>Open {link.order_id} · {link.shipment_id}</button>)}</div>}</div>)}
      </div>
      <form onSubmit={event => void send(event)}>
        <label htmlFor="workspace-message">Message</label>
        <textarea id="workspace-message" value={draft} onChange={event => setDraft(event.target.value)} maxLength={1000} rows={2} required disabled={disabled || sending} placeholder={selected ? 'What’s still missing?' : 'How many parcels arrived this week?'} />
        <button className="primary" disabled={disabled || sending || !draft.trim()}>Send message</button>
        {sending && <span className="muted" role="status"> Checking…</span>}
      </form>
    </section>
  </>;
}
