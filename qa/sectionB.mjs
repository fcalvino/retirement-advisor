import { App } from './driver.mjs';
const app = new App();
await app.start();

// ---------- SCREENER (refresh; likely cached) ----------
await app.goto('Screener');
await app.act('set screener max-tickers to min', async () => { await app.setSliderMin(0); });
await app.act('Refresh Analysis', async () => { await app.clickButton('Refresh Analysis'); });
await app.waitIdle(180000);
await app.capture('screener-refresh');
await app.shot('B_screener_after_refresh');

// ---------- STOCK ANALYSIS ----------
await app.goto('Stock_Analysis');

async function analyzeFromUniverse(sym, label) {
  // step 1: select ticker (causes a rerun)
  let selected = false;
  await app.act(`select ${label} (${sym})`, async () => {
    const tsel = app.page.locator('[data-testid="stSelectbox"]').nth(1);
    await tsel.click();
    await app.page.keyboard.type(sym);
    await app.page.waitForTimeout(900);
    const opt = app.page.locator('[role="option"]').first();
    if (await opt.count()) { await opt.click(); selected = true; }
  });
  if (!selected) { console.log(`SKIP ${sym}: not in universe`); return false; }
  // step 2: click Analizar (after selection rerun settled)
  await app.act(`analyze ${label} (${sym})`, async () => {
    const go = app.page.getByRole('button', { name: /Analizar/i }).first();
    await go.click({ timeout: 20000 });
  });
  await app.waitIdle(150000);
  await app.capture(`analyze ${label}`);
  await app.shot(`B_stock_${label}`);
  const tabs = await app.listTabs();
  console.log(`TABS [${label}]:`, JSON.stringify(tabs));
  for (const t of tabs) await app.act(`tab ${t} [${label}]`, async () => { await app.clickTab(t); });
  // expand detail sections
  const exps = await app.page.locator('[data-testid="stExpander"] summary, details summary').count();
  console.log(`expanders [${label}]:`, exps);
  return true;
}

async function analyzeManual(sym, label) {
  await app.act(`manual analyze ${label} (${sym})`, async () => {
    const exp = app.page.getByText(/Ingresalo manualmente|No está en el universo/i).first();
    if (await exp.count()) await exp.click();
    await app.page.waitForTimeout(500);
    // manual text input is the last text input
    const inp = app.page.locator('[data-testid="stTextInput"] input').last();
    await inp.fill(sym);
    await app.page.waitForTimeout(300);
    const go = app.page.getByRole('button', { name: /Analizar/i }).last();
    await go.click({ timeout: 20000 });
  });
  await app.waitIdle(150000);
  await app.capture(`manual ${label}`);
  await app.shot(`B_stock_${label}`);
}

await analyzeFromUniverse('AAPL', 'equity');
await analyzeFromUniverse('BTC', 'crypto');
await analyzeManual('YPF', 'adr');
await analyzeManual('ZZZZINVALIDXYZ', 'invalid');

await app.finish('./out_B.json');
