import React, { useEffect, useRef, useState } from "react";
import { DeliveryWorkspace, type ChatReply } from "../delivery-workspace";
import { caseStatusLabels, formatCaseItems, formatCaseTime, type Case } from "./case-data";
import { CasePanel } from "./case-panel";
import { ReturnWorkspace } from "./return-workspace";

type Order = {
  id: string;
  lines: { variant_id: string; quantity: number }[];
  shipments: { id: string }[];
};

type Confirmation = {
  action: "approve" | "execute";
  caseId: string;
  generation: number;
  proposalId: string;
  hash: string;
  items: Record<string, number>;
  operationId?: string;
};

class StaffRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export function StaffWorkspace() {
  const [auth, setAuth] = useState("");
  const [view, setView] = useState<"deliveries" | "returns">("deliveries");
  const [role, setRole] = useState<"staff" | "approver">("staff");
  const [conversationId, setConversationId] = useState("");
  const [staleEvidence, setStaleEvidence] = useState<{caseId:string;generation:number} | null>(null);
  const selectionFlight = useRef(false);
  const [username, setUsername] = useState("");
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
      throw new StaffRequestError(
        response.status === 503 && data?.detail === "Local assistant unavailable. Check the model and try again."
          ? "Local assistant unavailable. Check the model and try again."
          : response.status === 403 && data?.detail === "Origin is not permitted"
          ? "This address is not enabled for the demo. Use the demo address in the setup instructions."
          : response.status === 401
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
        response.status,
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
      if (selected) {
        try {
          await request("/api/conversations/" + conversation.id + "/select", { case_id: selected }, authorization);
        } catch (failure) {
          if (!(failure instanceof StaffRequestError) || failure.status !== 404) throw failure;
          setSelected("");
          setError("That case link is no longer available. Choose a case from the queue.");
        }
      }
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
          {active?.shipment_investigation?.state === "active" && !active.shipment_investigation.historical && <span className="tag tag-live" role="status">Specialists running</span>}
          <button type="button" className="quiet" disabled={busy || Boolean(confirm)}
            onClick={() => setView(view === "deliveries" ? "returns" : "deliveries")}>
            {view === "deliveries" ? "Return cases" : "Deliveries"}
          </button>
          <a href="/customer">Customer help</a>
          <span className="badge">Demo store · {role === "approver" ? "Approver" : "Staff"}</span>
          <button
            className="quiet"
            onClick={() => {
              setAuth("");
              setView("deliveries");
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
      {view === "returns" ? <main className="workspace">
        <div className="pageintro"><h1>Returns</h1></div>
        <ReturnWorkspace request={request} mayApprove={role === "approver"} />
      </main> : <main className="workspace delivery-dashboard">
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
          <CasePanel
            active={active}
            hasSelection={Boolean(selected)}
            busy={busy}
            mayApprove={role === "approver"}
            evidenceNeedsRefresh={evidenceNeedsRefresh}
            report={report}
            reason={reason}
            onStartInvestigation={() => void sendMessage("Fix this", crypto.randomUUID()).catch(e => setError((e as Error).message))}
            onCheckOrder={id => void perform(() => request("/api/cases/" + id + "/investigate", {}))}
            onApprove={() => confirmation("approve")}
            onDecline={() => void review("reject")}
            onCreateReplacement={() => confirmation("execute")}
            onReportChange={setReport}
            onSubmitReport={investigateShipment}
            onReasonChange={setReason}
            onEscalate={(id, reason) => void perform(() => request("/api/cases/" + id + "/escalate", { reason }))}
          />
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
                  {formatCaseItems(
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
                          {caseStatusLabels[row.status] || row.status}
                        </span>
                        <small>{formatCaseTime(row.updated_at)}</small>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </aside>
      </main>}
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
            <p>{formatCaseItems(confirm.items)}</p>
            <details className="approval-binding" open><summary>Approval binding</summary><p>Proposal {confirm.proposalId}<br/>Case {confirm.caseId} · Generation {confirm.generation}<br/>Content hash {confirm.hash}</p></details>
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
