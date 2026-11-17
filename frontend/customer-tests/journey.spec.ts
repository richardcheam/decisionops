import { test, expect, Page } from '@playwright/test';

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
  const customerContext = await browser.newContext();
  const staffContext = await browser.newContext();
  try {
    const customer = await customerContext.newPage();
    const staff = await staffContext.newPage();
    await customerLogin(customer);
    await customer.getByRole('button', { name: 'Open order DEMO-LYON', exact: true }).click();
    await customerAsk(customer, 'What is my delivery status?');
    const filed = await customerAsk(customer, 'My parcel never arrived. Please report it missing.');
    expect(filed.case_id).toBeTruthy();
    const conversationID = await customer.getByTestId('customer-conversation').getAttribute('data-conversation-id');
    const caseCard = customer.getByRole('region', { name: 'Your case updates' }).getByRole('article').filter({ hasText: filed.case_id });
    await expect(caseCard).toBeVisible();
    const repeat = await customerAsk(customer, 'My parcel never arrived. Please report it missing.');
    expect(repeat.case_id).toBe(filed.case_id);

    await staff.goto('/staff');
    await staff.getByLabel('Username', { exact: true }).fill(staffUsername);
    await staff.getByLabel('Password', { exact: true }).fill(staffPassword);
    await staff.getByRole('button', { name: 'Sign in', exact: true }).click();
    await staff.getByRole('region', { name: 'Exception queue', exact: true }).getByRole('button').filter({ hasText: 'DEMO-LYON' }).click();
    await expect(staff.getByTestId('selected-case')).toContainText(filed.case_id);
    await expect(staff.getByRole('heading', { name: 'Case history', exact: true }).locator('..')).toContainText('My parcel never arrived. Please report it missing.');
    await staffAsk(staff, 'Fix this');
    await expect(staff.getByText('Investigation complete. Replacement proposal ready for your review.')).toBeVisible({ timeout: 60_000 });
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
  } finally { await customerContext.close(); await staffContext.close(); }
});

async function customerLoginAfterReload(page: Page) {
  // Credentials stay in memory, so a page reload asks for authentication again.
  await page.getByLabel('Customer username', { exact: true }).fill('camille');
  await page.getByLabel('Password', { exact: true }).fill(camillePassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Your orders', exact: true })).toBeVisible();
}

test('split shipment needs parcel selection and second customer cannot cross ownership or staff permissions', async ({ browser, request }) => {
  const first = await browser.newContext();
  const second = await browser.newContext();
  try {
    const camille = await first.newPage();
    const alex = await second.newPage();
    await customerLogin(camille);
    await camille.getByRole('button', { name: 'Open order DEMO-SPLIT', exact: true }).click();
    const ambiguous = await customerAsk(camille, 'My parcel never arrived. Please report it missing.');
    expect(ambiguous.intent).toBe('clarify');
    expect(ambiguous.case_id).toBeFalsy();
    await expect(camille.getByRole('group', { name: 'Choose a parcel' }).getByRole('button')).toHaveCount(2);
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
  const camilleID = await page.getByTestId('customer-conversation').getAttribute('data-conversation-id');
  const alex = auth('alex', alexPassword);
  const owned = await (await request.post('/customer-api/conversations', { headers: alex, data: {} })).json();
  expect((await request.post('/customer-api/conversations/' + owned.id + '/select', { headers: alex,
    data: { order_id: 'DEMO-LYON', shipment_id: 'PARCEL-DEMO-LYON' } })).status()).toBe(404);
  expect((await request.post('/customer-api/conversations/' + owned.id + '/select', { headers: alex,
    data: { order_id: 'DEMO-FLIGHT', shipment_id: 'PARCEL-DEMO-LYON' } })).status()).toBe(404);
  expect((await request.post('/customer-api/conversations/' + camilleID + '/select', { headers: alex,
    data: { order_id: 'DEMO-FLIGHT', shipment_id: 'PARCEL-DEMO-FLIGHT' } })).status()).toBe(404);
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
    await expect(page.getByRole('region', { name: 'Your orders' })).toContainText('DEMO-FLIGHT');
    const alexConversation = await page.getByTestId('customer-conversation').getAttribute('data-conversation-id');
    expect(alexConversation).not.toBe(original);
    const delayed = page.waitForResponse(response => /\/customer-api\/conversations\/[^/]+\/select$/.test(response.url()));
    releaseResponse();
    await finished;
    await (await delayed).finished();
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByTestId('customer-conversation')).toHaveAttribute('data-conversation-id', alexConversation!);
    await expect(page.getByRole('region', { name: 'Your delivery conversation' })).not.toContainText('Selected order: DEMO-LYON');
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
