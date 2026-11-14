import React, { useEffect, useState } from "react";
import "./shop.css";

type Product = {
  slug: string;
  name: string;
  price: number;
  kind: "shirt" | "knit" | "trousers" | "jacket";
  description: string;
  colours: { name: string; fill: string }[];
};
const products: Product[] = [
  {
    slug: "everyday-shirt",
    name: "Everyday cotton shirt",
    price: 25,
    kind: "shirt",
    description:
      "An easy, straight-cut shirt with a soft collar. Made for the everyday rotation.",
    colours: [
      { name: "Blue", fill: "#718eaa" },
      { name: "Red", fill: "#a15e52" },
    ],
  },
  {
    slug: "ribbed-knit",
    name: "Soft ribbed knit",
    price: 58,
    kind: "knit",
    description:
      "A relaxed layer with a ribbed neckline and a softly structured shape.",
    colours: [
      { name: "Oat", fill: "#c9bba3" },
      { name: "Charcoal", fill: "#51534f" },
    ],
  },
  {
    slug: "daily-trouser",
    name: "Daily straight trouser",
    price: 68,
    kind: "trousers",
    description:
      "A comfortable straight leg and a clean finish. A useful starting point for any outfit.",
    colours: [
      { name: "Sand", fill: "#aaa18d" },
      { name: "Ink", fill: "#424d56" },
    ],
  },
  {
    slug: "studio-jacket",
    name: "Studio overshirt",
    price: 85,
    kind: "jacket",
    description:
      "A light, roomy overshirt with generous pockets and a simple button front.",
    colours: [
      { name: "Olive", fill: "#777b66" },
      { name: "Clay", fill: "#a47b66" },
    ],
  },
];
type Order = {
  id: string;
  currency: string;
  lines: { variant_id: string; quantity: number; unit_price_minor: number }[];
  shipment: null | {
    id: string;
    fulfilment_status: string;
    carrier_status?: string;
    carrier_observed_at?: string;
  };
};
const money = (value: number, currency = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);
const itemName = (id: string) =>
  id.startsWith("shirt-") ? "Everyday cotton shirt" : id;
const itemChoice = (id: string) =>
  id === "shirt-blue-M" ? "Blue / M" : id === "shirt-red-M" ? "Red / M" : id;
function Garment({ product, fill }: { product: Product; fill?: string }) {
  const colour = fill || product.colours[0].fill;
  return (
    <svg
      viewBox="0 0 360 380"
      role="img"
      aria-label={`${product.name} — original demo illustration`}
    >
      <ellipse cx="180" cy="340" rx="104" ry="12" fill="#000" opacity=".06" />
      {product.kind === "trousers" ? (
        <g fill={colour} stroke="#353b35" strokeOpacity=".2" strokeWidth="2">
          <path d="M115 66h130l18 258h-69l-14-174-14 174H97z" />
          <path
            d="M117 90h126M180 69v82M127 95l-4 42m110-42 4 42"
            fill="none"
          />
          <path d="M180 70v24" strokeWidth="4" />
        </g>
      ) : (
        <g fill={colour} stroke="#353b35" strokeOpacity=".2" strokeWidth="2">
          <path d="m128 74-51 28-39 100 52 22 25-62-9 156h148l-9-156 25 62 52-22-39-100-51-28z" />
          <path
            d={
              product.kind === "knit"
                ? "M146 76q34 39 68 0l-7-6h-54z"
                : "m151 70 29 19 29-19 17 18-30 31-16-30-16 30-30-31z"
            }
            fill={product.kind === "knit" ? "#b8ab96" : colour}
          />
          {product.kind !== "knit" && (
            <>
              <path d="M180 91v225" fill="none" />
              {[133, 169, 205, 241, 277].map((y) => (
                <circle key={y} cx="180" cy={y} r="2.2" fill="#eae6db" />
              ))}
            </>
          )}
          {product.kind === "jacket" && (
            <>
              <path d="M122 141h39v43h-39zM200 141h39v43h-39z" fill="none" />
              <path d="M122 148h39m39 0h39" />
            </>
          )}
          <path d="M107 304h147M50 192l44 18m172 0 44-18" fill="none" />
        </g>
      )}
    </svg>
  );
}
function Header() {
  return (
    <>
      <div className="shop-notice">
        A fictional clothing store · no real purchases or customer data
      </div>
      <header className="shop-header">
        <a className="shop-wordmark" href="/shop">
          THREAD <span>/</span> STUDY
        </a>
        <nav aria-label="Shop navigation">
          <a href="/shop">Shop all</a>
          <a href="/shop/account/orders">My account</a>
          <a href="/">Staff console ↗</a>
        </nav>
      </header>
    </>
  );
}
function Lines({ order }: { order: Order }) {
  return (
    <>
      {order.lines.length ? (
        order.lines.map((line) => (
          <div className="shop-line" key={line.variant_id}>
            <div className="shop-thumb">
              <Garment
                product={products[0]}
                fill={line.variant_id.includes("red") ? "#a15e52" : "#718eaa"}
              />
            </div>
            <div>
              <a href="/shop/products/everyday-shirt">
                {itemName(line.variant_id)}
              </a>
              <p>
                {itemChoice(line.variant_id)} · Quantity {line.quantity}
              </p>
              <small>Variant {line.variant_id}</small>
            </div>
            <strong>
              {money(
                (line.quantity * line.unit_price_minor) / 100,
                order.currency,
              )}
            </strong>
          </div>
        ))
      ) : (
        <p>Item information is unavailable. Ask staff to check the order.</p>
      )}
    </>
  );
}
export function Shop() {
  const pathname = window.location.pathname;
  const parts = pathname.split("/").filter(Boolean);
  const product = products.find((p) => p.slug === parts[2]);
  const [colour, setColour] = useState(0);
  const [size, setSize] = useState("M");
  const account = parts[1] === "account";
  const id = parts[3];
  const tracking = parts[4] === "tracking";
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(account);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!account) return;
    const control = new AbortController();
    const suffix = id
      ? "/" + encodeURIComponent(id) + (tracking ? "/tracking" : "")
      : "";
    fetch("/demo-shop/orders" + suffix, { signal: control.signal })
      .then((r) => {
        if (!r.ok)
          throw Error(
            "The fictional account is unavailable. Check that the isolated shop fixture is enabled.",
          );
        return r.json();
      })
      .then((data) => {
        setOrders(Array.isArray(data) ? data : [data]);
        setLoading(false);
      })
      .catch((e) => {
        if (!control.signal.aborted) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => control.abort();
  }, [account, id, tracking]);
  const order = orders[0];
  const base = id ? "/shop/account/orders/" + encodeURIComponent(id) : "";
  return (
    <div className="shop">
      <Header />
      <main className="shop-main">
        {!parts[1] && (
          <>
            <section className="shop-hero">
              <div>
                <p className="shop-kicker">The everyday collection / 01</p>
                <h1>
                  Good clothes.
                  <br />
                  An easy everyday.
                </h1>
                <p>
                  Simple shapes, softer colours. A few pieces to make your own.
                </p>
                <a className="shop-button" href="#collection">
                  Explore the collection ↓
                </a>
              </div>
              <div className="shop-hero-art">
                <Garment product={products[0]} />
                <span>Original illustrations · fictional products</span>
              </div>
            </section>
            <section id="collection">
              <div className="shop-section-title">
                <h2>Made for your rotation</h2>
                <p>Four considered essentials</p>
              </div>
              <div className="shop-grid">
                {products.map((p) => (
                  <a
                    className="shop-product"
                    key={p.slug}
                    href={"/shop/products/" + p.slug}
                  >
                    <div className="shop-product-art">
                      <Garment product={p} />
                    </div>
                    <div className="shop-product-caption">
                      <h3>{p.name}</h3>
                      <span>{money(p.price)}</span>
                    </div>
                    <p>{p.colours.map((c) => c.name).join(" / ")}</p>
                  </a>
                ))}
              </div>
            </section>
          </>
        )}
        {parts[1] === "products" && product && (
          <>
            <a className="shop-back" href="/shop">
              ← All clothing
            </a>
            <section className="shop-product-detail">
              <div className="shop-product-art">
                <Garment
                  product={product}
                  fill={product.colours[colour].fill}
                />
              </div>
              <div className="shop-product-info">
                <p className="shop-kicker">Everyday essentials</p>
                <h1>{product.name}</h1>
                <p className="shop-price">{money(product.price)}</p>
                <p>{product.description}</p>
                <fieldset>
                  <legend>Colour: {product.colours[colour].name}</legend>
                  <div className="shop-choices">
                    {product.colours.map((c, i) => (
                      <button
                        key={c.name}
                        aria-pressed={i === colour}
                        onClick={() => setColour(i)}
                      >
                        <span
                          className={
                            "shop-swatch colour-" + c.name.toLowerCase()
                          }
                        />
                        {c.name}
                      </button>
                    ))}
                  </div>
                </fieldset>
                <fieldset>
                  <legend>Size</legend>
                  <div className="shop-choices">
                    {["S", "M", "L", "XL"].map((s) => (
                      <button
                        key={s}
                        aria-pressed={s === size}
                        onClick={() => setSize(s)}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </fieldset>
                <p aria-live="polite" className="shop-selection">
                  Selected: {product.colours[colour].name} / {size}
                </p>
                <div className="shop-soft-note">
                  Browse-only fictional shop. Checkout and payments are
                  unavailable.
                </div>
                <details>
                  <summary>Product & care</summary>
                  <p>
                    Demo product description. Local illustrations are
                    placeholders for photography; no product is being sold.
                  </p>
                </details>
              </div>
            </section>
          </>
        )}
        {account && (
          <>
            <div className="shop-account-heading">
              <p className="shop-kicker">My account</p>
              <h1>
                {tracking
                  ? "Track your shipment"
                  : id
                    ? "Order details"
                    : "Your orders"}
              </h1>
              <p>
                Maya Chen · fictional customer preview. No real sign-in or
                personal data.
              </p>
            </div>
            <div className="shop-account-layout">
              <aside>
                <a
                  href="/shop/account/orders"
                  aria-current={!id ? "page" : undefined}
                >
                  Order history
                </a>
                <p>This demo account contains fictional records only.</p>
              </aside>
              <section className="shop-account-content">
                {loading && <p role="status">Loading your orders…</p>}
                {error && <p role="alert">{error}</p>}
                {!loading && !error && !id && (
                  <>
                    {orders.map((o) => (
                      <article className="shop-order-card" key={o.id}>
                        <div className="shop-order-title">
                          <h2>Order {o.id}</h2>
                          <span>
                            {o.lines.reduce((n, l) => n + l.quantity, 0)}{" "}
                            item(s)
                          </span>
                        </div>
                        <Lines order={o} />
                        <div className="shop-order-bottom">
                          <span>
                            Total{" "}
                            {money(
                              o.lines.reduce(
                                (n, l) => n + l.quantity * l.unit_price_minor,
                                0,
                              ) / 100,
                              o.currency,
                            )}
                          </span>
                          <a
                            className="shop-button shop-button-outline"
                            href={"/shop/account/orders/" + o.id}
                          >
                            View order {o.id} →
                          </a>
                        </div>
                      </article>
                    ))}
                    {!orders.length && <p>No order records are available.</p>}
                  </>
                )}
                {!loading && !error && id && order && (
                  <>
                    <a
                      className="shop-back"
                      href={tracking ? base : "/shop/account/orders"}
                    >
                      ← {tracking ? "Order details" : "Order history"}
                    </a>
                    <div className="shop-detail-heading">
                      <h2>Order {order.id}</h2>
                      <span>USD · fictional purchase</span>
                    </div>
                    {!tracking && (
                      <>
                        <Lines order={order} />
                        <div className="shop-shipment-summary">
                          <div>
                            <h3>Shipment</h3>
                            <p>
                              {order.shipment?.fulfilment_status === "shipped"
                                ? "Handed to the carrier"
                                : order.shipment
                                  ? "Shipment status: " +
                                    order.shipment.fulfilment_status
                                  : "Shipment information unavailable"}
                            </p>
                            {order.shipment && (
                              <small>Reference {order.shipment.id}</small>
                            )}
                          </div>
                          <a className="shop-button" href={base + "/tracking"}>
                            Track shipment →
                          </a>
                        </div>
                        <p className="shop-muted">
                          Need help with a missing parcel? Share this order and
                          shipment reference with staff.
                        </p>
                      </>
                    )}
                    {tracking && (
                      <>
                        <div
                          className={
                            "shop-tracking " +
                            (order.shipment?.carrier_status === "lost"
                              ? "shop-tracking-lost"
                              : "")
                          }
                        >
                          <span className="shop-pill">Carrier update</span>
                          <h2>
                            {order.shipment?.carrier_status === "lost"
                              ? "Parcel reported lost"
                              : order.shipment?.carrier_status === "in_transit"
                                ? "Last reported in transit"
                                : "Tracking information unavailable"}
                          </h2>
                          <p>
                            {order.shipment?.carrier_status === "lost"
                              ? "The carrier explicitly reports this shipment as lost. Staff can check which resolutions are available."
                              : "There is no loss confirmation on this page. An old update cannot establish the parcel’s current location."}
                          </p>
                        </div>
                        <dl className="shop-tracking-record">
                          <div>
                            <dt>Order reference</dt>
                            <dd>{order.id}</dd>
                          </div>
                          <div>
                            <dt>Shipment reference</dt>
                            <dd>{order.shipment?.id || "Unavailable"}</dd>
                          </div>
                          <div>
                            <dt>Carrier status</dt>
                            <dd>
                              {order.shipment?.carrier_status?.replaceAll(
                                "_",
                                " ",
                              ) || "Unavailable"}
                            </dd>
                          </div>
                          <div>
                            <dt>Update recorded</dt>
                            <dd>
                              {order.shipment?.carrier_observed_at
                                ? new Date(
                                    order.shipment.carrier_observed_at,
                                  ).toLocaleString("en-GB", {
                                    dateStyle: "medium",
                                    timeStyle: "short",
                                    timeZone: "UTC",
                                  }) + " UTC"
                                : "Unavailable"}
                            </dd>
                          </div>
                        </dl>
                        <p className="shop-soft-note">
                          This page presents the current fictional shipment
                          record. It does not confirm replacement stock,
                          previous compensation or store permission. Staff must
                          investigate those separately.
                        </p>
                        <a className="shop-text-link" href={base}>
                          Back to order details →
                        </a>
                      </>
                    )}
                  </>
                )}
              </section>
            </div>
          </>
        )}
        {parts[1] && !account && !(parts[1] === "products" && product) && (
          <section>
            <h1>Page not found</h1>
            <a href="/shop">Return to the shop</a>
          </section>
        )}
      </main>
      <footer className="shop-footer">
        <strong>THREAD / STUDY</strong>
        <span>
          A local fictional browser fixture. No checkout, real customer account
          or live carrier connection.
        </span>
        <a href="/shop/account/orders">View the demo order journey →</a>
      </footer>
    </div>
  );
}
