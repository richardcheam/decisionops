import React, { useEffect, useState } from "react";

type Store = { id: string; name: string; role: "staff" | "approver" };
type Session = { email: string; stores: Store[] };
type Connection = { shop: string | null; connected: boolean };
type Line = { fulfillment_line_id: string; title: string; quantity: number; eligible: boolean; reason: string };
type Order = { order_id: string; name: string; lines: Line[] };
type Case = {
  id: string;
  order_id: string;
  fulfillment_line_id: string;
  quantity: number;
  status: string;
  dispatched: boolean;
  reason: string;
  proposal_hash: string | null;
  external_return_id: string | null;
};
type Confirmation = { action: "approve" | "confirm"; row: Case };

class PilotError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function pilot<T>(path: string, body?: object): Promise<T> {
  const response = await fetch("/pilot-api" + path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new PilotError(response.status, typeof result.detail === "string" ?
      result.detail : "The pilot request could not be completed.");
  }
  return result as T;
}

function statusLabel(status: string) {
  if (status === "needs_review" || status === "review") return "Needs review";
  return status.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase());
}

function ShopifyStore({ store }: { store: Store }) {
  const path = "/shopify/" + encodeURIComponent(store.id);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [caseId, setCaseId] = useState("");
  const [shop, setShop] = useState("");
  const [invite, setInvite] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Store["role"]>("staff");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const selected = cases.find(row => row.id === caseId);
  const manager = store.role === "approver";

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [state, existing, imported] = await Promise.all([
          pilot<Connection>(path), pilot<Case[]>(path + "/cases"), pilot<Order[]>(path + "/orders"),
        ]);
        if (active) {
          setConnection(state);
          setCases(existing);
          setOrders(imported);
        }
      } catch (failure) {
        if (active) setError((failure as Error).message);
      } finally {
        if (active) setBusy(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [path]);

  async function perform(task: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try { await task(); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }

  function show(row: Case) {
    setCases(previous => [row, ...previous.filter(other => other.id !== row.id)]);
    setCaseId(row.id);
  }

  function changeCase(row: Case, action: string, body: object = {}) {
    return perform(async () => show(await pilot<Case>(
      path + "/cases/" + encodeURIComponent(row.id) + "/" + action, body,
    )));
  }

  return <main className="pilot-layout">
    {error && <p role="alert" className="error">{error}</p>}
    <section className="card" aria-label="Shopify connection">
      <h2>Development store connection</h2>
      <p>{connection?.connected ? connection.shop + " is connected" : "No development store connected."}</p>
      {manager && !connection?.connected && <form onSubmit={event => {
        event.preventDefault();
        void perform(async () => {
          const result = await pilot<{ url: string }>(path + "/connect", { shop });
          window.location.assign(result.url);
        });
      }}>
        <label>Shopify domain<input value={shop} onChange={e => setShop(e.target.value)}
          placeholder="your-store.myshopify.com" required /></label>
        <button className="primary" disabled={busy}>Connect Shopify</button>
      </form>}
      {connection?.connected && <button disabled={busy} onClick={() => void perform(async () => {
        setOrders(await pilot<Order[]>(path + "/resync", {}));
      })}>Resync test orders</button>}
    </section>

    {manager && <section className="card" aria-label="Staff invitations">
      <h2>Staff invitations</h2>
      <form onSubmit={event => {
        event.preventDefault();
        void perform(async () => {
          setInvite("");
          const { token } = await pilot<{ token: string }>("/stores/" + encodeURIComponent(store.id) + "/invites", { email, role });
          setInvite(window.location.origin + "/pilot#invite=" + encodeURIComponent(token));
        });
      }}>
        <label>Staff email<input type="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>
        <label>Role<select value={role} onChange={e => setRole(e.target.value as Store["role"])}>
          <option value="staff">Support agent</option><option value="approver">Approver</option>
        </select></label>
        <button disabled={busy}>Create invitation</button>
      </form>
      {invite && <label>One-time invitation link<input readOnly value={invite} /></label>}
    </section>}

    <section className="card" aria-label="Imported test orders">
      <h2>Imported test orders</h2>
      {orders.length === 0 && <p>Connect the development shop and resync its fictional test orders.</p>}
      {orders.map(order => <article key={order.order_id}>
        <h3>{order.name}</h3>
        {order.lines.map(line => <div key={line.fulfillment_line_id}>
          <p>{line.title} · {line.eligible ? "Eligible for review" : line.reason}</p>
          <button disabled={busy} onClick={() => void perform(async () => show(await pilot<Case>(path + "/cases", {
            order_id: order.order_id, fulfillment_line_id: line.fulfillment_line_id,
          })))}>Open return case for {line.title}</button>
        </div>)}
      </article>)}
    </section>

    <section className="card" aria-label="Shopify return cases">
      <h2>Shopify return cases</h2>
      <button disabled={busy || Boolean(confirmation)} onClick={() => void perform(async () => {
        setCases(await pilot<Case[]>(path + "/cases"));
      })}>Refresh return cases</button>
      {cases.map(row => <button key={row.id} disabled={busy || Boolean(confirmation)}
        aria-pressed={row.id === caseId} onClick={() => setCaseId(row.id)}>
        {row.id} · {statusLabel(row.status)}
      </button>)}
      {selected && <article aria-label="Selected Shopify return">
        <h3>{selected.id}</h3>
        <p>Order {selected.order_id} · Fulfillment line {selected.fulfillment_line_id} · Quantity {selected.quantity}</p>
        <p role="status">{statusLabel(selected.status)}</p>
        <p>{selected.reason}</p>
        {selected.external_return_id && <p>
          {selected.status === "verified" ? "Verified Shopify return" : "Recorded Shopify reference"} {selected.external_return_id}
        </p>}
        {(selected.status === "draft" || selected.status === "needs_review" && !selected.dispatched) && <button disabled={busy} onClick={() => void changeCase(selected, "propose")}>Submit return proposal</button>}
        {manager && selected.proposal_hash && selected.status === "proposed" && <button disabled={busy}
          onClick={() => setConfirmation({ action: "approve", row: selected })}>Approve return proposal</button>}
        {manager && selected.proposal_hash && selected.status === "approved" && <button disabled={busy}
          onClick={() => setConfirmation({ action: "confirm", row: selected })}>Create Shopify return</button>}
        {manager && selected.dispatched && ["pending", "needs_review"].includes(selected.status) && <button disabled={busy}
          onClick={() => void changeCase(selected, "reconcile")}>Check Shopify for a saved return</button>}
      </article>}
    </section>

    {confirmation && <div className="modal-backdrop">
      <section className="modal card" role="dialog" aria-modal="true" aria-labelledby="pilot-confirm">
        <h2 id="pilot-confirm">{confirmation.action === "approve" ? "Approve this proposal?" : "Create this Shopify return?"}</h2>
        <p>{store.name} · Order {confirmation.row.order_id} · Fulfillment line {confirmation.row.fulfillment_line_id} · Quantity {confirmation.row.quantity}</p>
        <p>Proposal hash {confirmation.row.proposal_hash}</p>
        <button disabled={busy} onClick={() => setConfirmation(null)}>Cancel</button>
        <button className="primary" disabled={busy} onClick={() => {
          const { action, row } = confirmation;
          setConfirmation(null);
          void changeCase(row, action, { proposal_hash: row.proposal_hash });
        }}>{confirmation.action === "approve" ? "Confirm approval" : "Confirm creation"}</button>
      </section>
    </div>}
  </main>;
}

export function ShopifyWorkspace() {
  const queryStore = new URLSearchParams(window.location.search).get("store_id");
  const [session, setSession] = useState<Session | null>(null);
  const [storeId, setStoreId] = useState(queryStore ?? "");
  const [invite, setInvite] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("invite"));
  const [accepting, setAccepting] = useState(Boolean(invite));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(true);
  const [disabled, setDisabled] = useState(false);
  const [error, setError] = useState("");
  const store = session?.stores.find(row => row.id === storeId) ?? session?.stores[0];

  useEffect(() => {
    let active = true;
    if (invite) history.replaceState(null, "", window.location.pathname + window.location.search);
    pilot<Session>("/session").then(
      value => { if (active) setSession(value); },
      failure => {
        if (active && failure.status === 404) setDisabled(true);
        else if (active && failure.status !== 401) setError("The hosted pilot is unavailable.");
      },
    ).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);

  async function authenticate(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setSession(accepting && invite
        ? await pilot<Session>("/invites/accept", { token: invite, password })
        : await pilot<Session>("/login", { email, password }));
      if (accepting) setInvite(null);
      else if (invite) setAccepting(true);
    } catch (failure) { setError((failure as Error).message); }
    finally { setPassword(""); setBusy(false); }
  }

  if (disabled) return <main className="login card"><h1>Shopify development pilot</h1><p>The hosted pilot is disabled on this deployment.</p><a href="/staff">Open the fictional local demo</a></main>;
  if (!session || (invite && accepting)) return <main className="login card">
    <h1>Shopify development pilot</h1>
    <p>Use a development shop with fictional test orders.</p>
    <form className="loginform" onSubmit={authenticate}>
      {!accepting && <label>Email<input autoComplete="username" type="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>}
      {!session && <label>Password<input type="password" autoComplete={accepting ? "new-password" : "current-password"}
        required value={password} onChange={e => setPassword(e.target.value)} /></label>}
      <button className="primary" disabled={busy}>{accepting ? "Accept invitation" : "Sign in"}</button>
    </form>
    {invite && !session && <button type="button" onClick={() => setAccepting(!accepting)}>
      {accepting ? "Sign in with an existing account" : "Create an invited account"}
    </button>}
    {error && <p role="alert" className="error">{error}</p>}
  </main>;

  return <>
    <header className="topbar">
      <div className="brand"><p className="eyebrow">DecisionOps</p><h1>Shopify development pilot</h1></div>
      <div className="header-right">
        <span>{session.email}</span>
        {store && <label>Store<select value={store.id} onChange={e => setStoreId(e.target.value)}>
          {session.stores.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select></label>}
        <button disabled={busy} onClick={() => {
          setBusy(true);
          void pilot("/logout", {}).then(() => setSession(null)).catch(
            () => setError("Sign-out failed. Try again."),
          ).finally(() => setBusy(false));
        }}>Sign out</button>
      </div>
    </header>
    {error && <p role="alert" className="error">{error}</p>}
    {store ? <ShopifyStore key={store.id} store={store} /> : <main className="card">No store membership.</main>}
  </>;
}
