/** Untrusted page observations only. No fixture truth, policy, SDK or Commerce import. */
import { createHash, randomUUID } from "node:crypto";
import http from "node:http";
import type {
  Browser,
  BrowserContext,
  Page,
  ElementHandle,
  Route,
  Request,
} from "@playwright/test";
export type Goal = {
  instruction: string;
  order_reference: string;
  variant: string;
  quantity: number;
  as_of: string;
};
export type Limits = {
  wall_seconds: number;
  actions: number;
  observations: number;
  frame_bytes: number;
  context_bytes: number;
  navigation_ms: number;
  read_retry: number;
  tool_calls: number;
  network_requests: number;
  resource_bytes: number;
  response_bytes: number;
};
export type Citation = { observation: string; block: string; quote: string };
export type Finding = {
  order: Citation;
  item: Citation;
  parcel?: Citation;
  claim?: Citation;
  event_time?: Citation;
};
export type Finish = {
  outcome:
    | "evidence_found"
    | "missing_evidence"
    | "wrong_binding"
    | "tool_unavailable"
    | "blocked_request"
    | "budget_exhausted";
  reason: string;
  findings?: Finding;
  citations?: Citation[];
  unknowns: string[];
};
export type Block = { reference: string; text: string; truncated: boolean };
export type Observation = {
  id: string;
  url: string;
  observed_at: string;
  document_hash: string;
  text: string;
  blocks: Block[];
  controls: { reference: string; role: string; name: string; state: string }[];
  truncated: boolean;
};
export class GuardError extends Error {
  constructor(
    public kind: string,
    message: string,
  ) {
    super(message);
  }
}
const hash = (s: string) => createHash("sha256").update(s).digest("hex");
const norm = (s: string) => s.replace(/\s+/g, " ").trim();
const byte = (v: unknown) => Buffer.byteLength(JSON.stringify(v), "utf8");
const clip = (s: string, max: number) => {
  let end = Math.min(s.length, max);
  while (Buffer.byteLength(s.slice(0, end), "utf8") > max) end--;
  return s.slice(0, end);
};
/** Resolve only a timestamp actually quoted from one labelled, bound tracking record.
 * No newest-date selection, inference from other blocks, or calendar normalization.
 */
function citationTimestamp(block: Block, quote: string): number {
  const source = norm(block.text);
  const tokens =
    source.match(
      /\b(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})|\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}, \d{2}:\d{2} UTC)\b/g,
    ) || [];
  const labels =
    source.match(/\b(?:Update recorded|Recorded timestamp)\b/g) || [];
  if (tokens.length !== 1 || labels.length !== 1)
    throw new GuardError(
      "invalid_citation",
      "Tracking record needs one unambiguous labelled timestamp",
    );
  const token = tokens[0];
  if (!norm(quote).includes(token))
    throw new GuardError(
      "invalid_citation",
      "Timestamp must be present in the actual citation quote",
    );
  const iso = token.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?Z$/,
  );
  const display = token.match(
    /^(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4}), (\d{2}):(\d{2}) UTC$/,
  );
  if (!iso && !display)
    throw new GuardError(
      "invalid_citation",
      "Unsupported tracking timestamp format",
    );
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const [year, month, day, hour, minute, second, millis] = iso
    ? [
        +iso[1],
        +iso[2] - 1,
        +iso[3],
        +iso[4],
        +iso[5],
        +iso[6],
        +(iso[7] || "0").padEnd(3, "0"),
      ]
    : [
        +display![3],
        months.indexOf(display![2]),
        +display![1],
        +display![4],
        +display![5],
        0,
        0,
      ];
  const date = new Date(0);
  date.setUTCFullYear(year, month, day);
  date.setUTCHours(hour, minute, second, millis);
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month ||
    date.getUTCDate() !== day ||
    date.getUTCHours() !== hour ||
    date.getUTCMinutes() !== minute ||
    date.getUTCSeconds() !== second
  )
    throw new GuardError("invalid_citation", "Invalid calendar timestamp");
  return date.getTime();
}

export type Transport = {
  document: (url: URL) => boolean;
  resource: (url: URL, document: URL, observedText: string) => boolean;
};
export class BrowserInvestigation {
  private inflight = 0;
  private requests = new Set<http.ClientRequest>();
  private networkRequests = 0;
  private resourceBytes = 0;
  private context!: BrowserContext;
  private page!: Page;
  private end: number;
  private actions = 0;
  private observations = 0;
  private bytes = 0;
  private calls = 0;
  private finished = false;
  private allowedLinks = new Set<string>();
  private handles = new Map<string, ElementHandle<Element>>();
  private current?: Observation;
  private saved = new Map<string, Observation>();
  private fingerprint = "";
  private pendingError?: GuardError;
  private lastError?: GuardError;
  private failures = new Map<string, number>();
  readonly audit: { kind: string; at: string; data: unknown }[] = [];
  constructor(
    private browser: Browser,
    readonly goal: Goal,
    readonly startURL: string,
    private transport: Transport,
    private limits: Limits,
  ) {
    if (
      !/^OR-\d{4}$/.test(goal.order_reference) ||
      !Number.isInteger(goal.quantity) ||
      goal.quantity < 1 ||
      !goal.variant ||
      byte(goal) > 2000 ||
      !Number.isFinite(Date.parse(goal.as_of))
    )
      throw new GuardError("invalid_goal", "Invalid bounded fictional goal");
    this.end = Date.now() + limits.wall_seconds * 1000;
    this.safeURL(startURL);
    if (!transport.document(new URL(startURL)))
      throw new GuardError(
        "blocked_request",
        "Start page is outside shopper scope",
      );
  }
  async init() {
    this.context = await this.browser.newContext({
      serviceWorkers: "block",
      acceptDownloads: false,
    });
    await this.context.route("**/*", (route) => this.route(route));
    await this.context.routeWebSocket("**/*", (socket) => {
      this.pendingError = new GuardError("blocked_request", "WebSocket denied");
      socket.close();
    });
    this.page = await this.context.newPage();
    this.context.on("page", (p) => {
      if (p !== this.page) {
        this.pendingError = new GuardError("blocked_request", "Popup denied");
        void p.close();
      }
    });
    this.page.on("dialog", (d) => {
      this.pendingError = new GuardError("blocked_request", "Dialog denied");
      void d.dismiss();
    });
    this.page.on("download", (d) => {
      this.pendingError = new GuardError("blocked_request", "Download denied");
      void d.cancel();
    });
    return this;
  }
  private note(kind: string, data: unknown) {
    this.audit.push({ kind, at: new Date().toISOString(), data });
  }
  private check(action = false) {
    if (this.finished) throw new GuardError("terminal", "Run already finished");
    if (Date.now() >= this.end || ++this.calls > this.limits.tool_calls)
      throw new GuardError("budget_exhausted", "Run deadline or tool-call cap");
    if (action) {
      if (this.actions >= this.limits.actions)
        throw new GuardError("budget_exhausted", "Action attempt cap");
      this.actions++;
    }
  }
  private remaining() {
    return Math.max(
      1,
      Math.min(this.limits.navigation_ms, this.end - Date.now()),
    );
  }
  private safeURL(raw: string) {
    let u: URL;
    try {
      u = new URL(raw);
    } catch {
      throw new GuardError("blocked_request", "Malformed URL");
    }
    if (
      u.protocol !== "http:" ||
      u.hostname !== "127.0.0.1" ||
      u.username ||
      u.password ||
      u.search ||
      u.pathname.includes("%") ||
      raw.includes("\\")
    )
      throw new GuardError(
        "blocked_request",
        "Nonlocal, credentialed or encoded/query URL denied",
      );
    if (u.origin !== new URL(this.startURL).origin)
      throw new GuardError("blocked_request", "Run origin change denied");
    return u;
  }
  private async route(route: Route) {
    const r = route.request();
    try {
      const u = this.safeURL(r.url());
      const headers = r.headers();
      if (
        !["GET", "HEAD"].includes(r.method()) ||
        headers.authorization ||
        headers.cookie ||
        headers["proxy-authorization"]
      )
        throw new GuardError(
          "blocked_request",
          "Method or credential header denied",
        );
      if (r.frame() !== this.page.mainFrame())
        throw new GuardError("blocked_request", "Unowned frame denied");
      const isDocument = r.isNavigationRequest();
      if (isDocument) {
        if (!this.transport.document(u) || !this.allowedLinks.has(u.href))
          throw new GuardError(
            "blocked_request",
            "Unobserved or out-of-scope document denied",
          );
      } else {
        if (u.pathname === "/favicon.ico") {
          await route.fulfill({ status: 204, body: "" });
          return;
        }
        const doc = this.safeURL(r.frame().url());
        if (
          !["script", "stylesheet", "fetch", "xhr", "image"].includes(
            r.resourceType(),
          ) ||
          !this.transport.resource(u, doc, this.current?.text || "")
        )
          throw new GuardError(
            "blocked_request",
            "Unneeded shopper resource denied",
          );
      }
      if (++this.networkRequests > this.limits.network_requests)
        throw new GuardError("budget_exhausted", "Network request cap");
      this.note("request_allowed", {
        url: u.href,
        method: r.method(),
        type: r.resourceType(),
      });
      if ((this.failures.get(u.href) || 0) > this.limits.read_retry)
        throw new GuardError(
          "navigation_failure",
          "Known-read retry cap exhausted",
        );
      try {
        this.inflight++;
        const response = await this.fetchBounded(u, r.method());
        await route.fulfill(response);
      } catch (error) {
        if (error instanceof GuardError && error.kind === "navigation_failure")
          this.failures.set(u.href, (this.failures.get(u.href) || 0) + 1);
        throw error;
      } finally {
        this.inflight--;
      }
    } catch (e) {
      const error =
        e instanceof GuardError
          ? e
          : new GuardError(
              "navigation_failure",
              "Bounded shopper request failed",
            );
      this.pendingError = error;
      this.note("request_denied", { kind: error.kind, reason: error.message });
      await route.abort("blockedbyclient").catch(() => {});
    }
  }
  private fetchBounded(
    u: URL,
    method: string,
  ): Promise<{
    status: number;
    headers: Record<string, string>;
    body: Buffer;
  }> {
    let timer: ReturnType<typeof setTimeout>;
    let req: http.ClientRequest;
    let received: http.IncomingMessage | undefined;
    return new Promise<{
      status: number;
      headers: Record<string, string>;
      body: Buffer;
    }>((resolve, reject) => {
      req = http.request(
        u,
        { method, headers: { Accept: "*/*" }, timeout: this.remaining() },
        (response) => {
          received = response;
          const status = response.statusCode || 0;
          if (status >= 300 && status < 400) {
            response.destroy();
            reject(
              new GuardError(
                "blocked_request",
                "Redirect denied before follow",
              ),
            );
            return;
          }
          if (
            String(response.headers["content-disposition"] || "").includes(
              "attachment",
            )
          ) {
            response.destroy();
            reject(new GuardError("blocked_request", "Attachment denied"));
            return;
          }
          if (status >= 400) {
            response.destroy();
            reject(
              new GuardError(
                "navigation_failure",
                "Shopper page/read unavailable",
              ),
            );
            return;
          }
          const chunks: Buffer[] = [];
          let bytes = 0;
          response.on("data", (chunk: Buffer) => {
            bytes += chunk.length;
            if (
              (this.resourceBytes += chunk.length) >
                this.limits.resource_bytes ||
              bytes > this.limits.response_bytes
            ) {
              response.destroy();
              reject(
                new GuardError(
                  this.resourceBytes > this.limits.resource_bytes
                    ? "budget_exhausted"
                    : "navigation_failure",
                  "Shopper resource byte cap",
                ),
              );
            } else chunks.push(chunk);
          });
          response.on("end", () => {
            const headers: Record<string, string> = {};
            for (const key of [
              "content-type",
              "cache-control",
              "content-security-policy",
              "x-content-type-options",
            ])
              if (response.headers[key])
                headers[key] = String(response.headers[key]);
            resolve({ status, headers, body: Buffer.concat(chunks) });
          });
          response.on("error", () =>
            reject(
              new GuardError("navigation_failure", "Shopper read interrupted"),
            ),
          );
        },
      );
      req.on("timeout", () => req.destroy(new Error("deadline")));
      req.on("error", () =>
        reject(
          new GuardError(
            "navigation_failure",
            "Bounded shopper request failed",
          ),
        ),
      );
      this.requests.add(req);
      timer = setTimeout(() => {
        received?.destroy();
        req.destroy();
        reject(
          new GuardError(
            "navigation_failure",
            "Absolute shopper request deadline",
          ),
        );
      }, this.remaining());
      req.end();
    }).finally(() => {
      clearTimeout(timer);
      this.requests.delete(req);
    });
  }
  private async raw() {
    return this.page.evaluate(() => {
      function visible(el: Element) {
        if (
          el.closest(
            'script,style,template,noscript,[hidden],[aria-hidden="true"]',
          )
        )
          return false;
        for (let a: Element | null = el; a; a = a.parentElement) {
          const s = getComputedStyle(a);
          if (
            s.display === "none" ||
            s.visibility === "hidden" ||
            s.opacity === "0" ||
            s.contentVisibility === "hidden"
          )
            return false;
          if (
            a.tagName === "DETAILS" &&
            !a.hasAttribute("open") &&
            !a.querySelector("summary")?.contains(el)
          )
            return false;
        }
        return Array.from(el.getClientRects()).some(
          (r) =>
            r.width > 0 &&
            r.height > 0 &&
            r.right > 0 &&
            r.left < document.documentElement.clientWidth,
        );
      }
      function text(el: Element) {
        const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let n: Node | null;
        const result: string[] = [];
        while ((n = w.nextNode())) {
          if (!n.parentElement || !visible(n.parentElement)) continue;
          const range = document.createRange();
          range.selectNodeContents(n);
          if (
            !Array.from(range.getClientRects()).some(
              (r) => r.width > 0 && r.height > 0,
            )
          )
            continue;
          const value = n.textContent?.replace(/\s+/g, " ").trim();
          if (value) result.push(value);
        }
        return result.join(" ");
      }
      const blocks = Array.from(
        document.querySelectorAll("article,dl,table,section[aria-label]"),
      )
        .filter(visible)
        .map((el) => ({ text: text(el) }))
        .filter((x) => x.text);
      const controls = Array.from(
        document.querySelectorAll(
          "a[href],button,select,input[type=radio],summary,[role=tab]",
        ),
      )
        .filter((el) => visible(el) && !(el as HTMLButtonElement).disabled)
        .map((el) => ({
          role:
            el.getAttribute("role") ||
            (
              {
                A: "link",
                BUTTON: "button",
                SELECT: "select",
                INPUT: "radio",
                SUMMARY: "disclosure",
              } as Record<string, string>
            )[el.tagName] ||
            "control",
          name: el.getAttribute("aria-label") || text(el),
          state:
            el.getAttribute("aria-expanded") ||
            el.getAttribute("aria-selected") ||
            el.getAttribute("aria-pressed") ||
            "",
          href: el.tagName === "A" ? (el as HTMLAnchorElement).href : null,
        }));
      return {
        url: location.href,
        text: text(document.body),
        blocks,
        controls,
      };
    });
  }
  private async capture() {
    if (++this.observations > this.limits.observations)
      throw new GuardError("budget_exhausted", "Observation cap");
    const raw = await this.raw();
    this.fingerprint = hash(JSON.stringify(raw));
    this.handles.clear();
    const candidates = (await this.page
      .locator("a[href],button,select,input[type=radio],summary,[role=tab]")
      .elementHandles()) as ElementHandle<Element>[];
    const kept: {
      reference: string;
      role: string;
      name: string;
      state: string;
    }[] = [];
    // Locate by visible DOM identity, never a caller-supplied selector or fixture recipe.
    const used = new Set<ElementHandle<Element>>();
    const linkByRef = new Map<string, string>();
    for (const c of raw.controls) {
      if (c.href) {
        try {
          const u = this.safeURL(c.href);
          if (!this.transport.document(u)) continue;
        } catch {
          continue;
        }
      }
      if (!c.name || kept.length >= 40) continue;
      let handle: ElementHandle<Element> | undefined;
      for (const candidate of candidates) {
        if (used.has(candidate)) continue;
        if (
          (await candidate.evaluate((el, c) => {
            const name =
              el.getAttribute("aria-label") ||
              el.textContent?.replace(/\s+/g, " ").trim();
            return (
              name === c.name &&
              (el.getAttribute("role") ||
                (
                  {
                    A: "link",
                    BUTTON: "button",
                    SELECT: "select",
                    INPUT: "radio",
                    SUMMARY: "disclosure",
                  } as Record<string, string>
                )[el.tagName] ||
                "control") === c.role
            );
          }, c)) &&
          (await candidate.isVisible())
        ) {
          handle = candidate;
          break;
        }
      }
      if (!handle) continue;
      const reference = "c" + kept.length;
      this.handles.set(reference, handle);
      used.add(handle);
      if (c.href) linkByRef.set(reference, c.href);
      kept.push({
        reference,
        role: c.role,
        name: clip(c.name, 160),
        state: c.state,
      });
    }
    const source = [...raw.blocks, { text: raw.text }];
    const obs: Observation = {
      id: randomUUID(),
      url: raw.url,
      observed_at: new Date().toISOString(),
      document_hash: this.fingerprint,
      text: clip(raw.text, 3000),
      blocks: [],
      controls: kept,
      truncated: Buffer.byteLength(raw.text) > 3000,
    };
    for (const b of source) {
      const block = {
        reference: "b" + obs.blocks.length,
        text: clip(b.text, 2000),
        truncated: Buffer.byteLength(b.text) > 2000,
      };
      if (
        byte({ ...obs, blocks: [...obs.blocks, block] }) <=
        this.limits.frame_bytes
      )
        obs.blocks.push(block);
      else obs.truncated = true;
    }
    while (byte(obs) > this.limits.frame_bytes && obs.controls.length) {
      const last = obs.controls.pop()!;
      this.handles.delete(last.reference);
      obs.truncated = true;
    }
    if (
      byte(obs) > this.limits.frame_bytes ||
      this.bytes + byte(obs) > this.limits.context_bytes
    )
      throw new GuardError("budget_exhausted", "Projection/context byte cap");
    for (const c of obs.controls) {
      const href = linkByRef.get(c.reference);
      if (href) this.allowedLinks.add(href);
    }
    this.bytes += byte(obs);
    this.current = obs;
    this.saved.set(obs.id, obs);
    this.note("observation", obs);
    return obs;
  }
  private async settle() {
    // A fulfilled intercepted fetch can finish outside Playwright's network-idle accounting.
    // Require a bounded quiet interval in rendered content, without site-specific readiness.
    const deadline = Date.now() + this.remaining();
    let previous = "",
      quiet = Date.now();
    while (Date.now() < deadline) {
      if (this.pendingError) throw this.pendingError;
      const current = hash(JSON.stringify(await this.raw()));
      if (this.inflight || current !== previous) {
        previous = current;
        quiet = Date.now();
      }
      if (Date.now() - quiet >= 300) return;
      await this.page.waitForTimeout(50);
    }
    throw new GuardError(
      "navigation_failure",
      "Rendered page did not settle within deadline",
    );
  }
  private async operation(fn: () => Promise<void>) {
    this.pendingError = undefined;
    try {
      await fn();
      await this.settle();
      if (this.pendingError) throw this.pendingError;
      return await this.capture();
    } catch (e) {
      const error =
        this.pendingError ||
        (e instanceof GuardError
          ? e
          : new GuardError(
              "navigation_failure",
              "Navigation or read did not complete",
            ));
      this.lastError = error;
      this.note("tool_error", { kind: error.kind, reason: error.message });
      throw error;
    }
  }
  async open(url: string) {
    this.check(true);
    const u = this.safeURL(url);
    if (url !== this.startURL && !this.allowedLinks.has(u.href))
      throw new GuardError("blocked_request", "Guessed URL denied");
    if (!this.transport.document(u))
      throw new GuardError("blocked_request", "Page path denied");
    this.allowedLinks.add(u.href);
    return this.operation(async () => {
      await this.page.goto(u.href, {
        timeout: this.remaining(),
        waitUntil: "domcontentloaded",
      });
    });
  }
  async observe() {
    this.check();
    if (this.pendingError) {
      this.lastError = this.pendingError;
      throw this.pendingError;
    }
    return this.capture();
  }
  async act(observation: string, reference: string, value?: string) {
    this.check(true);
    if (
      !this.current ||
      observation !== this.current.id ||
      hash(JSON.stringify(await this.raw())) !== this.fingerprint
    )
      throw new GuardError(
        "stale_reference",
        "Document/control reference changed",
      );
    const handle = this.handles.get(reference);
    if (!handle)
      throw new GuardError(
        "invalid_reference",
        "Control is not in current projection",
      );
    const role = this.current.controls.find(
      (c) => c.reference === reference,
    )!.role;
    const allowed = await handle.evaluate(
      (el) =>
        el.tagName === "A" ||
        el.tagName === "SUMMARY" ||
        el.tagName === "SELECT" ||
        el.getAttribute("type") === "radio" ||
        el.getAttribute("role") === "tab" ||
        el.hasAttribute("aria-expanded") ||
        el.hasAttribute("aria-pressed"),
    );
    if (!allowed)
      throw new GuardError(
        "unsupported_control",
        "Only shopper navigation/disclosure/options allowed",
      );
    return this.operation(async () => {
      if (role === "select") {
        if (value === undefined)
          throw new GuardError("invalid_action", "Selection value required");
        await handle.selectOption(
          { label: value },
          { timeout: this.remaining() },
        );
      } else {
        if (value !== undefined)
          throw new GuardError("invalid_action", "Unexpected value");
        await handle.click({ timeout: this.remaining() });
      }
    });
  }
  private cite(c: Citation) {
    const obs = this.saved.get(c.observation);
    const block = obs?.blocks.find((b) => b.reference === c.block);
    if (
      !obs ||
      !block ||
      block.truncated ||
      !c.quote ||
      c.quote.length > 512 ||
      !norm(block.text).includes(norm(c.quote))
    )
      throw new GuardError(
        "invalid_citation",
        "Citation must match a complete saved visible block",
      );
    return block;
  }
  private bound(block: Block) {
    const refs = [...new Set(block.text.match(/\bOR-\d{4}\b/g) || [])];
    if (refs.length !== 1 || refs[0] !== this.goal.order_reference)
      throw new GuardError(
        "wrong_binding",
        "Citation has ambiguous or wrong order binding",
      );
  }
  finish(result: Finish) {
    if (this.finished) throw new GuardError("terminal", "Run already finished");
    const exhausted =
      Date.now() >= this.end ||
      this.calls >= this.limits.tool_calls ||
      this.actions >= this.limits.actions ||
      this.observations > this.limits.observations ||
      this.networkRequests > this.limits.network_requests ||
      this.resourceBytes > this.limits.resource_bytes;
    if (exhausted && result.outcome !== "budget_exhausted")
      throw new GuardError(
        "budget_exhausted",
        "Only bounded budget-stop cleanup is permitted",
      );
    if (
      result.outcome === "budget_exhausted" &&
      !exhausted &&
      this.lastError?.kind !== "budget_exhausted"
    )
      throw new GuardError("invalid_result", "No exhausted budget");
    if (
      byte(result) > 8192 ||
      !Array.isArray(result.unknowns) ||
      typeof result.reason !== "string"
    )
      throw new GuardError("invalid_result", "Bounded result required");
    const permitted = [
      "evidence_found",
      "missing_evidence",
      "wrong_binding",
      "tool_unavailable",
      "blocked_request",
      "budget_exhausted",
    ];
    if (!permitted.includes(result.outcome))
      throw new GuardError("invalid_result", "Unknown outcome");
    const cs = result.citations || [];
    for (const c of cs) this.cite(c);
    if (result.findings) {
      const f = result.findings;
      this.bound(this.cite(f.order));
      if (!f.order.quote.includes(this.goal.order_reference))
        throw new GuardError(
          "wrong_binding",
          "Order quote missing requested reference",
        );
      const item = this.cite(f.item);
      this.bound(item);
      if (
        !f.item.quote.includes(this.goal.variant) ||
        !new RegExp("Quantity\\s*" + this.goal.quantity + "\\b", "i").test(
          f.item.quote,
        )
      )
        throw new GuardError(
          "wrong_binding",
          "Item/quantity binding unsupported",
        );
      if (f.parcel) {
        const block = this.cite(f.parcel);
        this.bound(block);
        const parcels = [
          ...new Set(block.text.match(/\b(?:PK|BX)-\d{4}\b/g) || []),
        ];
        if (parcels.length !== 1 || !f.parcel.quote.includes(parcels[0]))
          throw new GuardError("invalid_citation", "Parcel reference missing");
        const relationship = [...this.saved.values()].some((o) =>
          o.blocks.some(
            (b) =>
              !b.truncated &&
              b.text.includes(parcels[0]) &&
              b.text.includes(this.goal.variant) &&
              new RegExp("Quantity\\s*" + this.goal.quantity + "\\b", "i").test(
                b.text,
              ) &&
              [...new Set(b.text.match(/\bOR-\d{4}\b/g) || [])].join() ===
                this.goal.order_reference,
          ),
        );
        if (!relationship)
          throw new GuardError(
            "wrong_binding",
            "No visible item/order/parcel relationship",
          );
        for (const c of [f.claim, f.event_time])
          if (c) {
            if (
              c.observation !== f.parcel.observation ||
              c.block !== f.parcel.block
            )
              throw new GuardError(
                "wrong_binding",
                "Carrier claim/time must share parcel record block",
              );
            this.cite(c);
          }
        if (f.event_time && result.outcome === "evidence_found") {
          const at = citationTimestamp(block, f.event_time.quote);
          const age = Date.parse(this.goal.as_of) - at;
          if (!Number.isFinite(at) || age < 0 || age > 86400000)
            throw new GuardError(
              "stale_evidence",
              "Event not current at task as_of",
            );
        }
      }
    }
    if (
      result.outcome === "evidence_found" &&
      (!result.findings?.parcel ||
        !result.findings.claim ||
        !result.findings.event_time ||
        result.unknowns.length)
    )
      throw new GuardError(
        "invalid_result",
        "Complete bound citations required",
      );
    if (
      result.outcome === "missing_evidence" &&
      ((!cs.length && !result.findings) || !result.unknowns.length)
    )
      throw new GuardError(
        "invalid_result",
        "Missing evidence needs inspected source and unknowns",
      );
    if (
      ["tool_unavailable", "blocked_request"].includes(result.outcome) &&
      this.lastError?.kind !==
        (result.outcome === "tool_unavailable"
          ? "navigation_failure"
          : "blocked_request")
    )
      throw new GuardError(
        "invalid_result",
        "Operational stop requires actual matching tool error",
      );
    const record = {
      contract: "untrusted-browser-page/v1",
      goal: this.goal,
      result,
      execution_authorized: false,
      counts: {
        actions: this.actions,
        observations: this.observations,
        context_bytes: this.bytes,
        tool_calls: this.calls,
        network_requests: this.networkRequests,
        resource_bytes: this.resourceBytes,
      },
    };
    this.finished = true;
    this.note("finished", record);
    return record;
  }
  failure(error: unknown) {
    const e =
      error instanceof GuardError
        ? error
        : new GuardError("navigation_failure", "Browser operation failed");
    this.lastError = e;
    this.note("tool_error", { kind: e.kind, reason: e.message });
    return { kind: e.kind, reason: e.message };
  }
  features() {
    return {
      goal: this.goal,
      url: this.current?.url || this.startURL,
      observation: this.current,
      remaining: {
        actions: this.limits.actions - this.actions,
        observations: this.limits.observations - this.observations,
        wall_ms: Math.max(0, this.end - Date.now()),
      },
    };
  }
  async close() {
    for (const request of this.requests) request.destroy();
    await this.context?.close();
  }
}
