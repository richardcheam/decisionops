import { defineConfig } from "@playwright/test";
import path from "node:path";
import base from "./playwright.config";
const artifacts = path.resolve(process.env.BROWSER_ARTIFACT_DIR || "artifacts");
export default defineConfig({
  ...base,
  testDir: "./browser-tests",
  outputDir: artifacts + "/results",
  reporter: [
    ["list"],
    ["json", { outputFile: artifacts + "/browser-report.json" }],
  ],
  timeout: 90000,
  use: { ...base.use, baseURL: "http://127.0.0.1:8096" },
});
