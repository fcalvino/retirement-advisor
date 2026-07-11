import { App } from './driver.mjs';
const app = new App();
await app.start();
await app.goto('Stock_Analysis');
app.curPage = 'Stock_Analysis';

async function analyzeManual(sym, label) {
  await app.act(`manual analyze ${label} (${sym})`, async () => {
    const exp = app.page.getByText(/Ingresalo manualmente|No está en el universo/i).first();
    if (await exp.count()) await exp.click();
    await app.page.waitForTimeout(600);
    const inp = app.page.locator('[data-testid="stTextInput"] input').last();
    await inp.fill(sym);
    await inp.press('Enter');
    await app.page.waitForTimeout(900);
    // click the enabled manual Analizar (plain text, not the disabled universe one)
    const go = app.page.getByRole('button', { name: 'Analizar', exact: true }).first();
    if (await go.count()) await go.click({ timeout: 20000 });
    else await app.page.getByRole('button', { name: /Analizar/i }).last().click({ timeout: 20000 });
  });
  await app.waitIdle(150000);
  await app.capture(`manual ${label}`);
  await app.shot(`B_manual_${label}`);
  // dump the main alert/text so we can judge invalid-ticker handling
  const txt = await app.page.locator('[data-testid="stMain"]').innerText();
  console.log(`MAIN[${label}] first 300:`, txt.slice(0, 300).replace(/\n+/g,' | '));
}

await analyzeManual('YPF', 'adr');
await analyzeManual('ZZZZINVALIDXYZ', 'invalid');
await app.finish('./out_B_manual.json');
