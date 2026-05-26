"""About page — version info, system health check, score formula and docs."""

from __future__ import annotations

import concurrent.futures
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from config import DEFAULT_TICKERS
from data.preferences import _PREFS_PATH
from data.universe_loader import UNIVERSE_META, list_universes, load_universe

_VERSION = "1.1.0"
_BASE_DIR = Path(__file__).parent.parent.parent

# ------------------------------------------------------------------ #
#  Health check engine                                                 #
# ------------------------------------------------------------------ #

def _chk(component: str, ok: bool, detail: str, duration_ms: int = 0) -> dict:
    return {
        "icon":        "✅" if ok else "❌",
        "status":      "ok" if ok else "error",
        "component":   component,
        "detail":      detail,
        "duration_ms": duration_ms,
    }


def _chk_warn(component: str, detail: str, duration_ms: int = 0) -> dict:
    return {"icon": "⚠️", "status": "warning", "component": component,
            "detail": detail, "duration_ms": duration_ms}


def _run_health_check() -> list[dict]:
    results = []

    # ── 1. Internet (DNS) ─────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        results.append(_chk("🌐 Conectividad a internet", True, "DNS OK",
                            int((time.monotonic() - t0) * 1000)))
    except OSError:
        results.append(_chk("🌐 Conectividad a internet", False,
                            "Sin acceso a DNS — verificá tu conexión",
                            int((time.monotonic() - t0) * 1000)))

    # ── 2. Yahoo Finance (yfinance) ───────────────────────────────────
    t0 = time.monotonic()
    def _fetch_yf():
        import yfinance as yf
        fi = yf.Ticker("AAPL").fast_info
        return getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_fetch_yf)
            price = fut.result(timeout=8)
        ms = int((time.monotonic() - t0) * 1000)
        if price:
            results.append(_chk("📈 Yahoo Finance (yfinance)", True,
                                f"AAPL: ${price:.2f} — respuesta en {ms} ms", ms))
        else:
            results.append(_chk_warn("📈 Yahoo Finance (yfinance)",
                                     f"Conectado pero sin precio ({ms} ms)", ms))
    except concurrent.futures.TimeoutError:
        ms = int((time.monotonic() - t0) * 1000)
        results.append(_chk("📈 Yahoo Finance (yfinance)", False,
                            f"Timeout ({ms} ms) — la API puede estar lenta", ms))
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        results.append(_chk("📈 Yahoo Finance (yfinance)", False,
                            f"{str(exc)[:80]} ({ms} ms)", ms))

    # ── 3. Archivo de preferencias ────────────────────────────────────
    t0 = time.monotonic()
    try:
        if _PREFS_PATH.exists():
            import json
            json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
            size_kb = round(_PREFS_PATH.stat().st_size / 1024, 1)
            results.append(_chk("📋 Preferencias de usuario", True,
                                f"Archivo válido ({size_kb} KB)",
                                int((time.monotonic() - t0) * 1000)))
        else:
            results.append(_chk_warn("📋 Preferencias de usuario",
                                     "Archivo no existe — se usarán los defaults",
                                     int((time.monotonic() - t0) * 1000)))
    except Exception as exc:
        results.append(_chk("📋 Preferencias de usuario", False,
                            f"Error al leer: {exc}",
                            int((time.monotonic() - t0) * 1000)))

    # ── 4. Archivos de universos ──────────────────────────────────────
    t0 = time.monotonic()
    universes = list_universes()
    missing = []
    for uk in universes:
        path = _BASE_DIR / "data" / "universes" / f"{uk}.json"
        if not path.exists():
            missing.append(uk)
    ms = int((time.monotonic() - t0) * 1000)
    if missing:
        results.append(_chk("🗂️ Archivos de universos", False,
                            f"Faltantes: {', '.join(missing)}", ms))
    else:
        counts = " · ".join(
            f"{UNIVERSE_META[uk]['name']} ({UNIVERSE_META[uk]['count']})"
            for uk in universes
        )
        results.append(_chk("🗂️ Archivos de universos", True,
                            f"{len(universes)} universos — {counts}", ms))

    # ── 5. Caché SQLite ───────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        from data.cache import cache
        stats = cache.get_stats()
        ms    = int((time.monotonic() - t0) * 1000)
        results.append(_chk("🗄️ Caché SQLite", True,
                            f"{stats['valid']} entradas válidas · "
                            f"{stats['expired']} expiradas · "
                            f"{stats['db_size_mb']} MB · TTL {stats['ttl_hours']}h", ms))
    except Exception as exc:
        results.append(_chk("🗄️ Caché SQLite", False, str(exc)[:80],
                            int((time.monotonic() - t0) * 1000)))

    # ── 6. Configuración AI ───────────────────────────────────────────
    t0 = time.monotonic()
    ai_enabled  = st.session_state.get("ai_enabled", False)
    ai_provider = st.session_state.get("ai_provider", "claude")
    ai_model    = st.session_state.get("ai_model", "—")
    ai_key      = st.session_state.get("ai_api_key", "")

    if not ai_enabled:
        results.append(_chk_warn("🤖 Análisis AI",
                                 "Desactivado — usando scoring rule-based. "
                                 "Configurá en ⚙️ Configuración.",
                                 int((time.monotonic() - t0) * 1000)))
    elif ai_provider in ("xai", "nous"):
        # Try Hermes OAuth check
        try:
            hermes_dir = Path(os.path.expanduser("~/.hermes/hermes-agent"))
            hermes_ok  = hermes_dir.is_dir()
        except Exception:
            hermes_ok = False
        ms = int((time.monotonic() - t0) * 1000)
        if hermes_ok:
            results.append(_chk("🤖 Análisis AI", True,
                                f"Activo — {ai_provider} / {ai_model} (Hermes OAuth ✓)", ms))
        else:
            results.append(_chk_warn("🤖 Análisis AI",
                                     f"Proveedor {ai_provider} requiere Hermes OAuth "
                                     f"pero ~/.hermes/hermes-agent no encontrado. "
                                     f"Modelo: {ai_model}",
                                     int((time.monotonic() - t0) * 1000)))
    elif ai_key and len(ai_key) >= 20:
        results.append(_chk("🤖 Análisis AI", True,
                            f"Activo — {ai_provider} / {ai_model} (API Key ✓)",
                            int((time.monotonic() - t0) * 1000)))
    else:
        results.append(_chk("🤖 Análisis AI", False,
                            f"AI_ENABLED=true pero API Key ausente o inválida "
                            f"(proveedor: {ai_provider}). Revisá ⚙️ Configuración.",
                            int((time.monotonic() - t0) * 1000)))

    # ── 7. Issues de configuración startup ───────────────────────────
    config_issues = st.session_state.get("config_issues", [])
    errors   = [m for l, m in config_issues if l == "error"]
    warnings = [m for l, m in config_issues if l == "warning"]
    if errors:
        results.append(_chk("⚙️ Configuración startup", False,
                            f"{len(errors)} error(s): {errors[0][:80]}"))
    elif warnings:
        results.append(_chk_warn("⚙️ Configuración startup",
                                 f"{len(warnings)} advertencia(s) — ver 'Estado de configuración' arriba"))
    else:
        results.append(_chk("⚙️ Configuración startup", True,
                            "Sin errores ni advertencias"))

    return results


# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("ℹ️ About — Retirement Advisor")
st.caption(f"v{_VERSION} — Motor de análisis de inversiones para el retiro")

_universe_count = len(st.session_state.get("universe", DEFAULT_TICKERS))
_n_universes    = len(list_universes())

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Versión",            _VERSION)
col2.metric("Tickers en universo", _universe_count)
col3.metric("Universos",           _n_universes)
col4.metric("Tests",               "133 passing")
col5.metric("Páginas",             "11")

st.divider()

# Project highlights
st.subheader("Highlights del proyecto")
h1, h2, h3 = st.columns(3)
with h1:
    st.markdown("""
**📊 Análisis cuantitativo**
- Score fundamental 0–100 en 5 dimensiones
- Consistency Score + Piotroski F-Score
- Economic Moat cuantitativo 0–20 pts
- Análisis técnico en barras semanales de 10 años
""")
with h2:
    st.markdown("""
**🤖 Decisión asistida por AI**
- Claude, GPT-4o, Grok o Nous Research
- Moat cualitativo: network effects, switching costs, brand, regulatory
- Razonamiento en lenguaje natural por ticker
- Fallback rule-based si no hay API key
""")
with h3:
    st.markdown("""
**📈 Gestión de portafolio**
- Optimizer Mean-Variance (SLSQP) con 3 perfiles
- 4 presets de retiro + combinación de universos
- Monte Carlo block-bootstrap 10 000 sims
- Stress test en 6 crisis históricas
""")

st.divider()

# Config status
st.subheader("Estado de configuración")
issues = st.session_state.get("config_issues", [])
if not issues:
    st.info("Validación de configuración no disponible. Recargá la página.")
else:
    for level, msg in issues:
        if level == "error":
            st.error(msg, icon="🔴")
        elif level == "warning":
            st.warning(msg, icon="🟡")
        elif "Hermes OAuth" in msg:
            st.success(msg, icon="🔐")
        else:
            st.success(msg, icon="✅")

st.divider()

# System health check
st.subheader("🩺 Health Check del sistema")
st.caption("Verificación on-demand de conectividad, datos y configuración.")

_hc_col1, _hc_col2 = st.columns([1, 3])
with _hc_col1:
    _run_hc = st.button("🔍 Ejecutar Health Check", type="primary", use_container_width=True)

if _run_hc:
    with st.spinner("Verificando componentes…"):
        st.session_state.health_check_results = _run_health_check()
        st.session_state.health_check_ts = __import__("datetime").datetime.now().strftime("%H:%M:%S")

if "health_check_results" in st.session_state:
    _hc_results: list[dict] = st.session_state.health_check_results
    _hc_ts = st.session_state.get("health_check_ts", "")

    _ok_count  = sum(1 for r in _hc_results if r["status"] == "ok")
    _err_count = sum(1 for r in _hc_results if r["status"] == "error")
    _total     = len(_hc_results)

    if _err_count == 0:
        st.success(f"✅ {_ok_count}/{_total} verificaciones OK — última actualización: {_hc_ts}", icon="✅")
    else:
        st.error(f"❌ {_err_count} error(s) · {_ok_count}/{_total} OK — última actualización: {_hc_ts}", icon="❌")

    for _r in _hc_results:
        _ms_str = f" — {_r['duration_ms']} ms" if _r.get("duration_ms") else ""
        _line   = f"{_r['icon']} **{_r['component']}** — {_r['detail']}{_ms_str}"
        if _r["status"] == "ok":
            st.success(_line)
        elif _r["status"] == "warning":
            st.warning(_line)
        else:
            st.error(_line)

st.divider()

# Feature summary
st.subheader("Módulos activos")

# Show universe summary
_u_rows = []
for _uk in list_universes():
    _um = UNIVERSE_META.get(_uk, {})
    _u_rows.append(f"**{_um.get('name', _uk)}** ({_um.get('count', '?')} tickers) — {_um.get('description', '')}")
st.caption("Universos disponibles: " + " · ".join(_u_rows))

st.markdown("""
| Módulo | Descripción |
|--------|-------------|
| **🏠 Screener** | Ranking del universo con score ajustado (0–100) y señal — paralelo con caché 1h |
| **🔍 Análisis Profundo** | Piotroski, Consistency, Economic Moat cuantitativo + decisión AI |
| **💼 Mi Portfolio** | Posiciones abiertas, P&L, gráficos de pesos por sector |
| **📊 Allocation** | Regla conservadora acciones/bonos/cash según edad |
| **📈 Optimizer** | Mean-Variance SLSQP + 3 perfiles + 4 presets + combinación de universos |
| **📉 Backtesting** | Curva de equity histórica, Sharpe, Sortino, Calmar, scatter Score↔CAGR |
| **🎲 Simulaciones** | Monte Carlo 10k sims (block-bootstrap) + Stress Test 6 crisis históricas |
| **🔔 Alertas** | Motor inteligente con debounce SQLite + email/Telegram + PDF mensual |
| **📋 Watchlist** | Tickers favoritos con alertas de precio en tiempo real |
| **⚙️ Configuración** | Universo personalizado, configuración AI, limpieza de caché |
""")

st.divider()

# Score formula
st.subheader("Fórmula del Score Ajustado")
st.code(
    "adjusted_score = min(\n"
    "    fundamental_score        (0–100)\n"
    "  + consistency_score        (0–15)   # estabilidad ROE/EPS/márgenes\n"
    "  + piotroski_bonus          (0–12)   # 9 checks YoY de calidad contable\n"
    "  + moat_bonus               (0–10)   # min(moat_score × 0.5, 10)\n"
    ", 100)",
    language="python",
)

st.divider()

# Docs links
st.subheader("Documentación técnica")
st.markdown("""
- `docs/architecture.md` — Mapa de módulos y flujo de datos
- `docs/moat_methodology.md` — Economic Moat: metodología y umbrales
- `docs/portfolio_optimizer.md` — Optimizer: SLSQP, perfiles, ARS discount
- `docs/alert_system.md` — Alertas: tipos, cooldowns, scheduler
- `docs/ROADMAP.md` — Historial de fases (1 → 15)
""")

st.divider()

st.warning(
    "**Aviso legal**: Esta herramienta es educativa. Los resultados no constituyen "
    "asesoramiento financiero. Los datos provienen de Yahoo Finance y pueden contener "
    "errores o estar desactualizados. Consultá con un asesor certificado antes de "
    "tomar decisiones de inversión.",
    icon="⚠️",
)
