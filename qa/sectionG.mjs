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

// ============ SETTINGS ============
await app.navApp('Settings');
await app.shot('G_settings_load');
await app.capture('settings-load');
const btns = await app.listButtons();
console.log('SETTINGS BUTTONS:', JSON.stringify(btns.filter(b=>b&&!/keyboard|Deploy|Stop|View \d+ more/.test(b))));

// save optimizer config
await app.act('Guardar cambios (optimizer config)', async () => { await clickIf(/Guardar cambios/i, 'save-opt'); });
await app.waitIdle(30000);
await app.capture('settings-saveopt');

// save AI config
await app.act('Guardar configuración AI', async () => { await clickIf(/Guardar configuración AI/i, 'save-ai'); });
await app.waitIdle(30000);
await app.capture('settings-saveai');

// add custom ticker
await app.act('add custom ticker', async () => {
  // find a text input near the "Agregar (con advertencias)" button
  const inps = app.page.locator('[data-testid="stTextInput"] input');
  const n = await inps.count();
  if (n) { await inps.last().fill('NVDA'); await inps.last().press('Tab'); }
  await clickIf(/Agregar \(con advertencias\)|Agregar/i, 'add-custom');
});
await app.waitIdle(30000);
await app.capture('settings-customticker');
await app.shot('G_settings_custom');

// clear cache
await app.act('Limpiar todo el caché', async () => { await clickIf(/Limpiar todo el caché/i, 'clear-cache'); });
await app.waitIdle(60000);
await app.capture('settings-clearcache');
await app.shot('G_settings_cache');

// ============ ABOUT ============
await app.navApp('About');
await app.waitIdle(30000);
await app.capture('about-load');
await app.shot('G_about');
const aboutTxt = await app.page.locator('[data-testid="stMain"]').innerText();
console.log('ABOUT length:', aboutTxt.length, '| snippet:', aboutTxt.slice(0,150).replace(/\n+/g,' | '));

await app.finish('./out_G.json');
