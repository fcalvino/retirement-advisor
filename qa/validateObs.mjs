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

// 1) Optimizer -> result in session
await app.navApp('Optimizer');
await app.act('opt max-tickers low', async () => { await app.setSliderSteps(0, 8); });
await app.act('Ejecutar Optimización', async () => { await clickIf(/Ejecutar Optimización/i, 'ejecutar'); });
for (let i = 0; i < 24; i++) { if ((await app.listTabs()).length) break; await app.page.waitForTimeout(10000); }
await app.waitIdle(30000);

// 2) Plan -> save (NO goal/target) -> activate
await app.navApp('Plan');
await app.act('save plan (no goal)', async () => {
  const name = app.page.locator('[data-testid="stTextInput"] input').first();
  if (await name.count()) { await name.fill('OBS Validate Plan'); await name.press('Tab'); }
  await clickIf(/^💾 Guardar$|Guardar$/, 'save');
});
await app.waitIdle(30000);
await app.act('activate plan', async () => { await clickIf(/🎯 Activar|Activar/i, 'activate'); });
await app.waitIdle(30000);
await app.capture('obs-plan-activated');
await app.shot('VAL_obs_plan');

// 3) Chat -> ask the meta-probability question
await app.navApp('Chat');
await app.act('chat: meta probability', async () => {
  const ci = app.page.locator('[data-testid="stChatInput"] textarea, textarea[data-testid="stChatInputTextArea"]').first();
  await ci.fill('¿Cuál es la probabilidad de alcanzar mi meta?');
  await ci.press('Enter');
});
await app.waitIdle(240000);
await app.capture('obs-chat');
await app.shot('VAL_obs_chat');

const txt = await app.page.locator('[data-testid="stMain"]').innerText();
// extract assistant answer area
const ans = txt.slice(-600).replace(/\n+/g, ' | ');
console.log('\nCHAT ANSWER (tail):', ans);
const misleading0 = /probabilidad[^|]*\b0\s*%/i.test(txt) || /\b0%\b[^|]*meta/i.test(txt);
const mentionsNoGoal = /no hay meta|defin[íi].*meta|carg[áa].*meta|no se puede calcular|sin meta/i.test(txt);
console.log('\n==== VALIDATION RESULT (OBS-1) ====');
console.log('Misleading "0%" present?', misleading0, '  (expected: false)');
console.log('Mentions "define a goal"?', mentionsNoGoal, '  (expected: true)');
console.log('VERDICT:', (!misleading0 && mentionsNoGoal) ? '✅ FIXED' : '⚠️ REVIEW');

await app.finish('./out_validateObs.json');
