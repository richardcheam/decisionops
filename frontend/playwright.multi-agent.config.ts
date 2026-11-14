import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Run only against the isolated fictional multi-agent project and its fresh data.
export default defineConfig({
  ...base,
  testDir: './multi-agent-tests',
  outputDir: './artifacts/multi-agent-results',
  reporter: [['list'], ['json', { outputFile: './artifacts/multi-agent-report.json' }]],
  use: { ...base.use, baseURL: process.env.COMMERCE_WEB_URL || 'http://127.0.0.1:8123' },
});
