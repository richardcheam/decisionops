import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
// Read-only fixture server, separate from Commerce and its databases.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
const root = process.env.FIXTURE_ROOT || "/fixture";
const records = JSON.parse(
  fs.readFileSync(
    root + "/browser-investigation/fixtures/records.json",
    "utf8",
  ),
);
const startupIdentity = {
  server_sha256: createHash("sha256")
    .update(fs.readFileSync(fileURLToPath(import.meta.url)))
    .digest("hex"),
  records_sha256: createHash("sha256")
    .update(
      fs.readFileSync(root + "/browser-investigation/fixtures/records.json"),
    )
    .digest("hex"),
};
const site = process.env.FIXTURE_SITE;
if (!["a", "b"].includes(site)) throw Error("Choose fixture site a or b");
const dist = process.env.FIXTURE_DIST || "/dist";
const send = (res, status, value, type = "application/json") => {
  res.writeHead(status, {
    "Content-Type": type,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy":
      "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
  });
  res.end(typeof value === "string" ? value : JSON.stringify(value));
};
const documentAllowed = (p) =>
  site === "a"
    ? /^\/shop(?:\/account\/orders(?:\/OR-\d{4}(?:\/tracking)?)?|\/products\/[a-z-]+)?\/?$/.test(
        p,
      )
    : /^\/account(?:\/receipts\/RC-\d{4})?\/?$/.test(p);
http
  .createServer((req, res) => {
    if (!["GET", "HEAD"].includes(req.method))
      return send(res, 405, { error: "read_only" });
    const url = new URL(req.url, "http://fixture");
    const p = url.pathname;
    if (url.search || p.includes("%"))
      return send(res, 404, { error: "unsupported_path" });
    if (p === "/health")
      return send(res, 200, {
        status: "ready",
        site: "fictional shopper fixture",
        ...startupIdentity,
      });
    if (
      p.startsWith("/assets/") &&
      /^\/assets\/[A-Za-z0-9_.-]+\.(js|css)$/.test(p)
    ) {
      const file = path.join(dist, p);
      if (!fs.existsSync(file))
        return send(res, 404, { error: "asset_missing" });
      return send(
        res,
        200,
        fs.readFileSync(file, "utf8"),
        p.endsWith(".js") ? "application/javascript" : "text/css",
      );
    }
    if (site === "a" && p.startsWith("/demo-shop/orders")) {
      const match = p.match(
        /^\/demo-shop\/orders(?:\/(OR-\d{4})(\/tracking)?)?$/,
      );
      if (!match) return send(res, 404, {});
      const selected = match[1]
        ? records.a.filter((r) => r.id === match[1])
        : records.a;
      const rows = selected.map((r) => ({
        id: r.id,
        currency: "USD",
        lines: [records.item],
        shipment: match[1]
          ? {
              id: r.parcel,
              fulfilment_status: "shipped",
              ...(match[2]
                ? { carrier_status: r.event, carrier_observed_at: r.at }
                : {}),
            }
          : null,
      }));
      if (!rows.length) return send(res, 404, { error: "order_missing" });
      return send(res, 200, match[1] ? rows[0] : rows);
    }
    if (site === "b" && p === "/shop-data/purchases")
      return send(
        res,
        200,
        records.b.map((r) => ({
          receipt: r.receipt,
          order: r.id,
          item: records.item,
          parcel: r.parcel,
        })),
      );
    if (site === "b" && /^\/shop-data\/receipts\/RC-\d{4}$/.test(p)) {
      const r = records.b.find((r) => r.receipt === p.split("/").pop());
      return r
        ? send(res, 200, {
            receipt: r.receipt,
            order: r.id,
            item: records.item,
            parcel: r.parcel,
          })
        : send(res, 404, {});
    }
    if (site === "b" && /^\/shop-data\/parcels\/BX-\d{4}$/.test(p)) {
      const r = records.b.find((r) => r.parcel === p.split("/").pop());
      return r
        ? send(res, 200, {
            reference: r.parcel,
            order: r.parcel_order,
            variant: records.item.variant_id,
            quantity: records.item.quantity,
            event: r.event,
            at: r.at,
          })
        : send(res, 404, {});
    }
    if (documentAllowed(p)) {
      // Frozen evaluator fault: the page never supplies an event or a hidden answer.
      if (site === "a" && p === "/shop/account/orders/OR-5928/tracking")
        return send(
          res,
          503,
          "Carrier view temporarily unavailable",
          "text/plain",
        );
      return send(
        res,
        200,
        fs.readFileSync(dist + "/evaluation.html", "utf8"),
        "text/html",
      );
    }
    send(res, 404, { error: "not_found" });
  })
  .listen(8080, "0.0.0.0");
