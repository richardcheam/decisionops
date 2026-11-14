/** Private transport allowlists, NOT navigation instructions or policy features. */
import type { Transport } from "./harness.ts";
export function shopperTransport(origins: string[]): Transport {
  const local = (u: URL) =>
    origins.includes(u.origin) &&
    u.hostname === "127.0.0.1" &&
    u.protocol === "http:" &&
    !u.search &&
    !u.username &&
    !u.password &&
    !u.pathname.includes("%");
  const document = (u: URL) =>
    local(u) &&
    (/^\/shop(?:\/account\/orders(?:\/OR-\d{4}(?:\/tracking)?)?|\/products\/[a-z-]+)?\/?$/.test(
      u.pathname,
    ) ||
      /^\/account(?:\/receipts\/RC-\d{4})?\/?$/.test(u.pathname));
  const resource = (u: URL, d: URL, text: string) => {
    if (!local(u) || u.origin !== d.origin || !document(d)) return false;
    if (/^\/assets\/[A-Za-z0-9_.-]+\.(js|css)$/.test(u.pathname)) return true;
    if (d.pathname === "/shop/account/orders")
      return u.pathname === "/demo-shop/orders";
    const a = d.pathname.match(
      /^\/shop\/account\/orders\/(OR-\d{4})(\/tracking)?$/,
    );
    if (a) return u.pathname === "/demo-shop/orders/" + a[1] + (a[2] || "");
    if (d.pathname === "/account") return u.pathname === "/shop-data/purchases";
    const b = d.pathname.match(/^\/account\/receipts\/(RC-\d{4})$/);
    if (b) {
      if (u.pathname === "/shop-data/receipts/" + b[1]) return true;
      const parcel = u.pathname.match(/^\/shop-data\/parcels\/(BX-\d{4})$/);
      return !!parcel && text.includes(parcel[1]);
    }
    return false;
  };
  return { document, resource };
}
