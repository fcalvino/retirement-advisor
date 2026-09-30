"""Screener + Watchlist en una entrada del menú (IDEA-3 MENÚ).

Cada pestaña corre la página original (``1_Screener.py``, ``11_Watchlist.py``),
que sigue registrada, oculta, con su propia URL. Si una corta temprano
(``stop_view``), la otra pestaña se dibuja igual.
"""

from __future__ import annotations

import streamlit as st

from dashboard.shared import run_view

tab_screener, tab_watchlist = st.tabs(["🏠 Screener", "📋 Watchlist"])
with tab_screener:
    run_view("1_Screener.py")
with tab_watchlist:
    run_view("11_Watchlist.py")
