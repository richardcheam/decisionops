import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Requires the isolated delivery demo seed, API and worker (mock-specialists).
export default defineConfig({
  ...base,
  testDir: './delivery-tests',
  outputDir: './artifacts/delivery-results',
  reporter: [['list'], ['json', { outputFile: './artifacts/delivery-report.json' }]],
  use: { ...base.use, baseURL: process.env.COMMERCE_WEB_URL || 'http://127.0.0.1:8155', launchOptions: { executablePath: process.env.COMMERCE_BROWSER_PATH, args: ['--no-sandbox'] } },
});
