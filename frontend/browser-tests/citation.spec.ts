/** Offline replay only. No browser, provider call, fixture navigation or changed grader. */
import { test, expect, type Browser } from "@playwright/test";
import fs from "node:fs";
import {
  BrowserInvestigation,
  type Finish,
} from "../../browser-investigation/harness.ts";
const fixture = JSON.parse(
  fs.readFileSync(
    "/workspace/repo/frontend/browser-tests/fixtures/live002-a1-citation.json",
    "utf8",
  ),
);
const limits = JSON.parse(
  fs.readFileSync(
    "/workspace/repo/browser-investigation/controller.json",
    "utf8",
  ),
);
function data() {
  return structuredClone(fixture);
}
function result(d: any): Finish {
  return JSON.parse(d.response.output[0].arguments).result;
}
function replay(d: any) {
  const h = new BrowserInvestigation(
    {} as Browser,
    d.goal,
    d.observations[0].url,
    { document: () => true, resource: () => false },
    limits,
  );
  (h as any).saved = new Map(d.observations.map((o: any) => [o.id, o]));
  return h;
}
function changeRecord(d: any, old: string, next: string) {
  const f = result(d);
  const o = d.observations.find(
    (o: any) => o.id === f.findings!.parcel!.observation,
  );
  const b = o.blocks.find(
    (b: any) => b.reference === f.findings!.parcel!.block,
  );
  b.text = b.text.replaceAll(old, next);
  for (const key of ["parcel", "claim", "event_time"])
    f.findings[key].quote = f.findings[key].quote.replaceAll(old, next);
  d.response.output[0].arguments = JSON.stringify({
    ...JSON.parse(d.response.output[0].arguments),
    result: f,
  });
}
test("saved live002 final response accepts its whole-record citation offline at frozen as_of", () => {
  const d = data();
  const h = replay(d);
  const r = h.finish(result(d));
  expect(r.result.outcome).toBe("evidence_found");
  expect(r.execution_authorized).toBe(false);
  expect(r.result.findings!.event_time!.quote).toBe(
    result(d).findings!.event_time!.quote,
  );
  fs.writeFileSync(
    process.env.BROWSER_ARTIFACT_DIR + "/replayed-A1.json",
    JSON.stringify(
      {
        label:
          "OFFLINE validator replay; historical live002 remains invalid_finish",
        result: r,
        audit: [
          ...d.observations.map((o: any) => ({ kind: "observation", data: o })),
          ...h.audit,
        ],
      },
      null,
      2,
    ),
  );
});
test("timestamp-only quote and one ISO source timestamp remain precise supported citations", () => {
  const d = data();
  const f = result(d);
  f.findings!.event_time!.quote = "13 Nov 2026, 10:00 UTC";
  expect(replay(d).finish(f).result.outcome).toBe("evidence_found");
  const iso = data();
  changeRecord(iso, "13 Nov 2026, 10:00 UTC", "2026-11-13T10:00:00Z");
  expect(replay(iso).finish(result(iso)).result.outcome).toBe("evidence_found");
});
test("stale or future timestamp is rejected against frozen assessment time", () => {
  for (const stamp of ["10 Nov 2026, 10:00 UTC", "13 Nov 2026, 13:00 UTC"]) {
    const d = data();
    changeRecord(d, "13 Nov 2026, 10:00 UTC", stamp);
    expect(() => replay(d).finish(result(d))).toThrow(/not current/);
  }
  const boundary = data();
  boundary.goal.as_of = "2026-11-14T10:00:00Z";
  expect(replay(boundary).finish(result(boundary)).result.outcome).toBe(
    "evidence_found",
  );
  const expired = data();
  expired.goal.as_of = "2026-11-14T10:00:00.001Z";
  expect(() => replay(expired).finish(result(expired))).toThrow(/not current/);
});
test("two timestamps in the cited record cannot be silently selected even with precise quote", () => {
  for (const stamp of [
    "13 Nov 2026, 11:00 UTC",
    "13 Nov 2026, 10:00 UTC",
    "2026-11-13T11:00:00+01:00",
  ]) {
    const d = data();
    const f = result(d);
    const o = d.observations.find(
      (o: any) => o.id === f.findings!.parcel!.observation,
    );
    o.blocks.find((b: any) => b.reference === f.findings!.parcel!.block).text +=
      " Another event " + stamp;
    f.findings!.event_time!.quote = "13 Nov 2026, 10:00 UTC";
    expect(() => replay(d).finish(f)).toThrow(/unambiguous/);
  }
});
test("wrong order, wrong parcel, another observation or a quote without the timestamp is rejected", () => {
  const wrong = data();
  changeRecord(wrong, "OR-4821", "OR-7396");
  expect(() => replay(wrong).finish(result(wrong))).toThrow(/wrong order/);
  const parcel = data();
  changeRecord(parcel, "PK-6204", "PK-9999");
  expect(() => replay(parcel).finish(result(parcel))).toThrow(/relationship/);
  const other = data();
  const f = result(other);
  f.findings!.event_time!.observation = other.observations[1].id;
  expect(() => replay(other).finish(f)).toThrow(/share parcel record/);
  const absent = data();
  const a = result(absent);
  a.findings!.event_time!.quote = "Update recorded";
  expect(() => replay(absent).finish(a)).toThrow(/timestamp/i);
});
test("invalid calendar date and unlabelled time do not establish evidence", () => {
  const invalid = data();
  changeRecord(invalid, "13 Nov 2026, 10:00 UTC", "31 Feb 2026, 10:00 UTC");
  expect(() => replay(invalid).finish(result(invalid))).toThrow(
    /timestamp|calendar/,
  );
  const noLabel = data();
  changeRecord(noLabel, "Update recorded", "Order created");
  expect(() => replay(noLabel).finish(result(noLabel))).toThrow(/timestamp/i);
});
