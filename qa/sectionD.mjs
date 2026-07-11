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

// ============ SIMULACIONES ============
await app.navApp('Simulaciones');
await app.shot('D_sim_load');
// reduce n_sims (sidebar slider index 1)
await app.act('set n_sims low', async () => {
  const sl = app.page.locator('[data-testid="stSidebar"] [data-testid="stSlider"] [role="slider"]').nth(1);
  if (await sl.count()) { await sl.click(); await sl.press('Home'); }
});
// MC tab
await app.act('tab Monte Carlo', async () => { await app.clickTab('Monte Carlo'); });
await app.act('Ejecutar Monte Carlo', async () => { await clickIf(/Ejecutar simulación Monte Carlo/i, 'mc'); });
await app.waitIdle(180000);
await app.capture('mc-result');
await app.shot('D_sim_mc');
// Stress tab
await app.act('tab Stress', async () => { await app.clickTab('Stress'); });
await app.waitIdle(120000);
await app.capture('stress');
await app.shot('D_sim_stress');
await app.act('export stress CSV', async () => { await clickIf(/Exportar stress test a CSV/i, 'stress-csv'); });
// Custom scenario
await app.act('tab Escenario personalizado', async () => { await app.clickTab('Escenario personalizado'); });
await app.act('Calcular impacto', async () => { await clickIf(/Calcular impacto/i, 'custom'); });
await app.waitIdle(120000);
await app.capture('custom');
await app.shot('D_sim_custom');
// Compare profiles
await app.act('tab Comparar Perfiles', async () => { await app.clickTab('Comparar Perfiles'); });
await app.act('Comparar los 3 perfiles', async () => { await clickIf(/Comparar los 3 perfiles/i, 'compare'); });
await app.waitIdle(180000);
await app.capture('compare-profiles');
await app.shot('D_sim_compare');
// Metas
await app.act('tab Mis Metas', async () => { await app.clickTab('Mis Metas'); });
await app.act('add goal', async () => {
  // fill goal form text/number inputs if present then submit
  const txt = app.page.locator('[data-testid="stTextInput"] input').first();
  if (await txt.count()) await txt.fill('Casa QA');
  await clickIf(/Agregar meta al plan/i, 'add-goal');
});
await app.waitIdle(120000);
await app.capture('metas');
await app.shot('D_sim_metas');
// Sensibilidad section (scroll / may be a button)
await app.act('sensibilidad (if present)', async () => {
  const s = app.page.getByText(/Sensibilidad/i).first();
  if (await s.count()) await s.click();
});
await app.waitIdle(120000);
await app.capture('sensibilidad');

// ============ BACKTESTING ============
await app.navApp('Backtesting');
await app.shot('D_bt_load');
await app.act('Correr Backtest', async () => { await clickIf(/Correr Backtest/i, 'bt'); });
await app.waitIdle(240000);
await app.capture('backtest-result');
await app.shot('D_bt_result');
for (const t of await app.listTabs()) {
  await app.act(`bt tab ${t}`, async () => { await app.clickTab(t); });
}

await app.finish('./out_D.json');
