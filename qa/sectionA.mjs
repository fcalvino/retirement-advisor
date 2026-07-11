import { App } from './driver.mjs';
const app = new App();
await app.start();
app.curPage = 'Home';
await app.capture('home-load');
await app.shot('A_home');

// Sidebar universe switch + restore
const sb = app.page.locator('[data-testid="stSidebar"]');
const sbSel = sb.locator('[data-testid="stSelectbox"]').first();
if (await sbSel.count()) {
  await app.act('switch universe', async () => {
    await sbSel.click();
    const opts = app.page.locator('[role="option"]');
    if (await opts.count() > 1) await opts.nth(1).click();
  });
  await app.shot('A_universe_switched');
  await app.act('restore universe', async () => {
    await sbSel.click();
    const opts = app.page.locator('[role="option"]');
    if (await opts.count() > 0) await opts.nth(0).click();
  });
}

// Settings page — onboarding form + other controls
await app.goto('Settings');
await app.shot('A_settings');
const tabs = await app.listTabs();
console.log('SETTINGS TABS:', JSON.stringify(tabs));
const btns = await app.listButtons();
console.log('SETTINGS BUTTONS:', JSON.stringify(btns.filter(b=>b && !/keyboard|Deploy|View \d+ more/.test(b))));

// Submit onboarding form (re-save profile) if present
await app.act('save onboarding profile', async () => {
  const save = app.page.getByRole('button', { name: /Guardar mi perfil|Guardar perfil/i }).first();
  if (await save.count()) await save.click();
});
await app.shot('A_settings_saved');

await app.finish('./out_A.json');
