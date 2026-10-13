import { test, expect, Page } from '@playwright/test';

test('proxy outage is actionable and does not retain the password field', async ({ page }) => {
  await page.route('**/api/session', route => route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>Bad gateway</h1>' }));
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill('operator');
  await page.getByLabel('Password', { exact: true }).fill('fictional-test-secret');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Try again');
  await expect(page.getByRole('alert')).not.toContainText(/PostgreSQL|database|migration|JSON/);
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
});

async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill(process.env.COMMERCE_STAFF_USERNAME || 'operator');
  try {
    await page.getByLabel('Password', { exact: true }).fill(process.env.COMMERCE_STAFF_PASSWORD!);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  } finally {
    // Clear before failure diagnostics even when the click itself times out.
    // A closed page cannot retain a DOM input and may reject this cleanup call.
    await page.getByLabel('Password', { exact: true }).evaluateAll(nodes => nodes.forEach(node => (node as HTMLInputElement).value = '')).catch(() => undefined);
  }
  await expect(page.getByRole('heading', { name: 'Lost shipment reviews' })).toBeVisible();
}

test('superseded dialog cannot approve; fresh review records one verified replacement', async ({ page, request }) => {
  await login(page);
  await page.getByLabel('Order', { exact: true }).selectOption('ORD-1042');
  const opened = page.waitForResponse(r => r.url().endsWith('/api/cases') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Start review', exact: true }).click();
  const caseId = (await (await opened).json()).id;
  await expect(page.getByRole('button', { name: 'Approve replacement', exact: true })).toBeEnabled({ timeout: 20_000 });
  await expect(page.getByText('Blue shirt · Size M × 1').first()).toBeVisible();
  await page.getByRole('button', { name: 'Approve replacement', exact: true }).click();
  const headers = { Authorization: 'Basic ' + Buffer.from((process.env.COMMERCE_STAFF_USERNAME || 'operator') + ':' + process.env.COMMERCE_STAFF_PASSWORD).toString('base64') };
  expect((await request.post('/api/cases/' + caseId + '/investigate', { headers, data: {} })).status()).toBe(202);
  await expect.poll(async () => (await (await request.get('/api/cases/' + caseId, { headers })).json()).generation, { timeout: 20_000 }).toBe(2);
  await page.getByRole('button', { name: 'Confirm approval', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  expect((await (await request.get('/api/cases/' + caseId, { headers })).json()).status).toBe('awaiting_review');
  await page.getByRole('button', { name: 'Refresh case', exact: true }).click();
  await page.getByRole('button', { name: 'Approve replacement', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm approval', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create replacement', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Create replacement', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm replacement', exact: true }).click();
  await expect.poll(async () => (await (await request.get('/api/cases/' + caseId, { headers })).json()).operation?.status, { timeout: 20_000 }).toBe('verified');
  await expect(page.getByText('Replacement created', { exact: true }).first()).toBeVisible();
  expect(await page.locator('body').innerText()).not.toMatch(/Review generation|Rules mode|postgres-|source_version|OP-/);
  await page.screenshot({ path: 'artifacts/results/verified-workspace.png', fullPage: true });
  const result = await (await request.get('/api/cases/' + caseId, { headers })).json();
  expect(result.events.filter((e: { kind: string }) => e.kind === 'executed')).toHaveLength(1);
  expect(await page.evaluate(() => Object.keys(localStorage))).toHaveLength(0);
});

test('incomplete compensation history remains unknown without an approval control', async ({ page }) => {
  await login(page);
  await page.getByLabel('Order', { exact: true }).selectOption('ORD-HISTORY');
  await page.getByRole('button', { name: 'Start review', exact: true }).click();
  await expect(page.getByText('Needs more information', { exact: true }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('We need the full refund and replacement history before continuing.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve replacement', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Ask for help', exact: true })).toBeVisible();
  await page.screenshot({ path: 'artifacts/results/missing-history-evidence.png', fullPage: true });
});

test('case selection stays fixed while an action response is pending', async ({ page }) => {
  await login(page);
  await page.getByLabel('Order', { exact: true }).selectOption('ORD-POLICY');
  await page.getByRole('button', { name: 'Start review', exact: true }).click();
  await page.getByLabel('Order', { exact: true }).selectOption('ORD-PARTIAL');
  await page.getByRole('button', { name: 'Start review', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Check again', exact: true })).toBeEnabled({ timeout: 20_000 });
  let release!: () => void;
  let entered!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const intercepted = new Promise<void>(resolve => { entered = resolve; });
  await page.route('**/api/cases/*/investigate', async route => {
    entered();
    await held;
    await route.fulfill({ status: 202, contentType: 'application/json', body: '{}' });
  });
  await page.getByRole('button', { name: 'Check again', exact: true }).click();
  await intercepted;
  try {
    await expect(page.locator('.case-row').filter({ hasText: 'ORD-POLICY' })).toBeDisabled();
  } finally {
    release();
  }
});

test('out of stock explains a failed check without calling it missing information', async ({ page }) => {
  await login(page);
  await page.getByLabel('Order', { exact: true }).selectOption('ORD-STOCK');
  await page.getByRole('button', { name: 'Start review', exact: true }).click();
  await expect(page.getByText('Replacement unavailable', { exact: true }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('There are not enough items available for this replacement.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve replacement', exact: true })).toHaveCount(0);
  await expect(page.getByText('Red shirt · Size M × 1').first()).toBeVisible();
});


test('failed sign-in click clears the credential before diagnostics', async ({ page }) => {
  const password = process.env.COMMERCE_STAFF_PASSWORD;
  process.env.COMMERCE_STAFF_PASSWORD = 'fictional-timeout-test-secret';
  await page.addInitScript(() => {
    new MutationObserver(() => {
      for (const button of document.querySelectorAll('button')) {
        if (button.textContent === 'Sign in') button.disabled = true;
      }
    }).observe(document, { childList: true, subtree: true });
  });
  page.setDefaultTimeout(500);
  try {
    await expect(login(page)).rejects.toThrow();
    await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
  } finally {
    process.env.COMMERCE_STAFF_PASSWORD = password;
  }
});
