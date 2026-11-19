import {test,expect,Page} from '@playwright/test';
async function signIn(page:Page) {
  await page.goto('/'+new URL(page.url().startsWith('http') ? page.url() : 'http://localhost').hash);
  await page.getByLabel('Username',{exact:true}).fill(process.env.COMMERCE_STAFF_USERNAME || 'operator');
  await page.getByLabel('Password',{exact:true}).fill(process.env.COMMERCE_STAFF_PASSWORD!);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Deliveries'})).toBeVisible();
}
const mode=process.env.COMMERCE_STAFF_TEST_MODE || 'rules';
if(!['rules','mock-decisions'].includes(mode))throw new Error('Invalid COMMERCE_STAFF_TEST_MODE');
const mockMode=mode==='mock-decisions';
const investigationTimeout=process.env.COMMERCE_STAFF_RESTART_TEST==='1'?60000:30000;
const headers=()=>({Authorization:'Basic '+Buffer.from((process.env.COMMERCE_STAFF_USERNAME || 'operator')+':'+process.env.COMMERCE_STAFF_PASSWORD).toString('base64')});
test('eligible shipment: progress, reload, duplicate admission and exact approval boundary',async({page,request})=>{
  const opened=await request.post('/api/cases',{headers:headers(),data:{order_id:'ORD-1042',shipment_id:'SHIP-1042',items:{'shirt-blue-M':1}}});expect(opened.status()).toBe(201);const c=await opened.json();
  await page.goto('/#case='+c.id);await signIn(page);
  await page.getByLabel('Shipment report',{exact:true}).fill('Customer says the parcel never arrived. Please check the evidence.');
  const admitted=page.waitForResponse(r=>r.url().endsWith('/shipment-investigation')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Investigate shipment',exact:true}).dblclick();
  const response=await admitted;expect(response.status()).toBe(202);const body=response.request().postDataJSON();const run=(await response.json()).run_id;
  const duplicate=await request.post('/api/cases/'+c.id+'/shipment-investigation',{headers:headers(),data:body});expect(duplicate.status()).toBe(202);expect((await duplicate.json()).run_id).toBe(run);
  await expect(page.getByText('Investigation in progress. You can refresh or return later.')).toBeVisible();
  await page.screenshot({path:'artifacts/results/shipment-progress.png',fullPage:true});
  await page.reload();await signIn(page);
  await expect(page.getByText('Saved report: Customer says the parcel never arrived. Please check the evidence.')).toBeVisible();
  await expect(page.getByText('Investigation complete. Replacement proposal ready for your review.')).toBeVisible({timeout:investigationTimeout});
  await expect(page.getByText('Available stock: Confirmed',{exact:false})).toBeVisible();
  if(mockMode){
    await page.getByText('Why evidence gathering continued',{exact:true}).click();
    await expect(page.getByText('Evidence continuation:',{exact:false}).first()).toBeVisible();
    await page.getByText('Why evidence gathering continued',{exact:true}).click();
  }else{await expect(page.getByText('Why evidence gathering continued',{exact:true})).toHaveCount(0);}
  const detail=await (await request.get('/api/cases/'+c.id,{headers:headers()})).json();expect(detail.shipment_investigation.mode).toBe(mockMode?'simulated_decisions':'rules');expect(detail.assessment.facts.stock_available).toBe(true);expect(detail.approval).toBeNull();expect(detail.operation).toBeNull();
  expect((await request.post('/api/cases/'+c.id+'/execute',{headers:headers(),data:{operation_id:'unapproved'}})).status()).toBe(409);
  await page.screenshot({path:'artifacts/results/shipment-proposal.png',fullPage:true});
  await page.getByRole('button',{name:'Approve replacement',exact:true}).click();
  await expect(page.getByRole('button',{name:'Create replacement',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Confirm approval',exact:true}).click();
  await expect(page.getByRole('button',{name:'Create replacement',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Create replacement',exact:true}).click();await page.getByRole('button',{name:'Confirm replacement',exact:true}).click();
  await expect.poll(async()=> (await (await request.get('/api/cases/'+c.id,{headers:headers()})).json()).operation?.status,{timeout:20000}).toBe('verified');
  const final=await(await request.get('/api/cases/'+c.id,{headers:headers()})).json();
  const repeated=await request.post('/api/cases/'+c.id+'/execute',{headers:headers(),data:{operation_id:final.approval.operation_id}});expect(repeated.status()).toBe(409);
  await expect.poll(async()=> (await (await request.get('/api/cases/'+c.id,{headers:headers()})).json()).events.filter((e:any)=>e.kind==='executed').length).toBe(1);
});
test('incomplete history: explanation, remaining unknowns and no replacement',async({page,request})=>{
  const r=await request.post('/api/cases',{headers:headers(),data:{order_id:'ORD-HISTORY',shipment_id:'SHIP-HISTORY',items:{'shirt-blue-M':1}}});expect(r.status()).toBe(201);const c=await r.json();
  await page.goto('/#case='+c.id);await signIn(page);
  await page.getByLabel('Shipment report',{exact:true}).fill('Parcel missing; please check previous compensation.');await page.getByRole('button',{name:'Investigate shipment',exact:true}).click();
  await expect(page.getByText('Investigation finished.',{exact:false})).toBeVisible({timeout:investigationTimeout});
  await expect(page.getByText('We need the full refund and replacement history before continuing.')).toBeVisible();
  await expect(page.getByRole('button',{name:'Approve replacement',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'Create replacement',exact:true})).toHaveCount(0);
  const d=await(await request.get('/api/cases/'+c.id,{headers:headers()})).json();expect(d.proposal).toBeNull();expect(d.operation).toBeNull();expect(d.assessment.facts.no_previous_compensation).toBeNull();
  expect((await request.post('/api/cases/'+c.id+'/execute',{headers:headers(),data:{operation_id:'not-approved'}})).status()).toBe(409);
  await page.screenshot({path:'artifacts/results/shipment-incomplete.png',fullPage:true});
});
