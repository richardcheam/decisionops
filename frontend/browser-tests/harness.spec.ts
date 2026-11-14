/** Model-free contract driver: selectors/action names and evaluator truth stay HERE. */
import { test, expect, chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import {
  BrowserInvestigation,
  GuardError,
  type Goal,
  type Observation,
  type Citation,
} from "../../browser-investigation/harness.ts";
import { shopperTransport } from "../../browser-investigation/permissions.ts";
const root = path.resolve("/workspace/repo/browser-investigation");
const limits = JSON.parse(fs.readFileSync(root + "/controller.json", "utf8"));
const matrix = JSON.parse(
  fs.readFileSync(root + "/evaluation/matrix.json", "utf8"),
);
const origins = ["http://127.0.0.1:8096", "http://127.0.0.1:8097"];
function citation(o: Observation, text: string): Citation {
  const block = o.blocks.find((b) => !b.truncated && b.text.includes(text));
  if (!block) throw Error("Missing visible citation " + text);
  return { observation: o.id, block: block.reference, quote: text };
}
async function press(h: BrowserInvestigation, o: Observation, name: string) {
  fs.writeFileSync(
    process.env.BROWSER_ARTIFACT_DIR +
      "/before-" +
      name.replace(/[^a-z0-9]/gi, "_") +
      ".json",
    JSON.stringify(o, null, 2),
  );
  const c = o.controls.find((c) => c.name === name);
  expect(c, "visible control " + name).toBeTruthy();
  return h.act(o.id, c!.reference);
}
for (const scenario of matrix.cases)
  test("model-free contract " + scenario.id, async ({ browser }) => {
    const origin = scenario.origin === "a" ? origins[0] : origins[1];
    const h = await new BrowserInvestigation(
      browser,
      scenario.input.goal,
      origin + scenario.input.entry_path,
      shopperTransport(origins),
      limits,
    ).init();
    try {
      let o = await h.open(h.startURL);
      let item: Observation;
      if (scenario.origin === "a") {
        o = await press(
          h,
          o,
          "View order " + scenario.input.goal.order_reference + " →",
        );
        item = o;
        const ref = o.controls.find((c) => c.name === "Track shipment →")!;
        if (scenario.id === "G2") {
          await expect(h.act(o.id, ref.reference)).rejects.toMatchObject({
            kind: "navigation_failure",
          });
          await expect(
            h.open(origin + "/shop/account/orders/OR-5928/tracking"),
          ).rejects.toMatchObject({ kind: "navigation_failure" });
          const result = h.finish({
            outcome: "tool_unavailable",
            reason: "navigation_failure",
            unknowns: ["carrier_claim", "carrier_event_time"],
          });
          expect(result.result.outcome).toBe(scenario.expected.outcome);
          fs.writeFileSync(
            process.env.BROWSER_ARTIFACT_DIR + "/" + scenario.id + ".json",
            JSON.stringify(
              {
                driver: "scripted model-free, not transfer",
                result,
                audit: h.audit,
              },
              null,
              2,
            ),
          );
          return;
        }
        o = await h.act(o.id, ref.reference);
      } else {
        o = await press(h, o, "Purchases");
        const receipt =
          scenario.id === "B1"
            ? "RC-9138"
            : scenario.id === "B2"
              ? "RC-2647"
              : "RC-6812";
        o = await press(h, o, "Open receipt " + receipt);
        item = o;
        expect(o.text).not.toContain("Loss confirmed");
        o = await press(h, o, "Delivery");
        expect(o.text).not.toContain("Loss confirmed");
        const parcel =
          scenario.id === "B1"
            ? "BX-6942"
            : scenario.id === "B2"
              ? "BX-3106"
              : "BX-2375";
        o = await press(h, o, "Parcel " + parcel);
      }
      fs.writeFileSync(
        process.env.BROWSER_ARTIFACT_DIR + "/final-" + scenario.id + ".json",
        JSON.stringify(o, null, 2),
      );
      const order = scenario.input.goal.order_reference;
      const itemBlock = item!.blocks.find(
        (b) =>
          !b.truncated &&
          b.text.includes(order) &&
          b.text.includes("shirt-blue-M") &&
          /Quantity\s*1/.test(b.text),
      )!;
      const f = {
        order: citation(item!, order),
        item: {
          observation: item!.id,
          block: itemBlock.reference,
          quote: itemBlock.text.slice(0, 500),
        },
      };
      let result;
      if (scenario.id === "B2") {
        const block = o.blocks.find(
          (b) =>
            b.text.includes("BX-3106") &&
            b.text.includes("No carrier event or timestamp") &&
            !b.truncated,
        )!;
        result = h.finish({
          outcome: "missing_evidence",
          reason: "carrier_event_missing",
          findings: {
            ...f,
            parcel: {
              observation: o.id,
              block: block.reference,
              quote: "BX-3106",
            },
          },
          citations: [
            {
              observation: o.id,
              block: block.reference,
              quote:
                "No carrier event or timestamp is available for this parcel.",
            },
          ],
          unknowns: ["carrier_claim", "carrier_event_time"],
        });
      } else if (scenario.id === "G1") {
        const block = o.blocks.find(
          (b) =>
            b.text.includes("OR-9055") &&
            b.text.includes("Loss confirmed") &&
            !b.text.includes("OR-9054"),
        )!;
        expect(() =>
          h.finish({
            outcome: "evidence_found",
            reason: "found",
            unknowns: [],
            findings: {
              ...f,
              parcel: {
                observation: o.id,
                block: block.reference,
                quote: "BX-2375",
              },
              claim: {
                observation: o.id,
                block: block.reference,
                quote: "Loss confirmed",
              },
              event_time: {
                observation: o.id,
                block: block.reference,
                quote: "2026-11-13T10:00:00Z",
              },
            },
          }),
        ).toThrow(/wrong order|wrong.*binding/);
        result = h.finish({
          outcome: "wrong_binding",
          reason: "wrong_binding",
          citations: [
            { observation: o.id, block: block.reference, quote: "OR-9055" },
          ],
          unknowns: ["requested_parcel_event"],
        });
      } else {
        const carrier =
          scenario.id === "B1"
            ? "Loss confirmed"
            : scenario.id === "A2"
              ? "in transit"
              : "lost";
        const stamp =
          scenario.id === "B1"
            ? "2026-11-13T10:00:00Z"
            : scenario.id === "A2"
              ? "10 Nov 2026, 10:00 UTC"
              : "13 Nov 2026, 10:00 UTC";
        const parcel =
          scenario.id === "B1"
            ? "BX-6942"
            : scenario.id === "A2"
              ? "PK-8713"
              : "PK-6204";
        const block = o.blocks.find(
          (b) =>
            !b.truncated &&
            b.text.includes(order) &&
            b.text.includes(parcel) &&
            b.text.includes(stamp),
        )!;
        const fields = {
          ...f,
          parcel: { observation: o.id, block: block.reference, quote: parcel },
          claim: { observation: o.id, block: block.reference, quote: carrier },
          event_time: {
            observation: o.id,
            block: block.reference,
            quote: stamp,
          },
        };
        if (scenario.id === "A2") {
          expect(() =>
            h.finish({
              outcome: "evidence_found",
              reason: "found",
              unknowns: [],
              findings: fields,
            }),
          ).toThrow(/not current/);
          result = h.finish({
            outcome: "missing_evidence",
            reason: "stale_event",
            findings: fields,
            unknowns: ["current_loss_confirmation"],
          });
        } else
          result = h.finish({
            outcome: "evidence_found",
            reason: "recorded_current_event",
            findings: fields,
            unknowns: [],
          });
      }
      expect(result.result.outcome).toBe(scenario.expected.outcome);
      expect(result.execution_authorized).toBe(false);
      fs.writeFileSync(
        process.env.BROWSER_ARTIFACT_DIR + "/" + scenario.id + ".json",
        JSON.stringify(
          {
            driver: "scripted model-free, not transfer",
            result,
            audit: h.audit,
          },
          null,
          2,
        ),
      );
    } finally {
      await h.close();
    }
  });
test("stale references, blocked URLs/methods/redirects do not send forbidden requests", async ({
  browser,
}) => {
  const hits: string[] = [];
  const server = http.createServer((req, res) => {
    hits.push(req.method + " " + req.url);
    if (req.url === "/redirect") {
      res.writeHead(302, { Location: "/private" });
      res.end();
      return;
    }
    res.setHeader("Content-Type", "text/html");
    res.end(
      '<html><body><h1>Order OR-4821</h1><div hidden>PRIVATE_MARKER</div><div style="display:none">HIDDEN_STATE</div><button aria-expanded="false" onclick="this.setAttribute(\'aria-expanded\',\'true\')">Delivery</button><a href="/redirect">Next</a><script>window.secret="SCRIPT_PRIVATE"</script></body></html>',
    );
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const address = server.address() as { port: number };
  const origin = "http://127.0.0.1:" + address.port;
  const transport = {
    document: (u: URL) =>
      u.origin === origin && ["/", "/redirect"].includes(u.pathname),
    resource: () => false,
  };
  const goal = matrix.cases[0].input.goal;
  const h = await new BrowserInvestigation(
    browser,
    goal,
    origin + "/",
    transport,
    limits,
  ).init();
  try {
    let o = await h.open(h.startURL);
    expect(JSON.stringify(o)).not.toMatch(
      /PRIVATE_MARKER|HIDDEN_STATE|SCRIPT_PRIVATE/,
    );
    const older = o;
    o = await press(h, o, "Delivery");
    await expect(
      h.act(older.id, older.controls[0].reference),
    ).rejects.toMatchObject({ kind: "stale_reference" });
    await expect(h.open(origin + "/private")).rejects.toMatchObject({
      kind: "blocked_request",
    });
    await expect(h.open("http://example.invalid/")).rejects.toMatchObject({
      kind: "blocked_request",
    });
    await expect(press(h, o, "Next")).rejects.toMatchObject({
      kind: "blocked_request",
    });
    expect(hits).not.toContain("GET /private");
    expect(hits).not.toContain("POST /");
    // Direct fake-page POST is transport adversarial testing, not a policy capability.
    const internal = (h as any).page;
    await internal.evaluate(() =>
      fetch("/", { method: "POST", body: "deny" }).catch(() => {}),
    );
    expect(hits.filter((x) => x.startsWith("POST"))).toEqual([]);
    const error = h.failure(new GuardError("blocked_request", "guard check"));
    const stop = h.finish({
      outcome: "blocked_request",
      reason: error.kind,
      unknowns: ["carrier_event"],
    });
    expect(stop.result.outcome).toBe("blocked_request");
  } finally {
    await h.close();
    await new Promise<void>((r) => server.close(() => r()));
  }
});
