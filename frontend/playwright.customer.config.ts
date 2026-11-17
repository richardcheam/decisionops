import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testDir: './customer-tests',
  outputDir: './artifacts/customer-results',
  reporter: [['list'], ['json', { outputFile: './artifacts/customer-report.json' }]],
  timeout: 90_000,
  use: {
    ...base.use,
    baseURL: process.env.COMMERCE_WEB_URL || 'http://127.0.0.1:8167',
    launchOptions: { executablePath: process.env.COMMERCE_BROWSER_PATH, args: ['--no-sandbox'] },
  },
});
