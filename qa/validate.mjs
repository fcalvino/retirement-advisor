import { App } from './driver.mjs';
const app = new App();
await app.start();

async function clickIf(rx, label) {
  const btn = app.page.getByRole('button', { name: rx }).first();
  const n = await btn.count();
  console.log(`  [${label}] found=${n}`);
  if (n) await btn.click({ timeout: 20000 });
  return n > 0;
}

// ---- Reproduce BUG-1 scenario: Optimizer -> Plan (NO Monte Carlo) -> Generate PDF ----
await app.navApp('Optimizer');
await app.act('set optimizer max-tickers low', async () => { await app.setSliderSteps(0, 8); });
await app.act('Ejecutar Optimización', async () => { await clickIf(/Ejecutar Optimización/i, 'ejecutar'); });
for (let i = 0; i < 24; i++) { if ((await app.listTabs()).length) break; await app.page.waitForTimeout(10000); }
await app.waitIdle(30000);
console.log('Optimizer tabs:', JSON.stringify(await app.listTabs()));

await app.navApp('Plan');
const planMain = await app.page.locator('[data-testid="stMain"]').innerText();
console.log('Plan empty-state?', /Ir al Optimizer/.test(planMain));
console.log('Plan says no-MC?', /Sin simulación Monte Carlo/i.test(planMain));

// Generate PDF (the exact action that failed before)
await app.act('expand PDF + Generar PDF', async () => {
  const ex = app.page.getByText(/Generar PDF del plan|PDF del plan/i).first();
  if (await ex.count()) await ex.click();
  await app.page.waitForTimeout(600);
  await clickIf(/^📄 Generar PDF$|Generar PDF/i, 'plan-pdf');
});
await app.waitIdle(120000);
await app.capture('VALIDATE plan-pdf');
await app.shot('VAL_plan_pdf');

// VALIDATION CHECKS
const mainTxt = await app.page.locator('[data-testid="stMain"]').innerText();
const hasPdfError = /Error generando el PDF/i.test(mainTxt);
const hasDownload = (await app.page.getByRole('button', { name: /Descargar PDF/i }).count()) > 0
                 || (await app.page.locator('[data-testid="stDownloadButton"]').count()) > 0;
console.log('\n==== VALIDATION RESULT (BUG-1) ====');
console.log('PDF error alert present?  ', hasPdfError, '  (expected: false)');
console.log('Download PDF button present?', hasDownload, '  (expected: true)');
console.log('VERDICT:', (!hasPdfError && hasDownload) ? '✅ FIXED' : '❌ STILL BROKEN');

await app.finish('./out_validate.json');
