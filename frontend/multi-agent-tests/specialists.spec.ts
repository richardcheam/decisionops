import { test, expect, Page, APIRequestContext } from '@playwright/test';

const username = process.env.COMMERCE_STAFF_USERNAME || 'visitor';
const password = process.env.COMMERCE_MULTI_AGENT_PASSWORD || process.env.COMMERCE_STAFF_PASSWORD;
if (!password) throw new Error('Set an explicit fictional COMMERCE_MULTI_AGENT_PASSWORD');
const headers = { Authorization: 'Basic ' + Buffer.from(username + ':' + password).toString('base64') };

async function openInvestigation(page: Page, request: APIRequestContext, order: string, variant = 'shirt-blue-M') {
  const response = await request.post('/api/cases', {
    headers, data: { order_id: order, shipment_id: order.replace('ORD-', 'SHIP-'), items: { [variant]: 1 } },
  });
  expect(response.status()).toBe(201);
  const opened = await response.json();
  await page.goto('/#case=' + opened.id);
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(password!);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Shipment report', { exact: true }).fill('Customer reports the parcel missing. Please investigate the saved evidence.');
  const pending=page.waitForResponse(r=>r.url().endsWith('/shipment-investigation') && r.request().method()==='POST');
  await page.getByRole('button', { name: 'Investigate shipment', exact: true }).dblclick();
  const admitted=await pending;expect(admitted.status()).toBe(202);
  const body=admitted.request().postDataJSON();const run=(await admitted.json()).run_id;
  for(const request_id of [body.request_id,body.request_id+'-coalesced']) {
    const retry=await request.post('/api/cases/'+opened.id+'/shipment-investigation',{headers,data:{...body,request_id}});
    expect(retry.status()).toBe(202);expect((await retry.json()).run_id).toBe(run);
  }
  const stale=await request.post('/api/cases/'+opened.id+'/shipment-investigation',{headers,data:{...body,request_id:body.request_id+'-stale',expected_generation:99999}});
  expect(stale.status()).toBe(409);
  await page.reload();
  await page.getByLabel('Username',{exact:true}).fill(username);
  await page.getByLabel('Password',{exact:true}).fill(password!);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByText('Mocked specialists. No paid calls.', { exact: true })).toBeVisible();
  return opened.id as string;
}

async function result(request: APIRequestContext, id: string) {
  return (await request.get('/api/cases/' + id, { headers })).json();
}

test('specialist choices and sources remain visible before exact approval and execution', async ({ page, request }) => {
  const id = await openInvestigation(page, request, 'ORD-1042');
  await expect(page.getByText('Investigation complete. Replacement proposal ready for your review.')).toBeVisible({ timeout: 45_000 });
  const branches = page.getByRole('region', { name: 'Specialist branches', exact: true });
  await expect(branches.getByText('Branch status:', { exact: false }).first()).toBeVisible();
  await branches.getByText('Specialist decisions and read results', { exact: true }).click();
  await expect(branches.getByText('Decision choice', { exact: false }).first()).toBeVisible();
  await expect(branches.getByText('Read result', { exact: false }).first()).toBeVisible();
  await page.getByText('Evidence source', { exact: true }).first().click();
  await expect(page.getByText('Declared record scope:', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('This investigation consulted database records, not browser pages.').first()).toBeVisible();
  await page.screenshot({path:'artifacts/multi-agent-results/specialists-proposal.png',fullPage:true});
  const before = await result(request, id);
  expect(before.shipment_investigation.mode).toBe('mock_specialists');
  expect(before.shipment_investigation.specialists.length).toBeGreaterThan(1);
  expect(before.approval).toBeNull();
  expect(before.operation).toBeNull();
  expect((await request.post('/api/cases/' + id + '/execute', { headers, data: { operation_id: 'unapproved' } })).status()).toBe(409);
  await page.getByRole('button', { name: 'Approve replacement', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create replacement', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Confirm approval', exact: true }).click();
  await page.getByRole('button', { name: 'Create replacement', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm replacement', exact: true }).click();
  await expect.poll(async () => (await result(request, id)).operation?.status, { timeout: 20_000 }).toBe('verified');
  expect((await result(request, id)).events.filter((event: { kind: string }) => event.kind === 'executed')).toHaveLength(1);
});

test('incomplete history preserves other branch results and offers no approval', async ({ page, request }) => {
  const id = await openInvestigation(page, request, 'ORD-HISTORY');
  await expect(page.getByText('Investigation finished.', { exact: false })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText('We need the full refund and replacement history before continuing.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve replacement', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Create replacement', exact: true })).toHaveCount(0);
  await page.screenshot({path:'artifacts/multi-agent-results/specialists-incomplete.png',fullPage:true});
  const saved = await result(request, id);
  expect(saved.assessment.facts.no_previous_compensation).toBeNull();
  expect(saved.shipment_investigation.evidence.some((row: { value: boolean | null }) => row.value === true)).toBe(true);
  expect(saved.proposal).toBeNull();
  expect(saved.operation).toBeNull();
});

test('stock failure remains a failed policy condition', async ({ page, request }) => {
  const id = await openInvestigation(page, request, 'ORD-STOCK', 'shirt-red-M');
  await expect(page.getByText('Investigation finished.', { exact: false })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText('There are not enough items available for this replacement.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve replacement', exact: true })).toHaveCount(0);
  const saved = await result(request, id);
  expect(saved.assessment.facts.stock_available).toBe(false);
  expect(saved.proposal).toBeNull();
  expect(saved.operation).toBeNull();
});
