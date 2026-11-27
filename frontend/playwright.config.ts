import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './customer-tests',
  outputDir: './artifacts/results',
  workers: 1,
  forbidOnly: true,
  reporter: [['list'], ['json', { outputFile: './artifacts/browser-report.json' }]],
  timeout: 45_000,
  use: {
    actionTimeout: 10_000,
    baseURL: process.env.COMMERCE_WEB_URL || 'http://127.0.0.1:8133',
    // Credentials live in request headers: never export a browser trace.
    trace: 'off',
    screenshot: 'only-on-failure',
  },
});
