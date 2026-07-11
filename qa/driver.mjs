// Reusable Playwright driver for QA navigation of the Streamlit app.
// Detects: stException tracebacks, error stAlerts, JS console errors, pageerror.
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = process.env.QA_BASE || 'http://localhost:8502';
const SHOTS = new URL('./shots/', import.meta.url).pathname;

export class App {
  constructor() {
    this.findings = [];   // {page, action, type, detail}
    this.actions = [];    // log of actions w/ timestamps for log correlation
    this.consoleErrors = [];
    this.page = null;
    this.browser = null;
    this.curPage = 'home';
  }

  async start() {
    this.browser = await chromium.launch({ headless: true });
    const ctx = await this.browser.newContext({ viewport: { width: 1600, height: 1200 } });
    this.page = await ctx.newPage();
    this.page.on('console', (m) => {
      if (m.type() === 'error') {
        const t = m.text();
        // ignore noisy favicon / network 4xx that are not app bugs
        this.consoleErrors.push(t);
      }
    });
    this.page.on('pageerror', (e) => {
      this.consoleErrors.push('PAGEERROR: ' + e.message);
    });
    await this.page.goto(BASE, { waitUntil: 'domcontentloaded' });
    await this.waitIdle();
  }

  ts() { return new Date().toISOString(); }

  async waitIdle(timeout = 120000) {
    const p = this.page;
    // give the rerun a moment to START before we check
    await p.waitForTimeout(500);
    const inProgress = /analizando|calculando|generando|deliberando|obteniendo|ejecutando|corriendo|reconciliando|recuperando|puntuando|simulando/i;
    try {
      await p.waitForFunction((rxSrc) => {
        const rx = new RegExp(rxSrc, 'i');
        const w = document.querySelector('[data-testid="stStatusWidget"]');
        if (w && (w.innerText || '').toLowerCase().includes('running')) return false;
        if (document.querySelector('[data-testid="stSpinner"]')) return false;
        const m = document.querySelector('[data-testid="stMain"]');
        if (!m) return false;
        const txt = (m.innerText || '').trim();
        if (txt.length === 0) return false;
        if (rx.test(txt)) return false; // in-page progress message still showing
        return true;
      }, inProgress.source, { timeout, polling: 600 });
    } catch { /* ignore */ }
    await p.waitForTimeout(900);
  }

  // capture errors currently visible + console errors accumulated since last drain
  async capture(action) {
    const p = this.page;
    const exc = await p.$$eval('[data-testid="stException"]', els => els.map(e => e.innerText.slice(0, 1500)));
    // error alerts: stAlert whose kind is error (baseweb negative). capture all alert texts too.
    const alerts = await p.$$eval('[data-testid="stAlert"]', els => els.map(e => {
      const txt = (e.innerText || '').slice(0, 400);
      // classify by background color of the alert container: red bg == st.error
      const inner = e.querySelector('[data-testid="stAlertContainer"]') || e.querySelector('div') || e;
      const bg = getComputedStyle(inner).backgroundColor || '';
      const m = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      let isError = false;
      if (m) {
        const r = +m[1], g = +m[2], b = +m[3];
        isError = r > 180 && g < 120 && b < 120; // red notification
      }
      return { txt, isError, bg };
    }));
    const jsErr = this.consoleErrors.splice(0);
    for (const e of exc) this.findings.push({ page: this.curPage, action, type: 'stException', detail: e });
    for (const a of alerts) if (a.isError) this.findings.push({ page: this.curPage, action, type: 'errorAlert', detail: a.txt });
    for (const j of jsErr) {
      if (/favicon|net::ERR|status of 4|status of 5|websocket/i.test(j)) continue; // network noise
      this.findings.push({ page: this.curPage, action, type: 'jsError', detail: j.slice(0, 400) });
    }
    return { exc: exc.length, errAlerts: alerts.filter(a => a.isError).length };
  }

  async act(action, fn) {
    this.actions.push({ ts: this.ts(), page: this.curPage, action });
    process.stdout.write(`ACTION @${this.ts()} [${this.curPage}] ${action}\n`);
    try {
      if (fn) await fn();
      await this.waitIdle();
    } catch (e) {
      this.findings.push({ page: this.curPage, action, type: 'driverError', detail: String(e).slice(0, 300) });
      process.stdout.write(`  DRIVER-ERR: ${String(e).slice(0,160)}\n`);
    }
    const r = await this.capture(action);
    if (r.exc || r.errAlerts) process.stdout.write(`  ⚠️ exc=${r.exc} errAlerts=${r.errAlerts}\n`);
  }

  async shot(name) {
    try { await this.page.screenshot({ path: SHOTS + name + '.png', fullPage: false }); } catch {}
  }

  // navigate to a page by URL slug (robust against re-renders)
  async goto(slug) {
    const p = this.page;
    const url = (process.env.QA_BASE || 'http://localhost:8502') + '/' + (slug === '' || slug === 'Home' ? '' : slug);
    this.actions.push({ ts: this.ts(), page: this.curPage, action: 'goto:' + slug });
    process.stdout.write(`NAV   @${this.ts()} -> ${slug}\n`);
    try {
      await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      this.curPage = slug || 'Home';
      await this.waitIdle();
    } catch (e) {
      this.findings.push({ page: slug, action: 'goto', type: 'navError', detail: String(e).slice(0, 200) });
      process.stdout.write(`  NAV-ERR: ${String(e).slice(0,160)}\n`);
    }
    await this.capture('after-nav');
  }

  // in-app navigation via sidebar link (PRESERVES session_state, no reload)
  async navApp(slug) {
    const p = this.page;
    this.actions.push({ ts: this.ts(), page: this.curPage, action: 'navApp:' + slug });
    process.stdout.write(`NAVAPP @${this.ts()} -> ${slug}\n`);
    try {
      // make sure the full nav is visible
      const more = p.getByText(/View \d+ more/i).first();
      if (await more.count()) await more.click().catch(()=>{});
      const link = p.locator(`[data-testid="stSidebarNav"] a[href$="/${slug}"]`).first();
      await link.scrollIntoViewIfNeeded().catch(()=>{});
      await link.click({ timeout: 15000 });
      this.curPage = slug;
      await this.waitIdle();
    } catch (e) {
      this.findings.push({ page: slug, action: 'navApp', type: 'navError', detail: String(e).slice(0, 200) });
      process.stdout.write(`  NAVAPP-ERR: ${String(e).slice(0,160)}\n`);
    }
    await this.capture('after-navApp');
  }

  // ---- widget helpers (best-effort, by role/testid) ----
  async clickButton(name) {
    const b = this.page.getByRole('button', { name, exact: false }).first();
    await b.scrollIntoViewIfNeeded().catch(()=>{});
    await b.click({ timeout: 15000 });
  }
  async fillText(idx, value) {
    const inp = this.page.locator('[data-testid="stTextInput"] input').nth(idx);
    await inp.fill(String(value));
  }
  async fillNumber(idx, value) {
    const inp = this.page.locator('[data-testid="stNumberInput"] input').nth(idx);
    await inp.fill(String(value));
  }
  async selectOption(idx, optionText) {
    const sel = this.page.locator('[data-testid="stSelectbox"]').nth(idx);
    await sel.click();
    await this.page.locator('[role="option"]', { hasText: optionText }).first().click({ timeout: 8000 });
  }
  async setSliderMin(idx = 0) {
    const thumb = this.page.locator('[data-testid="stSlider"] [role="slider"]').nth(idx);
    await thumb.click();
    await thumb.press('Home');
  }
  async setSliderSteps(idx = 0, steps = 3, key = 'ArrowRight') {
    const thumb = this.page.locator('[data-testid="stSlider"] [role="slider"]').nth(idx);
    await thumb.click();
    await thumb.press('Home');
    for (let i = 0; i < steps; i++) await thumb.press(key);
  }
  async clickTab(name) {
    await this.page.getByRole('tab', { name, exact: false }).first().click({ timeout: 10000 });
  }
  async listButtons() {
    return await this.page.$$eval('button', bs => bs.map(b => (b.innerText||'').trim()).filter(Boolean));
  }
  async listTabs() {
    return await this.page.$$eval('[role="tab"]', ts => ts.map(t => (t.innerText||'').trim()).filter(Boolean));
  }

  async finish(outfile) {
    fs.writeFileSync(outfile, JSON.stringify({ findings: this.findings, actions: this.actions }, null, 2));
    process.stdout.write(`\n=== FINDINGS (${this.findings.length}) ===\n`);
    for (const f of this.findings) process.stdout.write(`[${f.page}] (${f.type}) ${f.action}: ${String(f.detail).replace(/\n/g,' ').slice(0,200)}\n`);
    await this.browser.close();
  }
}
