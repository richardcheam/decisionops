import React, { useEffect, useRef, useState } from 'react';

export type CaseLink = { case_id: string; order_id: string; shipment_id: string };
export type DeliveryReport = {
  timezone: string; start: string; end: string; as_of: string;
  completed: number; open: number; overdue: number; exceptions: number;
  case_links: CaseLink[];
  semantics: { completed: string; open: string; overdue: string };
};
type Exception = CaseLink & {
  city: string; triggers: string[]; status: string; updated_at: string;
  promised_at: string | null; carrier_status: string; next_action: string;
};
export type ChatReply = {
  intent: string; text: string; selected_case_id: string | null;
  report?: DeliveryReport; case_links?: CaseLink[]; evidence_current?: boolean; case_generation?: number;
};
type Message = { id: string; speaker: 'You' | 'Assistant'; text: string; links?: CaseLink[] };
type Props = {
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

export function DeliveryWorkspace({ conversationId, request, selected, selectedOrder, disabled, onSelect, onMessage }: Props) {
  const [report, setReport] = useState<DeliveryReport | null>(null);
  const [queue, setQueue] = useState<Exception[]>([]);
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
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
    try { await onSelect(id); } catch (e) { setError((e as Error).message); }
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
  return <div className="delivery-workspace">
    {error && <p role="alert" className="error">{error}</p>}
    <section className="card" aria-label="Delivery overview">
      <div className="sectionhead"><h2>Delivery overview</h2><span className="badge">Paris dispatch · Metropolitan France</span></div>
      {!report ? <p role="status">Loading delivery totals…</p> : <>
        <p className="muted">Week from <time data-testid="report-start" dateTime={report.start}>{stamp(report.start)}</time> until <time data-testid="report-end" dateTime={report.end}>{stamp(report.end)}</time> (end excluded) · {report.timezone}</p>
        <dl className="delivery-metrics">
          <div><dt>Completed this week</dt><dd>{report.completed}</dd></div>
          <div><dt>Open parcels</dt><dd>{report.open}</dd></div>
          <div><dt>Overdue parcels</dt><dd>{report.overdue}</dd></div>
          <div><dt>Operational exceptions</dt><dd>{report.exceptions}</dd></div>
        </dl>
        <p className="muted">Completed: {report.semantics.completed}. Open: {report.semantics.open}. Overdue: {report.semantics.overdue}.</p>
        <p className="muted">Data as of <time data-testid="report-freshness" dateTime={report.as_of}>{stamp(report.as_of)}</time> · Europe/Paris. In-app case updates refresh automatically.</p>
        <details><summary>Cases in this report</summary><div className="case-links">{report.case_links.map(link => <button key={link.case_id} disabled={disabled} onClick={() => void choose(link.case_id)}>Open {link.order_id} · {link.shipment_id}</button>)}</div></details>
      </>}
    </section>
    <section className="card" aria-label="Exception queue">
      <div className="sectionhead"><h2>Exception queue</h2><span className="count">{queue.length}</span></div>
      <p className="muted">An overdue parcel or a customer report needs investigation. Neither confirms loss. Delivered parcels with nonreceipt remain here.</p>
      {!queue.length ? <p className="muted">No operational exceptions to show.</p> : <div className="queue-scroll"><table className="exception-table">
        <thead><tr><th scope="col">Order / parcel</th><th scope="col">Trigger / carrier</th><th scope="col">Timing</th><th scope="col">Case / next action</th></tr></thead>
        <tbody>{queue.map(row => <tr key={row.case_id} aria-selected={row.case_id === selected}>
          <td><button disabled={disabled} aria-pressed={row.case_id === selected} onClick={() => void choose(row.case_id)}>{row.order_id}<small>{row.shipment_id} · {row.city}</small></button></td>
          <td>{row.triggers.map(plain).join(', ')}<small>Carrier: {plain(row.carrier_status)}</small></td>
          <td>{row.promised_at ? <>Promised <time dateTime={row.promised_at}>{stamp(row.promised_at)}</time></> : 'Promise unknown'}<small>Updated <time dateTime={row.updated_at}>{stamp(row.updated_at)}</time></small></td>
          <td><small>{row.case_id}</small>{plain(row.status)}<small>{plain(row.next_action)}</small></td>
        </tr>)}</tbody>
      </table></div>}
    </section>
    <section className="card" aria-label="Workspace chat">
      <h2>Delivery assistant</h2>
      <p className="muted">Ask about deliveries, open an exception, then ask “Fix this” to delegate its investigation. “What’s still missing?” reads the saved progress.</p>
      <p data-testid="selected-case" className="selection-summary">{selected ? `Selected case: ${selectedOrder ? selectedOrder + ' · ' : ''}${selected}` : 'No case selected. Open a queue or report link to select one.'}</p>
      <div role="log" aria-label="Conversation" aria-live="polite" className="conversation">
        {messages.map(row => <div key={row.id} className={'chat-message ' + (row.speaker === 'You' ? 'from-staff' : '')}><strong>{row.speaker}</strong><p>{row.text}</p>{!!row.links?.length && <div className="case-links">{row.links.map(link => <button key={link.case_id} disabled={disabled} onClick={() => void choose(link.case_id)}>Open {link.order_id} · {link.shipment_id}</button>)}</div>}</div>)}
      </div>
      <form onSubmit={event => void send(event)}>
        <label htmlFor="workspace-message">Message</label>
        <textarea id="workspace-message" value={draft} onChange={event => setDraft(event.target.value)} maxLength={1000} rows={2} required disabled={disabled || sending} placeholder="How many deliveries did we complete this week?" />
        <button className="primary" disabled={disabled || sending || !draft.trim()}>Send message</button>
        {sending && <span className="muted" role="status"> Reading saved store information…</span>}
      </form>
    </section>
  </div>;
}
