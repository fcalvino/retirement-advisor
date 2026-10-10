"""Oráculo GOAL-PRIORITY-TEXT: una prioridad escrita en texto entra como número.

Residual declarado de PLAN-GOALS-KEYS (#214). ``goal_dict_with_defaults`` es la única
puerta a ``goals_list`` además del formulario, y completaba lo que faltaba o era
``None``, pero no convertía una prioridad presente. Un JSON importado a mano con
``"priority": "esencial"`` llegaba así a la sesión y «Simular» hacía
``int(goal.priority)`` → ``ValueError``.

Las referencias salen de las decisiones, no del código:
- «esencial» → 1 e «importante» → 2, ratificado por el usuario el 2026-10-02;
- las etiquetas que la app ya muestra (Alta/Media/Baja, ``PRIORITY_LABELS``) → su número;
- un texto que no es ninguna de esas → la prioridad por defecto de ``Goal`` (Media),
  porque una meta no debería tirar abajo la simulación del plan entero.
"""

from __future__ import annotations

import pytest

from portfolio.goals import Goal, goal_dict_with_defaults

BASE = {"name": "Casa", "target_amount_today": 100_000.0, "horizon_years": 5}
DEFAULT_PRIORITY = Goal(**BASE).priority


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("esencial", 1),
        ("importante", 2),
        ("Esencial", 1),
        (" IMPORTANTE ", 2),
        ("Alta", 1),
        ("media", 2),
        ("Baja", 3),
        ("1", 1),
        ("3", 3),
        (2, 2),
        (2.0, 2),
    ],
)
def test_priority_text_becomes_its_number(raw, expected):
    out = goal_dict_with_defaults({**BASE, "priority": raw})
    assert out["priority"] == expected
    assert type(out["priority"]) is int


@pytest.mark.parametrize("raw", ["deseable", "urgentísima", "", "9", "0"])
def test_unknown_priority_falls_back_to_the_goal_default(raw):
    out = goal_dict_with_defaults({**BASE, "priority": raw})
    assert out["priority"] == DEFAULT_PRIORITY == 2


def test_the_converted_goal_simulates_without_raising():
    """Lo que hace «Simular» con la meta: ``int(goal.priority)`` sobre un ``Goal``."""
    goal = Goal(**goal_dict_with_defaults({**BASE, "priority": "esencial"}))
    assert int(goal.priority) == 1
    assert goal.priority_label == "Alta"
