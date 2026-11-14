import { defineConfig } from '@playwright/test';
import base from './playwright.config';
// Staff suite uses its own fictional schema; legacy tests keep their original fixture.
export default defineConfig({...base, testDir: './staff-tests'});
