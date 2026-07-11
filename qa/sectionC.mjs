import { App } from './driver.mjs';
const app = new App();
await app.start();

async function clickIf(rx, label) {
  const btn = app.page.getByRole('button', { name: rx }).first();
  const n = await btn.count();
  console.log(`  [${label}] button found=${n}`);
  if (n) await btn.click({ timeout: 20000 });
  return n > 0;
}

// ============ OPTIMIZER ============
await app.navApp('Optimizer');
await app.shot('C_opt_load');
await app.act('set optimizer max-tickers to min+8', async () => { await app.setSliderSteps(0, 8); });
await app.act('select Moderado profile', async () => {
  const r = app.page.locator('[role="radiogroup"] label').nth(1);
  if (await r.count()) await r.click();
});
await app.act('Ejecutar Optimización', async () => { await clickIf(/Ejecutar Optimización/i, 'ejecutar'); });
for (let i = 0; i < 24; i++) {
  const tabs = await app.listTabs();
  if (tabs.length) { console.log('OPT TABS:', JSON.stringify(tabs)); break; }
  await app.page.waitForTimeout(10000);
}
await app.waitIdle(30000);
await app.capture('optimizer-result');
await app.shot('C_opt_result');
for (const t of await app.listTabs()) {
  await app.act(`opt tab ${t}`, async () => { await app.clickTab(t); });
  await app.shot('C_opt_tab_' + t.replace(/[^a-zA-Z]/g,''));
}
await app.act('comparar universos', async () => { await clickIf(/Comparar todos los universos/i, 'comparar'); });
await app.waitIdle(120000);
await app.capture('optimizer-compare');
await app.act('export cartera CSV', async () => { await clickIf(/Exportar cartera a CSV/i, 'csv'); });
await app.act('expand grok narrative', async () => {
  const ex = app.page.getByText(/Grok explica|núcleo manejable/i).first();
  console.log('  narrative expander found=', await ex.count());
  if (await ex.count()) await ex.click();
});
await app.waitIdle(120000);
await app.capture('optimizer-narrative');
await app.shot('C_opt_narrative');
await app.act('expand + generar PDF', async () => {
  const ex = app.page.getByText(/Reporte PDF|Generar.*PDF|PDF del plan/i).first();
  if (await ex.count()) await ex.click();
  await app.page.waitForTimeout(600);
  await clickIf(/Generar.*PDF|Generar y Descargar/i, 'pdf-gen');
});
await app.waitIdle(120000);
await app.capture('optimizer-pdf');
await app.shot('C_opt_pdf');

// ============ PLAN (session preserved) ============
await app.navApp('Plan');
await app.shot('C_plan_load');
const planMain = await app.page.locator('[data-testid="stMain"]').innerText();
console.log('PLAN shows empty-state?', /Ir al Optimizer/.test(planMain));
await app.act('save plan', async () => {
  const name = app.page.locator('[data-testid="stTextInput"] input').first();
  if (await name.count()) { await name.fill('QA Test Plan'); await name.press('Tab'); }
  await clickIf(/^💾 Guardar$|Guardar$/, 'save-plan');
});
await app.waitIdle(30000);
await app.capture('plan-saved');
await app.shot('C_plan_saved');
const btnsPlan = await app.listButtons();
console.log('PLAN BUTTONS:', JSON.stringify(btnsPlan.filter(b=>b&&!/keyboard|Deploy|Stop|View \d+ more/.test(b))).slice(0,700));
// load + activate the saved plan
await app.act('load saved plan', async () => { await clickIf(/^📥 Cargar$|Cargar$/, 'load'); });
await app.waitIdle(30000);
await app.act('activate plan', async () => { await clickIf(/Cargar y activar|Activar/i, 'activate'); });
await app.waitIdle(30000);
await app.capture('plan-activated');
await app.shot('C_plan_activated');
// buy list CSV + PDF expanders
await app.act('expand buy list', async () => {
  const ex = app.page.getByText(/Lista de compra|compra del núcleo/i).first();
  if (await ex.count()) await ex.click();
});
await app.act('expand plan PDF + generate', async () => {
  const ex = app.page.getByText(/Generar PDF del plan|PDF del plan/i).first();
  if (await ex.count()) await ex.click();
  await app.page.waitForTimeout(500);
  await clickIf(/Generar PDF/i, 'plan-pdf');
});
await app.waitIdle(120000);
await app.capture('plan-pdf');
await app.shot('C_plan_pdf');
// sample plan load (demo)
await app.act('load sample plan', async () => { await clickIf(/Cargar ejemplo/i, 'sample'); });
await app.waitIdle(30000);
await app.capture('plan-sample');

// ============ PORTFOLIO ============
await app.navApp('Portfolio');
await app.shot('C_portfolio_load');
await app.capture('portfolio-load');
await app.act('run sizing analysis', async () => { await clickIf(/Ejecutar.*análisis de sizing/i, 'sizing'); });
await app.waitIdle(180000);
await app.capture('portfolio-sizing');
await app.shot('C_portfolio_sizing');
await app.act('open+close edit dialog', async () => {
  const e = app.page.getByRole('button', { name: '✏️' }).first();
  if (await e.count()) { await e.click(); await app.page.waitForTimeout(900); }
  const c = app.page.getByRole('button', { name: /Cancelar/i }).first();
  if (await c.count()) await c.click();
});
await app.capture('portfolio-editdialog');

// ============ ALLOCATION ============
await app.navApp('Allocation');
await app.shot('C_alloc_load');
await app.act('move age slider', async () => { await app.setSliderSteps(0, 5); });
await app.act('move retirement slider', async () => { await app.setSliderSteps(1, 3); });
await app.capture('allocation');
await app.shot('C_alloc_after');

await app.finish('./out_C.json');
