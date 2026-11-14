import React, { useEffect, useState } from "react";
import "./site-b.css";
type Receipt = {
  receipt: string;
  order: string;
  item: { variant_id: string; quantity: number; unit_price_minor: number };
  parcel: string;
};
type Parcel = {
  reference: string;
  order: string;
  variant: string;
  quantity: number;
  event: string | null;
  at: string | null;
};
export function SiteB() {
  const receiptId = window.location.pathname.split("/")[3];
  const [tab, setTab] = useState(false),
    [purchases, setPurchases] = useState<Receipt[]>([]),
    [receipt, setReceipt] = useState<Receipt | null>(null),
    [delivery, setDelivery] = useState(false),
    [parcel, setParcel] = useState<Parcel | null>(null),
    [opened, setOpened] = useState(false),
    [error, setError] = useState("");
  const load = (url: string) =>
    fetch(url).then((r) => {
      if (!r.ok) throw Error("The requested view is unavailable");
      return r.json();
    });
  useEffect(() => {
    if (receiptId)
      load("/shop-data/receipts/" + encodeURIComponent(receiptId))
        .then(setReceipt)
        .catch((e) => setError(e.message));
  }, [receiptId]);
  function showPurchases() {
    setTab(true);
    load("/shop-data/purchases")
      .then(setPurchases)
      .catch((e) => setError(e.message));
  }
  function showParcel() {
    setOpened(!opened);
    if (!opened && receipt)
      load("/shop-data/parcels/" + encodeURIComponent(receipt.parcel))
        .then(setParcel)
        .catch((e) => setError(e.message));
  }
  return (
    <div className="atelier">
      <header>
        <a href="/account" className="atelier-logo">
          FOLD & WEFT<span>Customer space</span>
        </a>
        <span>Fictional clothing account · snapshot 13 Nov 2026</span>
      </header>
      <main>
        <aside>
          <strong>Your account</strong>
          <a href="/account">Dashboard</a>
          <p>
            Preview customer
            <br />
            Alex Rivera
          </p>
          <small>
            Fictional records only.
            <br />
            No purchases or payments.
          </small>
        </aside>
        <div className="atelier-content">
          {error && <p role="alert">{error}</p>}
          {!receiptId && (
            <>
              <p className="atelier-eyebrow">Welcome back</p>
              <h1>A little space for your essentials.</h1>
              <div
                className="atelier-tabs"
                role="tablist"
                aria-label="Account views"
              >
                <button
                  role="tab"
                  aria-selected={!tab}
                  onClick={() => setTab(false)}
                >
                  Overview
                </button>
                <button role="tab" aria-selected={tab} onClick={showPurchases}>
                  Purchases
                </button>
              </div>
              {!tab ? (
                <section className="atelier-overview">
                  <h2>Everything, in its place.</h2>
                  <p>
                    Your receipts and delivery information live in Purchases.
                    Product details and parcel events are recorded separately.
                  </p>
                  <p>
                    For this read-only preview, account changes and checkout are
                    unavailable.
                  </p>
                </section>
              ) : (
                <section role="tabpanel" aria-label="Purchases">
                  <h2>Purchase archive</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>Receipt</th>
                        <th>Order reference</th>
                        <th>Item</th>
                        <th>Amount</th>
                        <th>Details</th>
                      </tr>
                    </thead>
                    <tbody>
                      {purchases.map((r) => (
                        <tr key={r.receipt}>
                          <td>{r.receipt}</td>
                          <td>{r.order}</td>
                          <td>Blue cotton shirt · M</td>
                          <td>$25.00</td>
                          <td>
                            <a href={"/account/receipts/" + r.receipt}>
                              Open receipt {r.receipt}
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}
            </>
          )}
          {receiptId && receipt && (
            <>
              <a href="/account" className="atelier-back">
                ← Account dashboard
              </a>
              <p className="atelier-eyebrow">
                Purchase receipt {receipt.receipt}
              </p>
              <h1>Order {receipt.order}</h1>
              <section aria-label="Purchased item">
                <h2>Items on this receipt</h2>
                <dl>
                  <div>
                    <dt>Order reference</dt>
                    <dd>{receipt.order}</dd>
                  </div>
                  <div>
                    <dt>Variant</dt>
                    <dd>{receipt.item.variant_id}</dd>
                  </div>
                  <div>
                    <dt>Quantity</dt>
                    <dd>{receipt.item.quantity}</dd>
                  </div>
                  <div>
                    <dt>Amount</dt>
                    <dd>$25.00 USD</dd>
                  </div>
                </dl>
              </section>
              <button
                className="atelier-disclosure"
                aria-expanded={delivery}
                onClick={() => setDelivery(!delivery)}
              >
                Delivery
              </button>
              {delivery && (
                <div className="atelier-delivery">
                  <p>
                    Parcel records belong to the order shown in each record.
                    Check the reference before using an event.
                  </p>
                  <button aria-expanded={opened} onClick={showParcel}>
                    Parcel {receipt.parcel}
                  </button>
                  {opened && parcel && (
                    <section aria-label="Parcel record">
                      <h2>Parcel record</h2>
                      <dl>
                        <div>
                          <dt>Order reference</dt>
                          <dd>{parcel.order}</dd>
                        </div>
                        <div>
                          <dt>Parcel reference</dt>
                          <dd>{parcel.reference}</dd>
                        </div>
                        <div>
                          <dt>Variant</dt>
                          <dd>{parcel.variant}</dd>
                        </div>
                        <div>
                          <dt>Quantity</dt>
                          <dd>{parcel.quantity}</dd>
                        </div>
                      </dl>
                      <h3>Carrier event history</h3>
                      {parcel.event ? (
                        <table>
                          <thead>
                            <tr>
                              <th>Carrier event</th>
                              <th>Recorded timestamp</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td>{parcel.event}</td>
                              <td>{parcel.at}</td>
                            </tr>
                          </tbody>
                        </table>
                      ) : (
                        <p>
                          No carrier event or timestamp is available for this
                          parcel.
                        </p>
                      )}
                      <p className="atelier-note">
                        This is page evidence only. No replacement is proposed
                        or authorised here.
                      </p>
                    </section>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </main>
      <footer>
        FOLD & WEFT · Fictional local snapshot · read-only account preview
      </footer>
    </div>
  );
}
