import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { Shop } from "./shop";
import { CustomerPortal } from "./customer";
import { DeliveryWorkspace, type ChatReply } from "./delivery-workspace";

type Order = {
  id: string;
  lines: { variant_id: string; quantity: number }[];
  shipments: { id: string }[];
};
type Evidence = {
  requirement: string;
  value: boolean | null;
  source_id: string;
  source_version: string;
  observed_at: string;
  details: Record<string, unknown>;
};
type Assessment = {
  facts: Record<string, boolean | null>;
  decision: { status: string; blockers: string[]; unknowns: string[] };
  read_tools: Evidence[];
  scope_reasons?: string[];
};
type Case = {
  id: string;
  status: string;
  generation: number;
  request: {
    order_id: string;
    shipment_id: string;
    items: Record<string, number>;
  };
  updated_at: string;
  delivery?: {
    city: string; promised_at: string | null; dispatch_origin: string;
    carrier_events: {id: string; source: string; external_id: string; event_at: string; received_at: string; status: string; verified: boolean; original: Record<string, unknown>}[];
  } | null;
  assessment?: Assessment;
  proposal?: {
    id: string;
    content_hash: string;
    document: { policy_id: string; request: { items: Record<string, number> } };
  } | null;
  approval?: { operation_id: string; actor: string } | null;
  events?: {
    id: string;
    kind: string;
    created_at: string;
    details: Record<string, unknown>;
  }[];
  latest_job?: {
    id: string;
    status: string;
    action: string;
    error_kind: string | null;
  } | null;
  shipment_investigation?: {
    id: string; generation?: number; historical?: boolean; state: string; report: string; mode: string; reason: string | null;
    unknowns: string[]; blockers: string[]; evidence_current?: boolean; planned_checks?: string[];
    evidence: {tool: string; value: boolean | null; applicability: string; status: string; reason: string | null; observed_at: string; expires_at?: string; customer_page?: string; source?: {kind:string;observation_id:string;version:string;order_id:string;shipment_id:string;tables:string[]}}[];
    steps: {sequence: number; kind: string; data: {specialist?: string; tool?: string; status?: string; chosen_action?: {tool?: string; kind?: string}; reason?: string}; created_at: string}[];
    specialists?: {name: string; state: string; tools: string[]; reason?: string | null; observations: string[]}[];
  } | null;
  operation?: {
    status: string;
    replacement_id: string;
    operation_id: string;
    meaning: string;
  } | null;
};
const labels: Record<string, string> = {
  open: "Ready to check",
  awaiting_review: "Ready for your review",
  needs_review: "Needs more information",
  blocked: "Replacement unavailable",
  approved: "Replacement approved",
  rejected: "Replacement declined",
  escalated: "Needs manager review",
  executed: "Replacement created",
};
const requirements: Record<string, string> = {
  paid: "Payment confirmed",
  shipped: "Full order shipped",
  loss_confirmed: "Carrier confirms loss",
  quantities_valid: "Items and quantities match",
  no_previous_compensation: "Not already refunded or replaced",
  stock_available: "Replacement stock available",
  policy_permits: "Store policy permits replacement",
};
const toolLabels: Record<string,string> = {order_manifest:"Order items", replacement_policy:"Store replacement policy", payment:"Payment", fulfilment:"Shipment", carrier_loss:"Carrier loss confirmation", compensation_history:"Refund and replacement history", inventory:"Available stock"};
const events: Record<string, string> = {
  opened: "Case opened",
  customer_report_received: "Customer reported a missing parcel",
  adaptive_started: "Shipment investigation started",
  staff_investigation_requested: "Shipment report received",
  adaptive_proposed: "Evidence checked — proposal prepared",
  adaptive_finished: "Shipment investigation finished",
  investigated: "Order checked",
  reviewed: "Review decision saved",
  approval_invalidated: "Information changed — approval needed again",
  proposal_stale: "Information changed — check again",
  executed: "Replacement created and items set aside",
  escalated: "Marked for manager review",
};
// Display labels for the two fictional variants; requests still use exact IDs.
const productNames: Record<string, string> = {
  "shirt-blue-M": "Blue shirt · Size M",
  "shirt-red-M": "Red shirt · Size M",
};
const missingInformation: Record<string, string> = {
  paid: "We need confirmation that this order was paid.",
  shipped: "We need confirmation that all these items were shipped.",
  loss_confirmed: "We need an up-to-date confirmation from the carrier that the parcel is lost.",
  quantities_valid: "We need to confirm these items and quantities match the order.",
  no_previous_compensation: "We need the full refund and replacement history before continuing.",
  stock_available: "We need current stock information before promising a replacement.",
  policy_permits: "We need to confirm which store rule applies to this order.",
};
const failedChecks: Record<string, string> = {
  paid: "Payment is not confirmed for this order.",
  shipped: "These items have not all been shipped.",
  loss_confirmed: "The carrier reports a status other than lost. Ask your manager to review the delivery issue.",
  quantities_valid: "These items or quantities do not match the original order.",
  no_previous_compensation: "These items have already been refunded or replaced.",
  stock_available: "There are not enough items available for this replacement.",
  policy_permits: "The store's rule does not allow replacement for this order.",
};
function nextStep(value: Case) {
  if (value.operation && value.operation.status !== "verified")
    return "We could not confirm the replacement. Ask your manager to check this case before trying again.";
  if (value.assessment?.scope_reasons?.length)
    return "This order needs a manager's review. It may include split shipments, only some items, or a previous partial refund or replacement.";
  const guidance: Record<string, string> = {
    open: value.delivery ? "Investigate the parcel to see if it can be replaced." : "Check the order to see if it can be replaced.",
    awaiting_review: "The checks passed. Review the replacement and approve or decline it.",
    needs_review: "Some information is missing or has changed. Check again or ask your manager for help before promising a replacement.",
    blocked: "A replacement is not available for this request. See the reasons below or ask your manager for help.",
    approved: "Approved. Choose Create replacement to set these items aside. They will not be shipped yet.",
    rejected: "The replacement was declined. You can check again or ask for help.",
    escalated: "This case is marked for help. Share it with your manager; no replacement has been created.",
    executed: "This replacement has been created. It has not been shipped yet.",
  };
  return guidance[value.status] || "Ask your manager to review this case.";
}
function time(value: string) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Paris",
  });
}
function items(value: Record<string, number>) {
  return Object.entries(value)
    .map(([variant, qty]) => `${productNames[variant] || variant} × ${qty}`)
    .join(", ");
}

type Confirmation = {
  action: "approve" | "execute";
  caseId: string;
  generation: number;
  proposalId: string;
  hash: string;
  items: Record<string, number>;
  operationId?: string;
};

function App() {
  const [auth, setAuth] = useState("");
  const [role, setRole] = useState<"staff" | "approver">("staff");
  const [conversationId, setConversationId] = useState("");
  const [staleEvidence, setStaleEvidence] = useState<{caseId:string;generation:number} | null>(null);
  const selectionFlight = useRef(false);
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [orderId, setOrderId] = useState("");
  const [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("case") || "");
  const [report, setReport] = useState("");
  const investigationFlight = useRef(false);
  useEffect(() => { window.history.replaceState(null, "", selected ? "#case=" + encodeURIComponent(selected) : window.location.pathname + window.location.search); }, [selected]);
  const [active, setActive] = useState<Case | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState<Confirmation | null>(null);
  async function request<T>(
    path: string,
    body?: unknown,
    authorization = auth,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        credentials: "omit",
        cache: "no-store",
        headers: {
          Authorization: authorization,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new Error(
        "We cannot reach the store right now. Try again in a moment. If it continues, ask your manager for help.",
      );
    }
    if (!response.headers.get("Content-Type")?.includes("application/json"))
      throw new Error("The store is temporarily unavailable. Try again in a moment. If it continues, ask your manager for help.");
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        response.status === 401
          ? "Your sign-in details were not accepted. Sign in again or ask your manager for help."
          : response.status === 409
            ? "This case has changed or the action is no longer available. Refresh the case and review the latest information before continuing."
            : response.status === 503
              ? "The store is temporarily unavailable. Try again in a moment. If it continues, ask your manager for help."
              : response.status === 422
                ? "Check the order and quantities, then try again."
                : response.status === 404
                  ? "We could not find that order or case. Refresh the page and try again."
                  : "We could not complete this request. Try again or ask your manager for help.",
      );
    return data as T;
  }
  async function refresh(id = selected) {
    const list = await request<Case[]>("/api/cases");
    setCases(list);
    if (id)
      setActive(await request<Case>("/api/cases/" + encodeURIComponent(id)));
  }
  useEffect(() => {
    if (!auth) return;
    let disposed = false;
    const poll = async () => {
      try {
        const list = await request<Case[]>("/api/cases");
        const detail = selected
          ? await request<Case>("/api/cases/" + encodeURIComponent(selected))
          : null;
        if (!disposed) {
          setCases(list);
          if (detail) setActive(detail);
        }
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [auth, selected]);
  async function login(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const authorization = "Basic " + btoa(username + ":" + password);
      const session = await request<{role?: "staff" | "approver"}>("/api/session", undefined, authorization);
      const conversation = await request<{id: string}>("/api/conversations", {}, authorization);
      if (selected) await request("/api/conversations/" + conversation.id + "/select", {case_id: selected}, authorization);
      setRole(session.role || "approver");
      setConversationId(conversation.id);
      const loaded = await request<Order[]>(
        "/api/orders",
        undefined,
        authorization,
      );
      setOrders(loaded);
      setOrderId(loaded[0]?.id || "");
      setPassword("");
      setAuth(authorization);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPassword("");
      setBusy(false);
    }
  }
  async function perform(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openCase(event: React.FormEvent) {
    event.preventDefault();
    const order = orders.find((row) => row.id === orderId);
    if (!order) return;
    setBusy(true);
    setError("");
    try {
      const result = await request<Case>("/api/cases", {
        order_id: order.id,
        shipment_id: order.shipments[0]?.id || "",
        items: Object.fromEntries(
          order.lines.map((line) => [line.variant_id, line.quantity]),
        ),
      });
      await request("/api/conversations/" + conversationId + "/select", {case_id: result.id});
      setStaleEvidence(null);
      setSelected(result.id);
      setActive(result);
      await request("/api/cases/" + result.id + "/investigate", {});
      await refresh(result.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function selectCase(id: string) {
    if (selectionFlight.current || busy || confirm) return;
    selectionFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const binding = await request<{selected_case_id: string}>("/api/conversations/" + conversationId + "/select", {case_id: id});
      setStaleEvidence(null);
      setSelected(binding.selected_case_id);
      setActive(null);
      setReport("");
      await refresh(binding.selected_case_id);
    } finally { selectionFlight.current = false; setBusy(false); }
  }
  async function sendMessage(message: string, requestId: string): Promise<ChatReply> {
    setBusy(true);
    setError("");
    try {
      const reply = await request<ChatReply>("/api/conversations/" + conversationId + "/messages", {message, request_id: requestId});
      const id = reply.selected_case_id || "";
      if (id !== selected) { setSelected(id); setActive(null); setReport(""); setStaleEvidence(null); }
      if (reply.evidence_current !== undefined) setStaleEvidence(reply.evidence_current === false && typeof reply.case_generation === 'number' ? {caseId:id,generation:reply.case_generation} : null);
      if (id) await refresh(id);
      return reply;
    } finally { setBusy(false); }
  }
  async function investigateShipment(event: React.FormEvent) {
    event.preventDefault();
    if (!active || investigationFlight.current) return;
    investigationFlight.current = true;
    const snapshot = active;
    try {
      await perform(async () => {
        await request("/api/cases/" + snapshot.id + "/shipment-investigation", {
          report, request_id: crypto.randomUUID(), expected_generation: snapshot.generation,
        });
        setStaleEvidence(null);
      });
    } finally { investigationFlight.current = false; }
  }
  const pending =
    active?.latest_job &&
    ["queued", "running"].includes(active.latest_job.status);
  const locked = busy || Boolean(pending);
  const replacementVerified = active?.operation?.status === "verified";
  const canStartDeliveryInvestigation = Boolean(active?.delivery && active.status === "open");
  const historicalInvestigation = active?.shipment_investigation?.historical === true;
  const evidenceNeedsRefresh = Boolean(staleEvidence && staleEvidence.caseId === active?.id && staleEvidence.generation === active?.generation) || (!historicalInvestigation && active?.shipment_investigation?.evidence_current === false);
  function confirmation(action: "approve" | "execute") {
    if (!active?.proposal) return;
    setConfirm({
      action,
      caseId: active.id,
      generation: active.generation,
      proposalId: active.proposal.id,
      hash: active.proposal.content_hash,
      items: { ...active.request.items },
      operationId: active.approval?.operation_id,
    });
  }
  async function review(
    decision: "approve" | "reject",
    snapshot?: Confirmation,
  ) {
    if (!active?.proposal && !snapshot) return;
    const current = snapshot || {
      caseId: active!.id,
      generation: active!.generation,
      proposalId: active!.proposal!.id,
      hash: active!.proposal!.content_hash,
    };
    await perform(() =>
      request("/api/cases/" + current.caseId + "/review", {
        generation: current.generation,
        proposal_id: current.proposalId,
        content_hash: current.hash,
        decision,
      }),
    );
    setConfirm(null);
  }
  async function execute(snapshot: Confirmation) {
    if (!snapshot.operationId) return;
    await perform(() =>
      request("/api/cases/" + snapshot.caseId + "/execute", {
        operation_id: snapshot.operationId,
      }),
    );
    setConfirm(null);
  }
  if (!auth)
    return (
      <main className="login">
        <p className="eyebrow">DecisionOps</p>
        <h1>Staff sign in</h1>
        <form onSubmit={login} className="loginform">
          <label>
            Username
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <nav aria-label="Application entry points"><a href="/customer">Customer help</a> · <a href="/staff">Staff workspace</a></nav>
        <p className="footnote">Fictional store</p>
      </main>
    );
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <strong>DecisionOps</strong>
        </div>
        <div className="header-right">
          <a href="/customer">Customer help</a>
          <span className="badge">Demo store · {role === "approver" ? "Approver" : "Staff"}</span>
          <button
            className="quiet"
            onClick={() => {
              setAuth("");
              setConversationId("");
              setRole("staff");
              setActive(null);
              setSelected("");
              setCases([]);
              setError("");
              setConfirm(null);
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="workspace delivery-dashboard">
        <div className="pageintro"><h1>Deliveries</h1></div>
        {error && (
          <div role="alert" className="error workspace-error">
            {error}
            <button
              className="quiet"
              onClick={() =>
                void perform(async () => {
                  await refresh();
                })
              }
            >
              Refresh case
            </button>
          </div>
        )}
        <DeliveryWorkspace key={conversationId} conversationId={conversationId} request={request} selected={selected} selectedOrder={active?.request.order_id} disabled={busy || Boolean(confirm)} onSelect={selectCase} onMessage={sendMessage}>
          <section className="casepanel" id="staff-case" tabIndex={-1} aria-label="Selected case">
            {!selected ? (
              <div className="empty card">
                <h2>Select a case</h2>
                <p className="muted">Open an exception to see the parcel and its next step.</p>
              </div>
            ) : !active ? (
              <div className="card">Loading case…</div>
            ) : (
              <>
                <section className="card caseheader">
                  <div>
                    <h2>{active.request.order_id}</h2>
                    <p>{active.delivery ? `${active.delivery.dispatch_origin} → ${active.delivery.city}` : active.request.shipment_id}</p>
                    <p className="muted">{items(active.request.items)}</p>
                  </div>
                  <span className={"status " + active.status}>
                    {active.operation && active.operation.status !== "verified"
                      ? "Needs confirmation"
                      : labels[active.status] || "Needs review"}
                  </span>
                </section>
                <section className="card next-step" aria-label="Next step">
                  <h2>Next step</h2>
                  <p>{replacementVerified ? nextStep(active) : pending ? "We are checking the order. You can leave this page and return later." : evidenceNeedsRefresh ? "Saved evidence needs an explicit investigation refresh before approval or execution." : nextStep(active)}</p>
                  <div className="actions">
                  {canStartDeliveryInvestigation && (
                    <button className="primary" disabled={locked}
                      onClick={() => void sendMessage("Fix this", crypto.randomUUID()).catch(e => setError((e as Error).message))}>
                      Investigate case
                    </button>
                  )}
                  {!canStartDeliveryInvestigation && active.status !== "executed" && <button
                    className={active.proposal && !evidenceNeedsRefresh ? "quiet" : "primary"}
                    disabled={locked}
                    onClick={() =>
                      void perform(() =>
                        request("/api/cases/" + active.id + "/investigate", {}),
                      )
                    }
                  >
                    {pending
                      ? "Checking…"
                      : active.generation
                        ? "Check again"
                        : "Check order"}
                  </button>}
                  {role === "approver" && active.status === "awaiting_review" && (
                    <>
                      <button
                        className="primary"
                        disabled={locked || evidenceNeedsRefresh}
                        onClick={() => confirmation("approve")}
                      >
                        Approve replacement
                      </button>
                      <button
                        className="quiet"
                        disabled={locked}
                        onClick={() => void review("reject")}
                      >
                        Decline replacement
                      </button>
                    </>
                  )}
                  {role === "approver" && active.status === "approved" && (
                    <button
                      className="primary"
                      disabled={locked || evidenceNeedsRefresh}
                      onClick={() => confirmation("execute")}
                    >
                      Create replacement
                    </button>
                  )}
                  {pending && (
                    <span className="muted" role="status">
                      {active.latest_job?.status === "queued"
                        ? "Your order check will start shortly"
                        : "Checking order information"}
                    </span>
                  )}
                  </div>
                  {role === "staff" && ["awaiting_review", "approved"].includes(active.status) && <p className="muted">An approver must review the exact proposal and separately confirm execution.</p>}
                </section>
                {active.latest_job?.status === "failed" && (
                  <div role="alert" className="error">
                    We could not finish checking this order. Try checking again.
                    If it continues, ask your manager for help.
                  </div>
                )}
                {active.operation && (
                  <section
                    className={
                      "card outcome " +
                      (active.operation.status === "verified" ? "success" : "")
                    }
                  >
                    <p className="eyebrow">Result</p>
                    <h2>
                      {active.operation.status === "verified"
                        ? "Replacement confirmed"
                        : "Replacement needs confirmation"}
                    </h2>
                    <p>
                      {active.operation.status === "verified"
                        ? "The replacement is created and the items are set aside. They have not been shipped yet."
                        : "We could not confirm the result. Ask your manager to check this case before creating another replacement."}
                    </p>
                  </section>
                )}
                {active.delivery && <details className="card" aria-label="Carrier timeline">
                  <summary>Carrier updates</summary>
                  <p>{active.delivery.dispatch_origin} → {active.delivery.city}. {active.delivery.promised_at ? "Promised " + time(active.delivery.promised_at) : "Delivery promise unknown"}.</p>
                  {active.delivery.carrier_events.some(event => event.verified && event.status === "lost") && active.delivery.carrier_events.some(event => event.verified && event.status === "delivered") && <p className="error">Conflicting verified loss and delivery records require review.</p>}
                  <ol className="timeline">{active.delivery.carrier_events.map(event => <li key={event.id}>
                    <strong>{event.status.replaceAll("_", " ")} · {event.verified ? "Verified record" : "Unverified record"}</strong>
                    <p>Event <time dateTime={event.event_at}>{time(event.event_at)}</time> · Received <time dateTime={event.received_at}>{time(event.received_at)}</time></p>
                    <p>Source: {event.source} · Event ID: {event.external_id} · Record: {event.id}</p>
                    <details><summary>Original simulated carrier event</summary><pre>{JSON.stringify(event.original, null, 2)}</pre></details>
                  </li>)}</ol>
                </details>}
                <section className="card" aria-label="Shipment investigation">
                  <h2>Investigation</h2>
                  {active.status !== "executed" && <details open={!active.delivery} className="manual-report">
                    <summary>Add a shipment report</summary>
                  <form onSubmit={event => void investigateShipment(event)}>
                    <label htmlFor="shipment-report">Shipment report</label>
                    <textarea id="shipment-report" rows={3} maxLength={1000} value={report} onChange={e => setReport(e.target.value)} placeholder="For example: the customer says their parcel has not arrived." disabled={locked} required />
                    {new TextEncoder().encode(report).length > 2000 && <p>Please shorten the report before submitting.</p>}
                    <button type="submit" className="primary" disabled={locked || !report.trim() || new TextEncoder().encode(report).length > 2000 || active.status === "executed"}>Investigate shipment</button>
                  </form>
                  </details>}
                  {active.shipment_investigation && <div aria-live="polite">
                    {evidenceNeedsRefresh && !replacementVerified && <p role="status" className="error">Saved evidence expired or source records changed. Start an explicit investigation refresh before relying on these findings.</p>}
                    <p role="status">{replacementVerified ? "Historical investigation. The replacement is verified by its execution record." : historicalInvestigation ? "Historical investigation from an earlier case generation. Current order checks and the proposal below govern this case." : evidenceNeedsRefresh ? "Saved investigation requires an evidence refresh." : active.shipment_investigation.state === "active" ? "Investigation in progress. You can refresh or return later." : active.shipment_investigation.state === "proposed" ? "Investigation complete. Replacement proposal ready for your review." : "Investigation finished. " + (active.shipment_investigation.blockers.length ? "A required condition was not met." : "More information or staff review is needed.")}</p>
                    {Boolean(active.shipment_investigation.specialists?.length) && <section aria-label="Specialist branches">
                      <h3>Specialist branches</h3>
                      {active.shipment_investigation.specialists?.map(branch => <div key={branch.name}>
                        <h4>{branch.name.replaceAll("_", " ")} specialist</h4>
                        <p>Branch status: {branch.state.replaceAll("_", " ")}</p>
                        <p>Assigned reads: {branch.tools.map(tool => toolLabels[tool] || tool).join(", ")}</p>
                        {branch.reason && <p>Branch outcome: {branch.reason.replaceAll("_", " ")}</p>}
                        <p>{branch.observations.length} saved observations</p>
                      </div>)}
                      <details><summary>Specialist decisions and read results</summary>
                        <ol className="timeline">{active.shipment_investigation.steps.filter(step => step.kind === "specialist_decision" || (step.kind === "specialist_read_result" && step.data.specialist)).map(step => <li key={step.sequence}>
                          <strong>{(step.data.specialist || "Specialist").replaceAll("_", " ")}</strong>: {step.kind === "specialist_decision" ? "Decision choice" : "Read result"}
                          {step.data.chosen_action?.kind && <span> · {step.data.chosen_action.kind.replaceAll("_", " ")}</span>}
                          {(step.data.tool || step.data.chosen_action?.tool) && <span> · {toolLabels[step.data.tool || step.data.chosen_action?.tool || ""] || step.data.tool || step.data.chosen_action?.tool}</span>}
                          {step.data.status && <span> · {step.data.status.replaceAll("_", " ")}</span>}
                          {step.data.reason && <p>{step.data.reason.replaceAll("_", " ")}</p>}
                          <time>{time(step.created_at)}</time>
                        </li>)}</ol>
                      </details>
                    </section>}
                    {!historicalInvestigation && active.shipment_investigation.evidence.some(row => ["expired", "dependency_changed", "future_timestamp", "conflicting_active_contents"].includes(row.applicability)) && <p role="status" className="error">Saved findings include expired, changed or conflicting evidence. Refresh the investigation before treating these findings as current.</p>}
                    {active.shipment_investigation.planned_checks?.length ? <p>Investigation outline: {active.shipment_investigation.planned_checks.join(" → ")}</p> : null}
                    <p>Saved report: {active.shipment_investigation.report}</p>
                    <p>{active.shipment_investigation.unknowns.length} checks still unknown</p>
                    <ol className="timeline">{active.shipment_investigation.evidence.map((row,i) => <li key={i}><strong>{toolLabels[row.tool] || row.tool}</strong>: {evidenceNeedsRefresh ? "Not current: refresh required" : row.applicability !== "current" ? "Not current: " + row.applicability.replaceAll("_", " ") : row.value === true ? "Confirmed" : row.value === false ? "Not met" : "Needs information"}<time>Checked {time(row.observed_at)}{row.expires_at ? " · Valid until " + time(row.expires_at) : ""}</time>{row.source && <details><summary>Evidence source</summary><p>Declared record scope: {row.source.tables.join(", ")}. Order {row.source.order_id}; shipment {row.source.shipment_id}.</p><p>This investigation consulted database records, not browser pages.</p><p>Observation: {row.source.observation_id}<br/>Version: {row.source.version}</p>{row.reason && <p>Evidence limitation: {row.reason.replaceAll("_", " ")}</p>}{row.customer_page && <a href={row.customer_page}>View corresponding customer page ↗</a>}</details>}</li>)}</ol>
                    {active.shipment_investigation.steps.some(s => s.kind === "deterministic_continuation") && <details><summary>Why evidence gathering continued</summary>{active.shipment_investigation.steps.filter(s => s.kind === "deterministic_continuation").map(s => <p key={s.sequence}>Evidence continuation: the application selected {toolLabels[s.data.chosen_action?.tool || ""] || "the next read"} after a missing-information review choice. This was not a model choice.</p>)}</details>}
                    {active.shipment_investigation.steps.filter(s => s.kind === "continuation_unavailable").map(s => <p key={s.sequence}>Could not continue gathering evidence: {s.data.reason?.replaceAll("_", " ")}.</p>)}
                    {active.shipment_investigation.reason && <p>Review outcome: {active.shipment_investigation.reason.replaceAll("_", " ")}</p>}
                  </div>}
                </section>
                {active.assessment && !replacementVerified && (
                  <section className="card">
                    <div className="sectionhead">
                      <h2>Order checks</h2>
                      <span className="muted">
                        {evidenceNeedsRefresh ? Object.keys(requirements).length : active.assessment.decision.unknowns.length} not
                        confirmed
                      </span>
                    </div>
                    <div className="requirements">
                      {Object.entries(requirements).map(([key, label]) => {
                        const value = evidenceNeedsRefresh ? null : active.assessment!.facts[key];
                        const evidence = active.assessment!.read_tools.find(
                          (row) => row.requirement === key,
                        );
                        return (
                          <div className="requirement" key={key}>
                            <span
                              className={
                                "fact-icon " +
                                (value === true
                                  ? "true"
                                  : value === false
                                    ? "false"
                                    : "unknown")
                              }
                            >
                              {value === true
                                ? "✓"
                                : value === false
                                  ? "×"
                                  : "?"}
                            </span>
                            <div>
                              <strong>{label}</strong>
                              <span>
                                {value === true
                                  ? "Confirmed"
                                  : value === false
                                    ? "Not met"
                                    : "Needs information"}
                              </span>
                              {value !== true && <p>{value === false ? failedChecks[key] : missingInformation[key]}</p>}
                              {evidence && <small>Last checked {time(evidence.observed_at)}</small>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                )}
                {active.proposal && (
                  <section className="card proposal">
                    <p className="eyebrow">Suggested replacement</p>
                    <h2>
                      Replace{" "}
                      {Object.values(active.request.items).reduce(
                        (sum, quantity) => sum + quantity,
                        0,
                      )}{" "}
                      item(s)
                    </h2>
                    <p>{items(active.proposal.document.request.items)}</p>
                    <p className="muted compact">
                      We will check the order and stock again before creating
                      this replacement. If anything changes, you will need to
                      review it again.
                    </p>
                  </section>
                )}
                <section className="card">
                  <h2>Case history</h2>
                  <details className="case-reference"><summary>Case reference</summary><p>{active.id}</p></details>
                  <ol className="timeline">
                    {active.events?.map((event) => (
                      <li key={event.id}>
                        <div>
                          <strong>{events[event.kind] || event.kind}</strong>
                          {event.kind === "customer_report_received" && typeof event.details.message === "string" && <p>{event.details.message}</p>}
                          <time>{time(event.created_at)}</time>
                        </div>
                      </li>
                    ))}
                  </ol>
                </section>
                {active.status !== "executed" && (
                  <section className="card">
                    <h2>Ask a manager</h2>
                    <p className="muted">Save a note, then share the case with your manager.</p>
                    <label>
                      What needs checking?
                      <input
                        value={reason}
                        maxLength={500}
                        onChange={(event) => setReason(event.target.value)}
                        placeholder="For example: the carrier has not confirmed the parcel is lost"
                      />
                    </label>
                    <button
                      className="quiet"
                      disabled={locked || !reason.trim()}
                      onClick={() =>
                        void perform(() =>
                          request("/api/cases/" + active.id + "/escalate", {
                            reason,
                          }),
                        )
                      }
                    >
                      Ask for help
                    </button>
                  </section>
                )}
                <details className="card">
                  <summary>Technical details</summary>
                  {active.shipment_investigation && <p>{active.shipment_investigation.mode === "mock_specialists" ? "Simulated specialists" : active.shipment_investigation.mode === "simulated_decisions" ? "Simulated Decisions responses" : "Rules investigation"}</p>}
                  <pre>{JSON.stringify(active, null, 2)}</pre>
                </details>
              </>
            )}
          </section>
        </DeliveryWorkspace>
          <aside className="order-lookup">
            <section className="card">
              <h2>Check an order</h2>
              <form onSubmit={openCase}>
                <label>
                  Order
                  <select
                    aria-label="Order"
                    value={orderId}
                    onChange={(event) => setOrderId(event.target.value)}
                  >
                    {orders.map((order) => (
                      <option key={order.id} value={order.id}>
                        {order.id}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="selection-summary">
                  {items(
                    Object.fromEntries(
                      (
                        orders.find((order) => order.id === orderId)?.lines ||
                        []
                      ).map((line) => [line.variant_id, line.quantity]),
                    ),
                  )}
                </p>
                <button className="primary full" disabled={busy || !orderId}>
                  Start review
                </button>
              </form>
            </section>
            <section className="card inbox">
              <div className="sectionhead">
                <h2>All cases</h2>
                <span className="count">{cases.length}</span>
              </div>
              {cases.length === 0 ? (
                <p className="muted">No cases yet. Select an order to start.</p>
              ) : (
                <ul>
                  {cases.map((row) => (
                    <li key={row.id}>
                      <button
                        disabled={busy || Boolean(confirm)}
                        aria-pressed={row.id === selected}
                        className={
                          "case-row " + (row.id === selected ? "selected" : "")
                        }
                        onClick={() => void selectCase(row.id).catch(e => setError((e as Error).message))}
                      >
                        <strong>{row.request.order_id}</strong>
                        <span className={"status " + row.status}>
                          {labels[row.status] || row.status}
                        </span>
                        <small>{time(row.updated_at)}</small>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </aside>
      </main>
      {confirm && active && (
        <div className="modal-backdrop">
          <section
            className="modal card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <h2 id="confirm-title">
              {confirm.action === "approve"
                ? "Approve this replacement?"
                : "Create this replacement?"}
            </h2>
            <p>{items(confirm.items)}</p>
            <details className="approval-binding"><summary>Approval binding</summary><p>Proposal {confirm.proposalId}<br/>Case {confirm.caseId} · Generation {confirm.generation}<br/>Content hash {confirm.hash}</p></details>
            <p className="muted">
              {confirm.action === "approve"
                ? "Approve the items and quantities shown above. You will still need to choose Create replacement to set the items aside."
                : "Create the replacement for these items and set them aside. This does not ship them."}
            </p>
            <div className="modal-actions">
              <button
                className="quiet"
                disabled={busy}
                onClick={() => setConfirm(null)}
              >
                Cancel
              </button>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  void (confirm.action === "approve"
                    ? review("approve", confirm)
                    : execute(confirm))
                }
              >
                {confirm.action === "approve"
                  ? "Confirm approval"
                  : "Confirm replacement"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname.startsWith("/customer") ? <CustomerPortal /> : window.location.pathname.startsWith("/shop") ? <Shop /> : <App />}
  </React.StrictMode>,
);
