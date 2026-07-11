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

// ============ EVAL IA ============
await app.navApp('Eval_IA');
await app.shot('F_eval_load');
// Replay mode (default) run
await app.act('Eval — Correr (replay)', async () => { await clickIf(/Correr evaluación/i, 'eval-replay'); });
await app.waitIdle(120000);
await app.capture('eval-replay');
await app.shot('F_eval_replay');
// switch to live mode + run (AI real)
await app.act('Eval — switch to live', async () => {
  const live = app.page.locator('[role="radiogroup"] label').filter({ hasText: /vivo|live/i }).first();
  if (await live.count()) await live.click();
});
await app.act('Eval — Correr (live AI)', async () => { await clickIf(/Correr evaluación/i, 'eval-live'); });
await app.waitIdle(240000);
await app.capture('eval-live');
await app.shot('F_eval_live');

// ============ CALIDAD DE DATOS ============
await app.navApp('Calidad_Datos');
await app.shot('F_calidad_load');
await app.act('Reconciliar AAPL', async () => {
  const inp = app.page.locator('[data-testid="stTextInput"] input').first();
  if (await inp.count()) { await inp.fill('AAPL'); await inp.press('Enter'); }
  await clickIf(/Reconciliar fuentes/i, 'reconcile');
});
await app.waitIdle(120000);
await app.capture('calidad-result');
await app.shot('F_calidad_result');
console.log('CALIDAD snippet:', (await app.page.locator('[data-testid="stMain"]').innerText()).slice(0, 250).replace(/\n+/g,' | '));

// ============ MACRO RAG ============
await app.navApp('Macro_RAG');
await app.shot('F_macro_load');
await app.act('Cargar set de ejemplo', async () => { await clickIf(/Cargar set de ejemplo/i, 'load-examples'); });
await app.waitIdle(120000);
await app.capture('macro-loaded');
await app.shot('F_macro_loaded');
await app.act('Recuperar contexto', async () => {
  const inp = app.page.locator('[data-testid="stTextInput"] input').first();
  if (await inp.count()) { await inp.fill('inflación tasas de interés'); await inp.press('Enter'); }
  await clickIf(/Recuperar contexto/i, 'retrieve');
});
await app.waitIdle(120000);
await app.capture('macro-retrieve');
await app.shot('F_macro_retrieve');
console.log('MACRO snippet:', (await app.page.locator('[data-testid="stMain"]').innerText()).slice(0, 250).replace(/\n+/g,' | '));

// ============ CHAT (AI real) ============
await app.navApp('Chat');
await app.shot('F_chat_load');
async function ask(q, label) {
  await app.act(`chat: ${label}`, async () => {
    const ci = app.page.locator('[data-testid="stChatInput"] textarea, textarea[data-testid="stChatInputTextArea"]').first();
    await ci.fill(q);
    await ci.press('Enter');
  });
  await app.waitIdle(180000);
  await app.capture(`chat ${label}`);
  await app.shot('F_chat_' + label);
}
await ask('¿Qué opinás de AAPL como inversión a largo plazo?', 'stock');
await ask('¿Cómo está mi plan de retiro?', 'plan');
await ask('¿Cuál es la probabilidad de alcanzar mi meta?', 'projection');
console.log('CHAT snippet:', (await app.page.locator('[data-testid="stMain"]').innerText()).slice(-400).replace(/\n+/g,' | '));

await app.finish('./out_F.json');
