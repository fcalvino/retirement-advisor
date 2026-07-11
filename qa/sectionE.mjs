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

// ============ ALERTAS ============
await app.navApp('Alertas');
await app.shot('E_alertas_load');
await app.act('Ejecutar análisis ahora', async () => { await clickIf(/Ejecutar análisis ahora/i, 'run-alerts'); });
await app.waitIdle(240000);
await app.capture('alertas-run');
await app.shot('E_alertas_run');
await app.act('Generar reporte PDF', async () => { await clickIf(/Generar reporte PDF/i, 'alert-pdf'); });
await app.waitIdle(120000);
await app.capture('alertas-pdf');
await app.shot('E_alertas_pdf');
// other tabs
for (const t of ['Historial', 'Configuración', 'Silenciados']) {
  await app.act(`tab ${t}`, async () => { await app.clickTab(t); });
  await app.capture(`alertas-tab-${t}`);
  await app.shot('E_alertas_' + t);
}

// ============ WATCHLIST ============
await app.navApp('Watchlist');
await app.waitIdle(120000);
await app.capture('watchlist-load');
await app.shot('E_watchlist');
const wlMain = await app.page.locator('[data-testid="stMain"]').innerText();
console.log('WATCHLIST snippet:', wlMain.slice(0, 200).replace(/\n+/g,' | '));
// set a price alert via first expander
await app.act('open watchlist expander + set price alert', async () => {
  const exp = app.page.locator('[data-testid="stExpander"] summary').first();
  if (await exp.count()) { await exp.click(); await app.page.waitForTimeout(700); }
  const num = app.page.locator('[data-testid="stNumberInput"] input').first();
  if (await num.count()) await num.fill('500');
  await clickIf(/Set alert|Crear alerta|🔔/i, 'set-alert');
});
await app.capture('watchlist-alert');
await app.shot('E_watchlist_alert');

// ============ TRACK RECORD ============
await app.navApp('Track_Record');
await app.shot('E_track_load');
await app.act('Puntuar pendientes', async () => { await clickIf(/Puntuar pendientes/i, 'score'); });
await app.waitIdle(180000);
await app.capture('track-scored');
await app.shot('E_track_scored');
// change horizon selectbox
await app.act('change horizon', async () => {
  const sel = app.page.locator('[data-testid="stSelectbox"]').first();
  if (await sel.count()) { await sel.click(); const o = app.page.locator('[role="option"]').nth(2); if (await o.count()) await o.click(); }
});
await app.capture('track-horizon');

await app.finish('./out_E.json');
