"""Temporary helper: navigate every dashboard page with Playwright and capture
full-page screenshots to feed the brainstorming docs. Safe to delete afterwards.

Usage: ./venv/bin/python3 scripts/brainstorm_capture.py [base_url] [out_dir]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8533"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/brainstorm/_screenshots")
OUT.mkdir(parents=True, exist_ok=True)

# (sidebar link text, output filename slug). Order follows app.py nav.
PAGES = [
    ("Inicio", "01_inicio"),
    ("Hablá con tu plan", "19_chat"),
    ("Screener", "02_screener"),
    ("Stock Analysis", "03_stock_analysis"),
    ("Comité", "16_comite"),
    ("Portfolio", "04_portfolio"),
    ("Allocation", "05_allocation"),
    ("Optimizer", "06_optimizer"),
    ("Mi Plan", "13_mi_plan"),
    ("Backtesting", "07_backtesting"),
    ("Simulaciones", "08_simulaciones"),
    ("Alertas", "09_alertas"),
    ("Watchlist", "12_watchlist"),
    ("Track Record", "14_track_record"),
    ("Settings", "10_settings"),
    ("Eval IA", "15_eval_ia"),
    ("Calidad de Datos", "17_calidad_datos"),
    ("Macro RAG", "18_macro_rag"),
    ("About", "11_about"),
]


def wait_idle(page, settle=2.5):
    """Wait until Streamlit finished its rerun."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    # Wait for the "Running" status widget to disappear if present.
    for _ in range(40):
        try:
            running = page.locator('[data-testid="stStatusWidget"]').count()
            if running:
                txt = page.locator('[data-testid="stStatusWidget"]').inner_text(timeout=500)
                if "Running" in txt or "running" in txt:
                    time.sleep(0.5)
                    continue
        except Exception:
            pass
        break
    time.sleep(settle)


def main():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded")
        wait_idle(page, settle=3.5)

        only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
        for text, slug in PAGES:
            if only and slug not in only:
                continue
            try:
                wait_idle(page, settle=1.0)
                # Streamlit collapses long navs behind a "View N more" button.
                try:
                    more = page.locator(
                        '[data-testid="stSidebarNav"] >> text=/View \\d+ more/'
                    ).first
                    if more.count():
                        more.click(timeout=3000)
                        time.sleep(0.6)
                except Exception:
                    pass
                link = page.locator(
                    f'[data-testid="stSidebarNav"] a:has-text("{text}")'
                ).first
                if link.count() == 0:
                    link = page.get_by_role("link", name=text, exact=False).first
                link.scroll_into_view_if_needed(timeout=8000)
                link.click(timeout=20000)
                wait_idle(page)
                out = OUT / f"{slug}.png"
                page.screenshot(path=str(out), full_page=True)
                results.append((slug, "ok"))
                print(f"[ok] {slug}: {text}")

                # Capture tabs if present (Optimizer / Simulaciones / Stock / Plan).
                tabs = page.locator('[data-testid="stTabs"] button[role="tab"]')
                n = tabs.count()
                if n > 1 and slug in {
                    "06_optimizer", "08_simulaciones", "03_stock_analysis",
                    "13_mi_plan", "04_portfolio",
                }:
                    for i in range(min(n, 6)):
                        try:
                            tabs.nth(i).click(timeout=4000)
                            wait_idle(page, settle=1.5)
                            page.screenshot(
                                path=str(OUT / f"{slug}_tab{i+1}.png"), full_page=True
                            )
                            print(f"   [tab {i+1}] {slug}")
                        except Exception as e:
                            print(f"   [tab {i+1} fail] {e}")
            except Exception as e:
                results.append((slug, f"FAIL: {e}"))
                print(f"[FAIL] {slug}: {e}")
        browser.close()

    print("\n=== summary ===")
    for slug, status in results:
        print(f"{slug}: {status}")


if __name__ == "__main__":
    main()
