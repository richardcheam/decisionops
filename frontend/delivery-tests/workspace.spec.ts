import { test, expect, Page } from '@playwright/test';

const username = process.env.COMMERCE_STAFF_USERNAME || 'operator';
const password = process.env.COMMERCE_STAFF_PASSWORD;
if (!password) throw new Error('Set an explicit fictional COMMERCE_STAFF_PASSWORD');
const headers = { Authorization: 'Basic ' + Buffer.from(username + ':' + password).toString('base64') };

async function login(page: Page, path='/') {
  await page.goto(path);
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(password!);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Delivery overview', exact: true })).toBeVisible();
}

async function ask(page: Page, message: string) {
  await page.getByLabel('Message', { exact: true }).fill(message);
  const reply = page.waitForResponse(r => /\/api\/conversations\/[^/]+\/messages$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const response = await reply;
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test('delivery questions expose computed totals and explicit links; Lyon investigation needs exact approval then confirmation', async ({ page, request, browser }) => {
  await login(page);
  const report = await (await request.get('/api/deliveries', { headers })).json();
  expect({ completed: report.completed, open: report.open, overdue: report.overdue, exceptions: report.exceptions }).toEqual({ completed: 3, open: 9, overdue: 8, exceptions: 9 });
  const overview = page.getByRole('region', { name: 'Delivery overview', exact: true });
  await expect(overview.getByText(String(report.completed), { exact: true }).first()).toBeVisible();
  await expect(overview).toContainText('Europe/Paris');
  await expect(overview.getByTestId('report-start')).toHaveAttribute('datetime', report.start);
  await expect(overview.getByTestId('report-end')).toHaveAttribute('datetime', report.end);
  const visibleFreshness = await overview.getByTestId('report-freshness').getAttribute('datetime');
  expect(Math.abs(Date.parse(visibleFreshness!) - Date.parse(report.as_of))).toBeLessThan(15_000);
  const weekly = await ask(page, 'How many deliveries did we complete this week?');
  expect(weekly.report.completed).toBe(report.completed);
  await expect(page.getByRole('log')).toContainText(weekly.text);
  const problems = await ask(page, 'Were there any problems?');
  expect(problems.case_links.length).toBeGreaterThan(0);
  const lyon = (await (await request.get('/api/exceptions', { headers })).json()).find((r: { order_id: string }) => r.order_id === 'DEMO-LYON');
  expect(lyon).toBeTruthy();
  await page.getByRole('log').getByRole('button', { name: `Open ${lyon.order_id} · ${lyon.shipment_id}`, exact: true }).last().click();
  await expect(page.getByTestId('selected-case')).toContainText(lyon.case_id);
  const fixed = await ask(page, 'Fix this');
  expect(fixed.selected_case_id).toBe(lyon.case_id);
  await expect(page.getByText('Investigation complete. Replacement proposal ready for your review.')).toBeVisible({ timeout: 60_000 });
  const branches = page.getByRole('region', { name: 'Specialist branches', exact: true });
  await expect(branches.getByRole('heading', { name: 'shipment specialist', exact: true })).toBeVisible();
  await expect(branches.getByRole('heading', { name: 'order specialist', exact: true })).toBeVisible();
  await page.getByText('Evidence source', { exact: true }).first().click();
  await expect(page.getByText('Observation:', { exact: false }).first()).toBeVisible();
  const detail = async () => (await request.get('/api/cases/' + lyon.case_id, { headers })).json();
  const before = await detail();
  expect(before.approval).toBeNull();
  expect(before.operation).toBeNull();
  const helperContext=await browser.newContext();
  try {
    const helper=await helperContext.newPage();
    await helper.goto('/');
    await helper.getByLabel('Username',{exact:true}).fill('staff');
    await helper.getByLabel('Password',{exact:true}).fill(process.env.COMMERCE_HELPER_PASSWORD!);
    await helper.getByRole('button',{name:'Sign in',exact:true}).click();
    await helper.getByRole('region',{name:'Exception queue'}).getByRole('button').filter({hasText:'DEMO-LYON'}).click();
    await expect(helper.getByText('An approver must review the exact proposal and separately confirm execution.',{exact:true})).toBeVisible();
    await expect(helper.getByRole('button',{name:'Approve replacement',exact:true})).toHaveCount(0);
    await expect(helper.getByRole('button',{name:'Create replacement',exact:true})).toHaveCount(0);
  } finally { await helperContext.close(); }
  await ask(page, "What's still missing?");
  expect((await detail()).proposal.id).toBe(before.proposal.id);
  expect((await detail()).generation).toBe(before.generation);
  await page.getByRole('button', { name: 'Approve replacement', exact: true }).click();
  const approval = page.getByRole('dialog');
  await expect(approval).toContainText(before.proposal.id);
  await expect(approval).toContainText(before.proposal.content_hash);
  await expect(page.getByRole('button', { name: 'Create replacement', exact: true })).toHaveCount(0);
  await approval.getByRole('button', { name: 'Confirm approval', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create replacement', exact: true })).toBeEnabled();
  expect((await detail()).operation).toBeNull();
  const approved = await detail();
  await ask(page, "What's still missing?");
  expect((await detail()).approval.operation_id).toBe(approved.approval.operation_id);
  await page.getByRole('button', { name: 'Create replacement', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm replacement', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Replacement confirmed', exact: true })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: 'artifacts/delivery-results/verified-delivery-workspace.png', fullPage: true });
  await expect(page.getByText('Historical investigation. The replacement is verified by its execution record.', {exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:'Next step'})).not.toContainText('refresh');
  const saved = await detail();
  expect(saved.operation.status).toBe('verified');
  expect(saved.events.filter((e: {kind: string}) => e.kind === 'executed')).toHaveLength(1);
  expect((await request.post('/api/cases/' + lyon.case_id + '/execute', { headers, data: { operation_id: approved.approval.operation_id } })).status()).toBe(409);
  expect((await detail()).operation.operation_id).toBe(saved.operation.operation_id);
});

test('queue selection is independent per browser session and split order asks for a parcel', async ({ page, browser }) => {
  await login(page);
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  try {
    await login(other);
    const queue = page.getByRole('region', { name: 'Exception queue', exact: true });
    await queue.getByRole('button').filter({ hasText: 'DEMO-OVERDUE' }).click();
    await expect(page.getByTestId('selected-case')).toContainText('DEMO-OVERDUE');
    await expect(other.getByTestId('selected-case')).toContainText('No case selected');
    const reply = await ask(other, 'Fix this');
    expect(reply.selected_case_id).toBeNull();
    const ambiguous = await ask(other, 'Fix order DEMO-SPLIT');
    expect(ambiguous.intent).toBe('clarify');
    expect(ambiguous.case_links.length).toBeGreaterThan(1);
    await expect(other.getByTestId('selected-case')).toContainText('No case selected');
    await queue.getByRole('button').filter({ hasText: 'DEMO-CONFLICT' }).click();
    await page.getByText('Carrier timeline and provenance', { exact: true }).click();
    const timeline = page.getByLabel('Carrier timeline', { exact: true });
    await expect(timeline).toContainText('Conflicting verified loss and delivery records require review.');
    await expect(timeline).toContainText('conflicting-delivery');
    await expect(timeline).toContainText('Received');
  } finally {
    await otherContext.close();
  }
});

test('staff can read the workspace but cannot approve or execute or use another actor conversation', async ({ browser, request }) => {
  const helperPassword = process.env.COMMERCE_HELPER_PASSWORD;
  if (!helperPassword) throw new Error('Set fictional COMMERCE_HELPER_PASSWORD for real staff browser acceptance');
  const context = await browser.newContext();
  const page = await context.newPage();
  const staffHeaders = {Authorization:'Basic '+Buffer.from('staff:'+helperPassword).toString('base64')};
  try {
    await page.goto('/');
    await page.getByLabel('Username',{exact:true}).fill('staff');
    await page.getByLabel('Password',{exact:true}).fill(helperPassword);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await expect(page.getByRole('region',{name:'Delivery overview'})).toBeVisible();
    const rows=await (await request.get('/api/cases',{headers})).json();
    const lyon=rows.find((r:{order_id:string})=>r.order_id==='DEMO-LYON');
    await page.getByRole('button').filter({hasText:'DEMO-LYON'}).first().click();
    await expect(page.getByRole('button',{name:'Approve replacement',exact:true})).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Create replacement',exact:true})).toHaveCount(0);
    expect((await request.post('/api/cases/'+lyon.id+'/execute',{headers:staffHeaders,data:{operation_id:'forbidden'}})).status()).toBe(403);
    expect((await request.post('/api/cases/'+lyon.id+'/review',{headers:staffHeaders,data:{generation:1,proposal_id:'forbidden',content_hash:'0'.repeat(64),decision:'approve'}})).status()).toBe(403);
    const conversation=await (await request.post('/api/conversations',{headers,data:{}})).json();
    expect((await request.post('/api/conversations/'+conversation.id+'/messages',{headers:staffHeaders,data:{message:'status',request_id:'other-actor'}})).status()).toBe(404);
    const foreign=process.env.COMMERCE_FOREIGN_CASE_ID;
    if (!foreign) throw new Error('Run isolated commerce_delivery_browser.py to supply a real foreign-store case');
    expect((await request.get('/api/cases/'+foreign,{headers:staffHeaders})).status()).toBe(404);
    const own=await (await request.post('/api/conversations',{headers:staffHeaders,data:{}})).json();
    expect((await request.post('/api/conversations/'+own.id+'/select',{headers:staffHeaders,data:{case_id:foreign}})).status()).toBe(404);
  } finally { await context.close(); }
});


test('rules refresh makes a new valid proposal actionable while old specialist findings remain historical', async ({ page, request }) => {
  const id=process.env.COMMERCE_STALE_CASE_ID;
  if (!id) throw new Error('Run commerce_delivery_browser.py for the persisted stale-evidence fixture');
  await login(page,'/#case='+id);
  const before=await (await request.get('/api/cases/'+id,{headers})).json();
  expect((await ask(page,"What's still missing?")).evidence_current).toBe(false);
  await expect(page.getByRole('button',{name:'Approve replacement',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Check again',exact:true}).click();
  const detail=async()=> (await request.get('/api/cases/'+id,{headers})).json();
  await expect.poll(async()=> (await detail()).generation,{timeout:30_000}).toBeGreaterThan(before.generation);
  await expect(page.getByRole('button',{name:'Approve replacement',exact:true})).toBeEnabled({timeout:30_000});
  const current=await detail();
  expect(current.proposal.id).not.toBe(before.proposal.id);
  expect(current.shipment_investigation.historical).toBe(true);
  expect(current.shipment_investigation.evidence_current).toBe(false);
  await expect(page.getByText('Historical investigation from an earlier case generation. Current order checks and the proposal below govern this case.',{exact:true})).toBeVisible();
  const reply=await ask(page,"What's still missing?");
  expect(reply.evidence_current).toBe(true);expect(reply.proposal_id).toBe(current.proposal.id);
  await page.getByRole('button',{name:'Approve replacement',exact:true}).click();
  await page.getByRole('button',{name:'Confirm approval',exact:true}).click();
  await expect(page.getByRole('button',{name:'Create replacement',exact:true})).toBeEnabled();
  const approved=await detail();
  await ask(page,'status');
  expect((await detail()).approval.operation_id).toBe(approved.approval.operation_id);
});
