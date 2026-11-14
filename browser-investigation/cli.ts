/** Private bounded JSONL bridge. No provider, expected answers or staff imports. */
import { chromium } from "@playwright/test";
import { BrowserInvestigation } from "./harness.ts";
import { shopperTransport } from "./permissions.ts";
import fs from "node:fs";
async function main() {
  const limits = JSON.parse(
    fs.readFileSync("/source/browser-investigation/controller.json", "utf8"),
  );
  const browser = await chromium.launch({ headless: true });
  let h: BrowserInvestigation | undefined,
    emitted = 0,
    total = 0,
    buffer = Buffer.alloc(0),
    busy = Promise.resolve(),
    closed = false;
  const end = setTimeout(() => void cleanup(2), 660000);
  async function cleanup(code = 0) {
    if (closed) return;
    closed = true;
    clearTimeout(end);
    await h?.close();
    await browser.close();
    process.exit(code);
  }
  process.on("SIGTERM", () => void cleanup(2));
  process.on("SIGINT", () => void cleanup(2));
  function emit(value: unknown) {
    const line = JSON.stringify(value) + "\n";
    emitted += Buffer.byteLength(line);
    if (Buffer.byteLength(line) > 131072 || emitted > 2 * 1024 * 1024)
      throw Error("Bridge output cap");
    process.stdout.write(line);
  }
  async function command(message: any) {
    if (closed) return;
    try {
      if (message.op === "start") {
        if (h) throw Error("Existing browser run must be closed");
        h = await new BrowserInvestigation(
          browser,
          message.goal,
          message.url,
          shopperTransport(["http://127.0.0.1:8096", "http://127.0.0.1:8097"]),
          limits,
        ).init();
        const observation = await h.open(message.url);
        emit({ ok: true, observation, features: h.features() });
      } else if (message.op === "close") {
        const audit = h?.audit;
        await h?.close();
        h = undefined;
        emit({ ok: true, audit });
      } else {
        if (!h) throw Error("No active browser run");
        if (message.op === "finish")
          emit({ ok: true, result: h.finish(message.result) });
        else if (
          message.op === "observe" ||
          message.op === "act" ||
          message.op === "open"
        ) {
          const observation =
            message.op === "observe"
              ? await h.observe()
              : message.op === "open"
                ? await h.open(message.url)
                : await h.act(
                    message.observation,
                    message.reference,
                    message.value,
                  );
          emit({ ok: true, observation, features: h.features() });
        } else throw Error("Unknown bridge operation");
      }
    } catch (error) {
      emit({
        ok: false,
        error: h?.failure(error) || {
          kind: "bridge_failure",
          reason: "Bridge rejected command",
        },
      });
    }
  }
  process.stdin.on("data", (data: Buffer) => {
    total += data.length;
    if (total > 1024 * 1024 || buffer.length + data.length > 131072) {
      void cleanup(2);
      return;
    }
    buffer = Buffer.concat([buffer, data]);
    for (let newline; (newline = buffer.indexOf(10)) >= 0;) {
      const frame = buffer.subarray(0, newline);
      buffer = buffer.subarray(newline + 1);
      if (frame.length > 65536) {
        void cleanup(2);
        return;
      }
      busy = busy.then(async () => {
        try {
          await command(JSON.parse(frame.toString("utf8")));
        } catch {
          await cleanup(2);
        }
      });
    }
  });
  process.stdin.on("end", () => void busy.then(() => cleanup()));
}
void main();
