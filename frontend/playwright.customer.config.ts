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
    launchOptions: { executablePath: process.env.COMMERCE_BROWSER_PATH, args: ['--no-sandbox'] },
  },
});
