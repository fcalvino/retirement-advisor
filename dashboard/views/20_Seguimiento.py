"""Alertas + Track Record en una entrada del menú (IDEA-3 MENÚ).

Cada pestaña corre la página original (``8_Alertas.py``, ``13_Track_Record.py``),
que sigue registrada, oculta, con su propia URL. Si una corta temprano
(``stop_view``), la otra pestaña se dibuja igual.
"""

from __future__ import annotations

import streamlit as st

from dashboard.shared import run_view

tab_alerts, tab_track = st.tabs(["🔔 Alertas", "📒 Track Record"])
with tab_alerts:
    run_view("8_Alertas.py")
with tab_track:
    run_view("13_Track_Record.py")
