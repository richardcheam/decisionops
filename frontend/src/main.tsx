import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

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
const events: Record<string, string> = {
  opened: "Case opened",
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
    open: "Choose Check order to see whether a replacement is available.",
    awaiting_review: "The checks passed. Review the items below, then approve or decline the replacement.",
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
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [orderId, setOrderId] = useState("");
  const [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState("");
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
      await request("/api/session", undefined, authorization);
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
  const pending =
    active?.latest_job &&
    ["queued", "running"].includes(active.latest_job.status);
  const locked = busy || Boolean(pending);
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
        <div className="brandmark">D</div>
        <p className="eyebrow">DecisionOps Commerce</p>
        <h1>
          Make the next decision
          <br />
          with evidence.
        </h1>
        <p className="muted">
          Sign in to check orders and arrange replacements.
        </p>
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
        <p className="footnote">
          Demo store · Replacements need your approval
        </p>
      </main>
    );
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="brandmark small">D</span>
          <strong>
            DecisionOps <span>Commerce</span>
          </strong>
        </div>
        <div className="header-right">
          <span className="badge">Demo store</span>
          <button
            className="quiet"
            onClick={() => {
              setAuth("");
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
      <main className="workspace">
        <section className="pageintro">
          <p className="eyebrow">Staff workspace</p>
          <h1>Lost shipment reviews</h1>
          <p className="muted">
            Check an order. Review the replacement. Confirm when you are ready.
          </p>
        </section>
        {error && (
          <div role="alert" className="error">
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
        <div className="layout">
          <aside>
            <section className="card">
              <h2>Check an order</h2>
              <p className="muted compact">
                Select the order with the missing parcel. We will check whether
                all its items can be replaced.
              </p>
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
                <h2>Case inbox</h2>
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
                        onClick={() => {
                          setSelected(row.id);
                          setActive(null);
                          setError("");
                        }}
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
          <section className="casepanel">
            {!selected ? (
              <div className="empty card">
                <div className="empty-icon">↗</div>
                <h2>Choose an order to get started</h2>
                <p className="muted">
                  Select an order on the left and choose Start review. We will
                  check payment, delivery, stock and the store's replacement rules.
                </p>
              </div>
            ) : !active ? (
              <div className="card">Loading case…</div>
            ) : (
              <>
                <section className="card caseheader">
                  <div>
                    <p className="eyebrow">Order {active.request.order_id}</p>
                    <h2>Replacement review</h2>
                    <p className="muted">{items(active.request.items)}</p>
                  </div>
                  <span className={"status " + active.status}>
                    {active.operation && active.operation.status !== "verified"
                      ? "Needs confirmation"
                      : labels[active.status] || "Needs review"}
                  </span>
                </section>
                <section className="card" aria-label="Next step">
                  <h2>What to do next</h2>
                  <p>{pending ? "We are checking the order. You can leave this page and return later." : nextStep(active)}</p>
                </section>
                <div className="actions card">
                  <button
                    className="primary"
                    disabled={locked || active.status === "executed"}
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
                  </button>
                  {active.status === "awaiting_review" && (
                    <>
                      <button
                        disabled={locked}
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
                  {active.status === "approved" && (
                    <button
                      disabled={locked}
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
                {active.assessment && (
                  <section className="card">
                    <div className="sectionhead">
                      <h2>Order checks</h2>
                      <span className="muted">
                        {active.assessment.decision.unknowns.length} not
                        confirmed
                      </span>
                    </div>
                    <p className="muted compact">
                      All checks must be confirmed before a replacement can be
                      approved. Missing information does not mean the order failed.
                    </p>
                    <div className="requirements">
                      {Object.entries(requirements).map(([key, label]) => {
                        const value = active.assessment!.facts[key];
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
                  <ol className="timeline">
                    {active.events?.map((event) => (
                      <li key={event.id}>
                        <div>
                          <strong>{events[event.kind] || event.kind}</strong>
                          <time>{time(event.created_at)}</time>
                        </div>
                      </li>
                    ))}
                  </ol>
                </section>
                {active.status !== "executed" && (
                  <section className="card">
                    <h2>Need help?</h2>
                    <p className="muted">Add a note for your manager. This saves the note; you still need to share the case with them.</p>
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
                  <summary>Technical details (for support)</summary>
                  <pre>{JSON.stringify(active, null, 2)}</pre>
                </details>
              </>
            )}
          </section>
        </div>
        <footer>
          Demo store · No real payments or shipments
        </footer>
      </main>
      {confirm && active && (
        <div className="modal-backdrop">
          <section
            className="modal card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <p className="eyebrow">Please confirm</p>
            <h2 id="confirm-title">
              {confirm.action === "approve"
                ? "Approve this replacement?"
                : "Create this replacement?"}
            </h2>
            <p>{items(confirm.items)}</p>
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
    <App />
  </React.StrictMode>,
);
