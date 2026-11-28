import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { test, expect, Page } from '@playwright/test';

async function runtimeProbe(phase: 'pause' | 'interrupt' | 'verify') {
  if (!process.env.COMMERCE_RUNTIME) return;
  const { stdout } = await promisify(execFile)('python3', ['-B', '../scripts/commerce_runtime_probe.py', phase]);
  if (stdout.trim()) console.log(stdout.trim());
}

const compactDemo = process.env.COMMERCE_COMPACT_DEMO === '1';
const alexOrder = compactDemo ? 'DEMO-OVERDUE' : 'DEMO-FLIGHT';

const staffUsername = process.env.COMMERCE_STAFF_USERNAME || 'operator';
const staffPassword = process.env.COMMERCE_STAFF_PASSWORD!;
const camillePassword = process.env.COMMERCE_CUSTOMER_CAMILLE_PASSWORD!;
const alexPassword = process.env.COMMERCE_CUSTOMER_ALEX_PASSWORD!;
if (!staffPassword || !camillePassword || !alexPassword) throw new Error('Set explicit synthetic browser passwords');
const auth = (user: string, password: string) => ({ Authorization: 'Basic ' + Buffer.from(user + ':' + password).toString('base64') });

async function customerLogin(page: Page, user='camille', password=camillePassword) {
  await page.goto('/customer');
  await page.getByLabel('Customer username', { exact: true }).fill(user);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Your orders', exact: true })).toBeVisible();
}
async function staffLogin(page: Page) {
  await page.goto('/staff');
  await page.getByLabel('Username', { exact: true }).fill(staffUsername);
  await page.getByLabel('Password', { exact: true }).fill(staffPassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Exception queue', exact: true })).toBeVisible();
}
async function customerAsk(page: Page, message: string) {
  await page.getByLabel('Your message', { exact: true }).fill(message);
  const reply = page.waitForResponse(r => /\/customer-api\/conversations\/[^/]+\/messages$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const response = await reply;
  expect(response.ok()).toBeTruthy();
  return response.json();
}
async function staffAsk(page: Page, message: string) {
  await page.getByLabel('Message', { exact: true }).fill(message);
  const reply = page.waitForResponse(r => /\/api\/conversations\/[^/]+\/messages$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  expect((await reply).ok()).toBeTruthy();
}

test('customer Lyon report reaches the same staff case and original conversation shows only verified replacement', async ({ browser, request }) => {
  if (process.env.COMMERCE_RUNTIME) test.setTimeout(180_000);
  const customerContext = await browser.newContext();
  const staffContext = await browser.newContext();
  try {
    const customer = await customerContext.newPage();
    const staff = await staffContext.newPage();
    await customerLogin(customer);
    const help = await customerAsk(customer, 'What can you help me?');
    expect(help.intent).toBe('help');
    await expect(customer.getByRole('log')).toContainText('track a parcel');
    await expect(customer.getByRole('log')).toContainText('report it missing');
    expect((await customerAsk(customer, 'How do I return an item?')).intent).toBe('returns_help');
    await expect(customer.getByRole('log')).toContainText('return instructions');
    await customer.getByRole('button', { name: 'Open order DEMO-LYON', exact: true }).click();
    const summary = await customerAsk(customer, 'What did I order?');
    expect(summary.intent).toBe('order_summary');
    await expect(customer.getByRole('log')).toContainText('DEMO-LYON includes');
    await customerAsk(customer, 'What is my delivery status?');
    await customer.getByRole('button', { name: 'Report a missing parcel', exact: true }).click();
    await expect(customer.getByLabel('Your message', { exact: true })).toHaveValue('My parcel never arrived. Please report it missing.');
    const report = customer.waitForResponse(r => /\/customer-api\/conversations\/[^/]+\/messages$/.test(r.url()) && r.request().method() === 'POST');
    await customer.getByRole('button', { name: 'Send message', exact: true }).click();
    const reply = await report;
    expect(reply.ok()).toBeTruthy();
    const filed = await reply.json();
    expect(filed.case_id).toBeTruthy();
    const conversationID = await customer.getByTestId('customer-conversation').getAttribute('data-conversation-id');
    const caseCard = customer.getByRole('region', { name: 'Your case updates' }).getByRole('article').filter({ hasText: filed.case_id });
    await expect(caseCard).toBeVisible();
    const repeat = await customerAsk(customer, 'My parcel never arrived. Please report it missing.');
    expect(repeat.case_id).toBe(filed.case_id);

    await staffLogin(staff);
    await staffAsk(staff, 'What can you help me?');
    await expect(staff.getByRole('log')).toContainText('delivery totals');
    await expect(staff.getByRole('log')).toContainText('investigate a case');
    const queue = staff.getByRole('region', { name: 'Exception queue', exact: true });
    if (compactDemo) {
      await expect(queue.getByRole('button')).toHaveCount(3);
      await expect(queue).toContainText('DEMO-OVERDUE');
      await expect(queue).toContainText('DEMO-CONFLICT');
      const orders = customer.getByRole('region', { name: 'Your orders' });
      await expect(orders.getByRole('button', { name: 'Open order DEMO-RETURN', exact: true })).toBeVisible();
      await expect(orders.getByRole('button', { name: 'Open order DEMO-CONFLICT', exact: true })).toBeVisible();
    }
    await queue.getByRole('button').filter({ hasText: 'DEMO-LYON' }).click();
    await expect(staff.getByRole('region', { name: 'Selected case', exact: true })
      .getByRole('heading', { name: 'DEMO-LYON', exact: true })).toBeInViewport();
    await expect(staff.getByTestId('selected-case')).toContainText(filed.case_id);
    await expect(staff.getByRole('heading', { name: 'Case history', exact: true }).locator('..')).toContainText('My parcel never arrived. Please report it missing.');
    await staffAsk(staff, 'Which parcels are late?');
    await expect(staff.getByRole('log')).toContainText('overdue parcels in the exception queue');
    await runtimeProbe('pause');
    const investigate = staff.getByRole('button', { name: 'Investigate case', exact: true });
    await expect(investigate).toBeInViewport();
    const started = staff.waitForResponse(response => /\/api\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
    await investigate.click();
    expect((await started).ok()).toBeTruthy();
    await runtimeProbe('interrupt');
    await expect(staff.getByText('Investigation complete. Replacement proposal ready for your review.')).toBeVisible({ timeout: process.env.COMMERCE_RUNTIME ? 90_000 : 60_000 });
    const branches = staff.getByRole('region', { name: 'Specialist branches' });
    await expect(branches.getByRole('heading', { name: 'order specialist' })).toBeVisible();
    await expect(branches.getByRole('heading', { name: 'shipment specialist' })).toBeVisible();
    await branches.getByText('Specialist decisions and read results', { exact: true }).click();
    await expect(branches.getByText('Decision choice', { exact: false }).first()).toBeVisible();
    await expect(branches.getByText('Read result', { exact: false }).first()).toBeVisible();
    const headers = auth(staffUsername, staffPassword);
    const before = await (await request.get('/api/cases/' + filed.case_id, { headers })).json();
    expect(before.approval).toBeNull();
    expect(before.operation).toBeNull();
    await staffAsk(staff, "What's still missing?");
    const afterStatus = await (await request.get('/api/cases/' + filed.case_id, { headers })).json();
    expect(afterStatus.proposal.id).toBe(before.proposal.id);
    expect(afterStatus.generation).toBe(before.generation);
    await staff.getByRole('button', { name: 'Approve replacement', exact: true }).click();
    const approval = staff.getByRole('dialog');
    await expect(approval).toContainText(before.proposal.id);
    await expect(approval).toContainText(before.proposal.content_hash);
    await approval.getByRole('button', { name: 'Confirm approval', exact: true }).click();
    expect((await (await request.get('/api/cases/' + filed.case_id, { headers })).json()).operation).toBeNull();
    const awaitingView = await (await request.get('/customer-api/conversations/' + conversationID, { headers: auth('camille', camillePassword) })).json();
    expect(awaitingView.cases.find((row: { case_id: string }) => row.case_id === filed.case_id).replacement_created).toBe(false);
    await staff.getByRole('button', { name: 'Create replacement', exact: true }).click();
    await staff.getByRole('button', { name: 'Confirm replacement', exact: true }).click();
    await expect(staff.getByRole('heading', { name: 'Replacement confirmed', exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(caseCard).toContainText(/replacement.*created/i, { timeout: 15_000 });
    await expect(caseCard).toContainText(/not.*shipped|hasn.t.*shipped/i);
    await customer.reload();
    await customerLoginAfterReload(customer);
    expect(await customer.getByTestId('customer-conversation').getAttribute('data-conversation-id')).toBe(conversationID);
    await expect(caseCard).toContainText(/replacement.*created/i);
    await customer.screenshot({ path: 'artifacts/customer-results/customer-verified-replacement.png', fullPage: true });
    const view = await (await request.get('/customer-api/conversations/' + conversationID, { headers: auth('camille', camillePassword) })).json();
    expect(view.cases.some((row: { case_id: string; replacement_created: boolean }) => row.case_id === filed.case_id && row.replacement_created)).toBe(true);
    const serialized = JSON.stringify(view);
    for (const internal of ['content_hash', 'compensation_history', 'on_hand', 'reserved_units', 'evidence_current']) expect(serialized).not.toContain(internal);
    const finalCase = await (await request.get('/api/cases/' + filed.case_id, { headers })).json();
    expect((await request.post('/api/cases/' + filed.case_id + '/execute', { headers, data: { operation_id: finalCase.operation.operation_id } })).status()).toBe(409);
    await runtimeProbe('verify');
  } finally { await customerContext.close(); await staffContext.close(); }
});

for (const scenario of [
  {
    order: 'DEMO-OVERDUE', city: 'Lille',
    carrier: 'in transit · Verified record',
  },
  {
    order: 'DEMO-CONFLICT', city: 'Saint-Denis',
    carrier: 'Conflicting verified loss and delivery records require review.',
  },
]) {
  test(`${scenario.city} carrier evidence leaves the case for staff without a replacement`, async ({ page, request }) => {
    await staffLogin(page);
    const queue = page.getByRole('region', { name: 'Exception queue', exact: true });
    await queue.getByRole('button').filter({ hasText: scenario.order }).click();
    const selected = page.getByRole('region', { name: 'Selected case', exact: true });
    await expect(selected.getByRole('heading', { name: scenario.order, exact: true })).toBeVisible();
    await expect(selected).toContainText(scenario.city);
    await selected.getByText('Carrier updates', { exact: true }).click();
    await expect(selected.getByLabel('Carrier timeline')).toContainText(scenario.carrier);

    await selected.getByRole('button', { name: 'Investigate case', exact: true }).click();
    const investigation = selected.getByRole('region', { name: 'Shipment investigation' });
    await expect(investigation.getByText(/^Investigation finished\./)).toBeVisible({ timeout: 60_000 });
    await expect(selected.getByText('We need an up-to-date confirmation from the carrier that the parcel is lost.')).toBeVisible();
    await expect(selected.getByRole('button', { name: 'Approve replacement', exact: true })).toHaveCount(0);
    await expect(selected.getByRole('button', { name: 'Create replacement', exact: true })).toHaveCount(0);

    const headers = auth(staffUsername, staffPassword);
    const cases = await (await request.get('/api/cases', { headers })).json();
    const row = cases.find((candidate: { order_id: string }) => candidate.order_id === scenario.order);
    expect(row).toBeTruthy();
    const detail = await (await request.get('/api/cases/' + row.id, { headers })).json();
    expect(detail.status).toBe('needs_review');
    expect(detail.assessment.facts.loss_confirmed).toBeNull();
    expect(detail.proposal).toBeNull();
    expect(detail.approval).toBeNull();
    expect(detail.operation).toBeNull();
  });
}

test('staff proxy outage offers a safe retry and clears the password', async ({ page }) => {
  await page.route('**/api/session', route => route.fulfill({
    status: 502, contentType: 'text/html', body: '<h1>Bad gateway</h1>',
  }));
  await page.goto('/staff');
  await page.getByLabel('Username', { exact: true }).fill(staffUsername);
  const password = page.getByLabel('Password', { exact: true });
  await password.fill('fictional-proxy-outage-only');
  const signIn = page.getByRole('button', { name: 'Sign in', exact: true });
  await signIn.click();
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('Try again');
  await expect(alert).not.toContainText(/Bad gateway|PostgreSQL|database|migration|JSON/);
  await expect(password).toHaveValue('');

  await page.unroute('**/api/session');
  await password.fill(staffPassword);
  await signIn.click();
  await expect(page.getByRole('region', { name: 'Delivery overview' })).toBeVisible();
});

async function customerLoginAfterReload(page: Page) {
  // Credentials stay in memory, so a page reload asks for authentication again.
  await page.getByLabel('Customer username', { exact: true }).fill('camille');
  await page.getByLabel('Password', { exact: true }).fill(camillePassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Your orders', exact: true })).toBeVisible();
}

test('customer ownership and staff permissions hold, including split shipments in the full fixture', async ({ browser, request }) => {
  const first = await browser.newContext();
  const second = await browser.newContext();
  try {
    const camille = await first.newPage();
    const alex = await second.newPage();
    await customerLogin(camille);
    if (!compactDemo) {
      await camille.getByRole('button', { name: 'Open order DEMO-SPLIT', exact: true }).click();
      const ambiguous = await customerAsk(camille, 'My parcel never arrived. Please report it missing.');
      expect(ambiguous.intent).toBe('clarify');
      expect(ambiguous.case_id).toBeFalsy();
      await expect(camille.getByRole('group', { name: 'Choose a parcel' }).getByRole('button')).toHaveCount(2);
    }
    const identity = await camille.getByTestId('customer-conversation').getAttribute('data-conversation-id');
    const orders = await (await request.get('/customer-api/orders', { headers: auth('camille', camillePassword) })).json();
    const lyon = orders.find((row: { id: string }) => row.id === 'DEMO-LYON');
    const cases = await (await request.get('/api/cases', { headers: auth(staffUsername, staffPassword) })).json();
    const lyonCase = cases.find((row: { order_id: string }) => row.order_id === 'DEMO-LYON');
    expect(lyonCase).toBeTruthy();
    await customerLogin(alex, 'alex', alexPassword);
    await expect(alex.getByRole('region', { name: 'Your orders' })).not.toContainText('DEMO-LYON');
    const other = auth('alex', alexPassword);
    for (const path of ['/customer-api/orders/DEMO-LYON', '/customer-api/parcels/' + lyon.parcels[0].shipment_id, '/customer-api/cases/' + lyonCase.id, '/customer-api/conversations/' + identity]) {
      expect((await request.get(path, { headers: other })).status()).toBe(404);
    }
    expect((await request.post('/customer-api/conversations/' + identity + '/messages', { headers: other, data: { message: 'status', request_id: 'OTHER-REPLAY' } })).status()).toBe(404);
    expect((await request.get('/api/orders', { headers: other })).status()).toBe(401);
    expect((await request.get('/customer-api/orders', { headers: auth(staffUsername, staffPassword) })).status()).toBe(401);
    const helper = auth('staff', process.env.COMMERCE_HELPER_PASSWORD!);
    expect((await request.post('/api/cases/' + lyonCase.id + '/review', { headers: helper, data: { generation: 1, proposal_id: 'guessed', content_hash: '0'.repeat(64), decision: 'approve' } })).status()).toBe(403);
    expect((await request.post('/api/cases/' + lyonCase.id + '/execute', { headers: helper, data: { operation_id: 'guessed' } })).status()).toBe(403);
  } finally { await first.close(); await second.close(); }
});

test('missing selection and ambiguous references require a fresh parcel choice before reporting', async ({ page, request }) => {
  await page.goto('/staff');
  await expect(page.getByRole('link', { name: 'Customer help', exact: true })).toHaveAttribute('href', '/customer');
  await customerLogin(page);
  const initial = await customerAsk(page, 'My parcel never arrived. Please report it missing.');
  expect(initial.intent).toBe('clarify');
  expect(initial.case_id).toBeFalsy();
  await page.getByRole('button', { name: 'Open order DEMO-LYON', exact: true }).click();
  const question = await customerAsk(page, 'Can you check whether my parcel never arrived?');
  expect(question.intent).not.toBe('report_nonreceipt');
  expect(question.case_id).toBeFalsy();
  if (!compactDemo) {
    const ambiguous = await customerAsk(page, 'Please report DEMO-LYON or DEMO-SPLIT missing.');
    expect(ambiguous.intent).toBe('clarify');
    expect(ambiguous.case_id).toBeFalsy();
    const unresolved = await customerAsk(page, 'Please report it missing.');
    expect(unresolved.intent).toBe('clarify');
    expect(unresolved.case_id).toBeFalsy();
    await page.getByRole('button', { name: 'Open order DEMO-LYON', exact: true }).click();
    const splitReference = await customerAsk(page, 'Please report DEMO-SPLIT missing.');
    expect(splitReference.intent).toBe('clarify');
    expect(splitReference.case_id).toBeFalsy();
    const stillUnresolved = await customerAsk(page, 'Please report it missing.');
    expect(stillUnresolved.intent).toBe('clarify');
    expect(stillUnresolved.case_id).toBeFalsy();
  }
  const camilleID = await page.getByTestId('customer-conversation').getAttribute('data-conversation-id');
  const alex = auth('alex', alexPassword);
  const owned = await (await request.post('/customer-api/conversations', { headers: alex, data: {} })).json();
  expect((await request.post('/customer-api/conversations/' + owned.id + '/select', { headers: alex,
    data: { order_id: 'DEMO-LYON', shipment_id: 'PARCEL-DEMO-LYON' } })).status()).toBe(404);
  expect((await request.post('/customer-api/conversations/' + owned.id + '/select', { headers: alex,
    data: { order_id: alexOrder, shipment_id: 'PARCEL-DEMO-LYON' } })).status()).toBe(404);
  expect((await request.post('/customer-api/conversations/' + camilleID + '/select', { headers: alex,
    data: { order_id: alexOrder, shipment_id: 'PARCEL-' + alexOrder } })).status()).toBe(404);
});

test('late customer responses cannot replace another account’s conversation after sign-out', async ({ page }) => {
  await customerLogin(page);
  const original = await page.getByTestId('customer-conversation').getAttribute('data-conversation-id');
  let releaseResponse!: () => void;
  let selectionObserved!: () => void;
  let responseFinished!: () => void;
  const held = new Promise<void>(resolve => { releaseResponse = resolve; });
  const observed = new Promise<void>(resolve => { selectionObserved = resolve; });
  const finished = new Promise<void>(resolve => { responseFinished = resolve; });
  await page.route('**/customer-api/conversations/*/select', async route => {
    const response = await route.fetch();
    selectionObserved();
    await held;
    await route.fulfill({ response });
    responseFinished();
  });
  try {
    await page.getByRole('button', { name: 'Open order DEMO-LYON', exact: true }).click();
    await observed;
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByLabel('Customer username', { exact: true }).fill('alex');
    await page.getByLabel('Password', { exact: true }).fill(alexPassword);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Your orders' })).toContainText(alexOrder);
    const alexConversation = await page.getByTestId('customer-conversation').getAttribute('data-conversation-id');
    expect(alexConversation).not.toBe(original);
    const delayed = page.waitForResponse(response => /\/customer-api\/conversations\/[^/]+\/select$/.test(response.url()));
    releaseResponse();
    await finished;
    await (await delayed).finished();
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByTestId('customer-conversation')).toHaveAttribute('data-conversation-id', alexConversation!);
    await expect(page.getByRole('region', { name: 'Your delivery conversation' })).not.toContainText('DEMO-LYON');
  } finally { releaseResponse(); }
});

test('temporary conversation read failure keeps the saved conversation for retry', async ({ page }) => {
  await customerLogin(page);
  const original = await page.getByTestId('customer-conversation').getAttribute('data-conversation-id');
  await page.reload();
  let created = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && /\/customer-api\/conversations$/.test(request.url())) created++;
  });
  await page.route('**/customer-api/conversations/' + original, route => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic temporary outage' }),
  }));
  await page.getByLabel('Customer username', { exact: true }).fill('camille');
  await page.getByLabel('Password', { exact: true }).fill(camillePassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Please try again');
  expect(created).toBe(0);
  await page.unroute('**/customer-api/conversations/' + original);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByTestId('customer-conversation')).toHaveAttribute('data-conversation-id', original!);
});

if (compactDemo) {
  test('a customer selects one return item and staff authorize the same case', async ({ browser }) => {
    const customerContext = await browser.newContext();
    const staffContext = await browser.newContext();
    try {
      const customer = await customerContext.newPage();
      const staff = await staffContext.newPage();
      await customerLogin(customer);
      await customer.getByRole('button', { name: 'Open order DEMO-RETURN', exact: true }).click();
      await customer.getByRole('button', { name: 'Check return eligibility' }).click();
      const eligibility = customer.getByRole('region', { name: 'Return eligibility' });
      await expect(eligibility).toContainText('Choose one item');
      await expect(eligibility.getByRole('button', { name: 'Start return' })).toHaveCount(0);
      await eligibility.getByLabel('Return item').selectOption('return-tote');
      await expect(eligibility.getByRole('button', { name: 'Start return' })).toBeVisible();
      const ambiguous = await customerAsk(customer, 'Can I return something from DEMO-RETURN and PARCEL-DEMO-LYON?');
      expect(ambiguous.intent).toBe('clarify');
      await expect(eligibility).toHaveCount(0);
      await customer.getByRole('button', { name: 'Check return eligibility' }).click();
      await eligibility.getByLabel('Return item').selectOption('return-tote');
      await eligibility.getByRole('button', { name: 'Start return' }).click();
      const updates = customer.getByRole('region', { name: 'Your case updates' });
      const caseCard = updates.getByRole('article').filter({ hasText: 'DEMO-RETURN' });
      await expect(caseCard).toBeVisible();
      const reference = (await caseCard.getByRole('heading').innerText()).replace(/^Return /, '');

      await staffLogin(staff);
      await staff.getByRole('button', { name: 'Return cases', exact: true }).click();
      await staff.getByRole('region', { name: 'Return cases' }).getByRole('button', { name: /DEMO-RETURN · return-tote/ }).click();
      await expect(staff.getByRole('region', { name: 'Selected return' })).toContainText(reference);
      await staff.getByRole('button', { name: 'Investigate return' }).click();
      await staff.getByRole('button', { name: 'Approve return', exact: true }).click();
      await staff.getByRole('dialog').getByRole('button', { name: /confirm return approval/i }).click();
      await expect(caseCard.getByText(/^Authorization RETURN-AUTH-/)).toHaveCount(0);
      await staff.getByRole('button', { name: 'Authorize return', exact: true }).click();
      await staff.getByRole('dialog').getByRole('button', { name: /confirm return authorization/i }).click();
      await expect(caseCard).toContainText('The shop authorized your return.');

      await customer.getByRole('button', { name: 'Open order DEMO-RETURN-EXPIRED', exact: true }).click();
      await customer.getByRole('button', { name: 'Check return eligibility' }).click();
      await expect(eligibility).toContainText('The return window for this item has closed.');
      await expect(eligibility.getByRole('button', { name: 'Start return' })).toHaveCount(0);
    } finally {
      await customerContext.close();
      await staffContext.close();
    }
  });
}

if (compactDemo) {
  test('staff approve and separately relink a verified catalog image', async ({ page, request }) => {
    await staffLogin(page);
    await page.getByRole('button', { name: 'Catalog', exact: true }).click();
    const cases = page.getByRole('region', { name: 'Catalog cases' });
    const selected = page.getByRole('region', { name: 'Selected catalog case' });
    await cases.getByRole('button', { name: /TOTE-BLUE/ }).click();
    await expect(selected.getByAltText('Current listing image')).toBeVisible();
    await selected.getByRole('button', { name: 'Investigate image' }).click();
    await expect(selected.getByAltText('Proposed listing image')).toBeVisible();
    await selected.getByRole('button', { name: 'Approve image change' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('tote-red');
    await expect(dialog).toContainText('tote-blue');
    await dialog.getByRole('button', { name: 'Confirm approval' }).click();
    const headers = auth(staffUsername, staffPassword);
    const approved = await (await request.get('/api/catalog/TOTE-BLUE', { headers })).json();
    expect(approved.current_image_id).toBe('tote-red');
    await selected.getByRole('button', { name: 'Relink image' }).click();
    await dialog.getByRole('button', { name: 'Confirm relink' }).click();
    await expect(selected).toContainText('Verified saved image tote-blue');
    const approvedBody = { proposal_hash: approved.proposal_hash };
    const replay = await request.post('/api/catalog/TOTE-BLUE/confirm', { headers, data: approvedBody });
    expect(replay.ok()).toBeTruthy();
    expect((await replay.json()).receipt.saved_image_id).toBe('tote-blue');

    await cases.getByRole('button', { name: /MUG-WHITE/ }).click();
    await selected.getByRole('button', { name: 'Investigate image' }).click();
    await expect(selected).toContainText(/conflict|disagree/i);
    await expect(selected.getByRole('button', { name: 'Approve image change' })).toHaveCount(0);
  });
}
