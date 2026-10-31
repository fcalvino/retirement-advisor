#!/usr/bin/env python3
"""Barridos mecánicos de las clases de defecto que dejó la serie AUDIT-* (PRs #283–#311, 2026-10).

Cada auditoría de esta serie volvió a encontrar el mismo puñado de defectos en lugares nuevos. Las clases que
se pueden detectar sin entender el negocio están acá, como reglas sobre el AST, para que la próxima auditoría
(o el CI) las corra en segundos en vez de redescubrirlas leyendo:

* ``lost_message``    — ``st.success/info/warning/error`` seguido de ``st.rerun()`` en el mismo bloque: el rerun
                        descarta lo dibujado, el mensaje no se ve (AUDIT-UI-ESTADO, AUDIT-RESIDUALES).
* ``one_sided_clip``  — ``clip`` con un solo extremo: el cociente se topa hacia un lado y el otro queda sin
                        piso o sin techo (MOAT-FCF-CONVERSION, AUDIT-RESIDUALES moat).
* ``falsy_default``   — ``x or default`` o ``if x:`` sobre una magnitud (``*_pct``, ``*_rate``, margen, tasa,
                        crecimiento) donde 0 es un valor válido: un margen de 0 % volvía al del perfil.
* ``test_skip``       — ``pytest.skip(...)`` o ``@pytest.mark.skip*`` en un test: un test que se saltea no dice
                        nada (AUDIT-TESTS; la primera versión de un test del optimizador salteaba 9 casos y la revisión lo marcó).

Límites de los detectores, dichos para que nadie los lea como cobertura total: ``lost_message`` exige
``st.<mensaje>`` con raíz ``st`` en el mismo bloque que ``st.rerun()`` (no ve ``col.error(...)``, ni un rerun en un bloque
que contiene al del mensaje); ``test_skip`` no ve ``@pytest.mark.skip`` sin paréntesis ni ``from pytest import skip``;
``falsy_default`` marca nombres que coinciden con ``_MAGNITUDE`` (``is_growth`` también) y no ve ``not margin_pct``.

Lo que NO detecta (hay que leer): resultados en ``session_state`` sin atar a sus inputs, llamadas al LLM en cada
rerun, ``_safe_float`` que convierte NaN o texto en 0,0, etiquetas que prometen algo que el motor no hace. Eso
está en la lista de verificación de ``.claude/agents/engine-reviewer.md`` y en ``docs/MAINTENANCE.md``.

Uso::

    ./venv/bin/python scripts/audit_sweeps.py          # sólo lo que no está justificado en KNOWN_OK
    ./venv/bin/python scripts/audit_sweeps.py --all    # todo, también lo justificado

``tests/test_audit_sweeps_oracle.py`` corre esto sobre el repo en cada ``make check``: un hallazgo nuevo sin
justificar, o una excepción que ya no se dispara, hace fallar la suite.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import _bootstrap  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent

#: Carpetas que barre cada regla (rutas relativas a la raíz del repo).
UI_DIRS = ("dashboard",)
CODE_DIRS = ("analysis", "portfolio", "data", "alerts", "reports", "dashboard")
TEST_DIRS = ("tests",)

_MESSAGES = {"success", "info", "warning", "error"}
#: Nombres de magnitudes donde 0 es un valor válido y ``or``/``if x:`` lo confunde con «no hay».
_MAGNITUDE = re.compile(r"(_pct|_rate|margin|growth|override|yield)$")
_SNIPPET_MAX = 110


@dataclass(frozen=True)
class Hit:
    rule: str
    path: str       # relativo a la raíz, con «/»
    line: int
    snippet: str

    @property
    def key(self) -> Tuple[str, str, str]:
        """Identidad estable ante cambios de línea: regla, archivo y código."""
        return (self.rule, self.path, self.snippet)

    def __str__(self) -> str:
        return f"{self.rule:14} {self.path}:{self.line}  {self.snippet}"


#: Cuántos hallazgos idénticos cubre una excepción cuando son más de uno.
KNOWN_COUNT: Dict[Tuple[str, str, str], int] = {
    ("falsy_default", "reports/investment_plan.py", "mc_params.get('inflation_rate') or 3.0"): 2,
}

#: Excepciones justificadas: (regla, archivo, código) → por qué no es defecto. Una entrada que ya no se
#: dispara hace fallar ``tests/test_audit_sweeps_oracle.py``: se borra, no se deja vieja.
KNOWN_OK: Dict[Tuple[str, str, str], str] = {
    ("falsy_default", "dashboard/views/9_Settings.py", "_prefs.exigencia_pct or _prof_cfg.exigencia_pct"):
        "el campo tiene min_value=50: un 0 no se puede guardar (el margen sí, y se arregló en AUDIT-UI-VERDAD).",
    ("falsy_default", "data/product_ux.py", "if override:"):
        "profile_exigencia_pct: igual que arriba, la Exigencia mínima es 50. (profile_margin_pct usa `is not None`.)",
    ("falsy_default", "dashboard/shared.py", "drags.get('total_annual_drag_pct') or sum((float(drags.get(k, 0.0)) for k in _DRAG_KEYS))"):
        "si el total guardado es 0 se suma componente por componente: el mismo 0 si no hay drags.",
    ("falsy_default", "dashboard/shared.py", "if drags.get('annual_fee_pct'):"):
        "sólo lista en el resumen los drags que valen algo: un 0 no se muestra, que es lo buscado.",
    ("falsy_default", "dashboard/shared.py", "if drags.get('dividend_tax_drag_pct'):"):
        "ídem: un drag en 0 no se lista.",
    ("falsy_default", "dashboard/shared.py", "if drags.get('rebalance_cost_annual_pct'):"):
        "ídem: un drag en 0 no se lista.",
    ("falsy_default", "dashboard/shared.py", "if drags.get('ar_buffer_pct'):"):
        "ídem: un drag en 0 no se lista.",
    ("falsy_default", "data/product_ux.py", "drags.get('total_annual_drag_pct') or drags.get('annual_fee_pct')"):
        "sin verificar el daño (leído): con el total guardado en 0 el resumen del comité cae al fee anual.",
    ("falsy_default", "reports/investment_plan.py", "mc_params.get('inflation_rate') or 3.0"):
        "DEFECTO REAL (auditoría 2, 2026-10-29), pendiente de PR propio: el slider de Simulaciones admite 0,0 % "
        "(min_value=0.0) y el PDF lo reemplaza por 3,0 %; son dos sitios (:479 y :1183). Se borra al arreglarlo.",
    ("lost_message", "dashboard/views/8_Alertas.py", "st.info(f'⚡ Analizando {n} tickers en paralelo…')"):
        "aviso de progreso mientras corre el análisis; se espera que desaparezca. El resultado se guarda con flash.",
    ("one_sided_clip", "analysis/technical.py", "delta.clip(lower=0)"):
        "RSI: las ganancias son la parte positiva del delta; el otro lado es la pérdida (siguiente línea).",
    ("one_sided_clip", "analysis/technical.py", "delta.clip(upper=0)"):
        "RSI: las pérdidas son la parte negativa del delta; el otro lado es la ganancia (línea anterior).",
    ("one_sided_clip", "portfolio/black_litterman.py", "np.clip(conf, 0.001, None)"):
        "piso para no dividir por cero; la confianza no tiene techo natural.",
    ("one_sided_clip", "portfolio/black_litterman.py", "np.clip(omega_diag, 1e-10, None)"):
        "piso para que la matriz de incertidumbre sea invertible; no tiene techo natural.",
    ("one_sided_clip", "portfolio/optimizer.py", "np.clip(scores, 0.01, None)"):
        "piso para que ningún score en cero quede sin peso en el reparto proporcional; los topes se aplican después.",
    ("one_sided_clip", "portfolio/optimizer.py", "np.clip(weights, 1e-12, None)"):
        "piso para el logaritmo; los pesos ya están acotados por las cotas del optimizador.",
    ("test_skip", "tests/test_backtesting.py", "pytest.skip('no saved backtest in data/db/backtests/')"):
        "anotado como defecto en AUDIT-TESTS (se saltea siempre); al arreglarlo se borra esta excepción.",
    ("test_skip", "tests/test_config_single_home_oracle.py", "pytest.skip('fields removed — inertness is now structural')"):
        "anotado como defecto en AUDIT-TESTS; al arreglarlo se borra esta excepción.",
    ("test_skip", "tests/test_network_guard_oracle.py", "pytest.skip('corrida de medición (RA_NETGUARD=report)')"):
        "modo de medición opt-in del guard de red (RA_NETGUARD=report): en una corrida normal no se saltea.",
}


# --------------------------------------------------------------------------- #
#  Reglas                                                                      #
# --------------------------------------------------------------------------- #

def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _snippet(node: ast.AST) -> str:
    text = " ".join(ast.unparse(node).split())
    return text if len(text) <= _SNIPPET_MAX else text[: _SNIPPET_MAX - 1] + "…"


def _is_st_expr_call(stmt: ast.stmt, names: set[str]) -> bool:
    """``st.<name>(...)`` o ``st.sidebar.<name>(...)`` como sentencia."""
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    func = stmt.value.func
    return isinstance(func, ast.Attribute) and func.attr in names and _root_name(func) == "st"


def _statement_lists(tree: ast.AST) -> Iterator[List[ast.stmt]]:
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                yield handler.body


def find_lost_messages(tree: ast.AST) -> List[Tuple[int, str]]:
    """Un mensaje de Streamlit antes de ``st.rerun()`` en el mismo bloque."""
    hits = []
    for block in _statement_lists(tree):
        for index, stmt in enumerate(block):
            if _is_st_expr_call(stmt, {"rerun"}):
                hits += [(prev.lineno, _snippet(prev.value)) for prev in block[:index]
                         if _is_st_expr_call(prev, _MESSAGES)]
    return hits


def find_one_sided_clips(tree: ast.AST) -> List[Tuple[int, str]]:
    """``x.clip(...)`` o ``np.clip(...)`` con menos de dos extremos que no sean ``None``."""
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "clip"):
            continue

        def present(arg: ast.AST) -> bool:
            return not (isinstance(arg, ast.Constant) and arg.value is None)

        bounds = [a for a in node.args if present(a)]
        bounds += [k.value for k in node.keywords
                   if k.arg in {"lower", "upper", "a_min", "a_max", "min", "max"} and present(k.value)]
        # np.clip(x, lo, hi): el primer argumento es el dato, no un extremo.
        if _root_name(node.func) in {"np", "numpy"} and node.args:
            bounds = bounds[1:] if present(node.args[0]) else bounds
        if len(bounds) < 2:
            hits.append((node.lineno, _snippet(node)))
    return hits


def _magnitude_name(node: ast.AST) -> str | None:
    """El nombre de magnitud de ``x``, ``a.x``, ``d["x"]``, ``d.get("x")`` o ``float(...)`` de cualquiera de ellos."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and node.args:
            return _magnitude_name(node.args[0])           # d.get("inflation_rate")
        if isinstance(func, ast.Name) and func.id in {"float", "int"} and node.args:
            return _magnitude_name(node.args[0])
        return None
    if isinstance(node, ast.Subscript):
        return _magnitude_name(node.slice)                # d["margin_pct"]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        name = node.value
    elif isinstance(node, ast.Attribute):
        name = node.attr
    elif isinstance(node, ast.Name):
        name = node.id
    else:
        return None
    return name if _MAGNITUDE.search(name) else None


def _is_zero_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and not isinstance(node.value, bool) and node.value == 0


def find_falsy_defaults(tree: ast.AST) -> List[Tuple[int, str]]:
    """``magnitud or <default distinto de cero>`` e ``if magnitud:`` donde la magnitud puede valer 0.

    ``x or 0`` no se marca: si ``x`` vale 0 el resultado es el mismo. El daño es ``x or 3.0``: una inflación
    de 0 % pasa a ser 3 %. (Que ``or 0`` también convierte None en 0, y eso se lee como medido, hay que
    mirarlo a mano: es la clase «ausencia como cero» de la lista del revisor.)
    """
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and not _is_zero_constant(node.values[-1]):
            if any(_magnitude_name(v) for v in node.values[:-1]):
                hits.append((node.lineno, _snippet(node)))
        elif isinstance(node, ast.If) and _magnitude_name(node.test):
            hits.append((node.lineno, f"if {_snippet(node.test)}:"))
    return hits


def find_test_skips(tree: ast.AST) -> List[Tuple[int, str]]:
    """``pytest.skip(...)`` y ``@pytest.mark.skip/skipif``. ``importorskip`` (dependencia opcional) no cuenta."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if func.attr == "skip" and _root_name(func) == "pytest":
                hits.append((node.lineno, _snippet(node)))
            elif func.attr in {"skip", "skipif"} and isinstance(func.value, ast.Attribute) \
                    and func.value.attr == "mark":
                hits.append((node.lineno, _snippet(node)))
    return hits


RULES = {
    "lost_message": (find_lost_messages, UI_DIRS),
    "one_sided_clip": (find_one_sided_clips, CODE_DIRS),
    "falsy_default": (find_falsy_defaults, CODE_DIRS),
    "test_skip": (find_test_skips, TEST_DIRS),
}


# --------------------------------------------------------------------------- #
#  Barrido                                                                     #
# --------------------------------------------------------------------------- #

def _python_files(directory: Path) -> Iterator[Path]:
    for path in sorted(directory.rglob("*.py")):
        if "venv" not in path.parts and "__pycache__" not in path.parts:
            yield path


def scan(root: Path = ROOT, *, rules: Dict[str, tuple] | None = None) -> List[Hit]:
    """Todos los hallazgos de las reglas sobre ``root``, ordenados, sin descontar KNOWN_OK."""
    hits: List[Hit] = []
    for rule, (finder, dirs) in (rules or RULES).items():
        for name in dirs:
            base = root / name
            if not base.is_dir():
                continue
            for path in _python_files(base):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                rel = path.relative_to(root).as_posix()
                hits += [Hit(rule, rel, line, snippet) for line, snippet in finder(tree)]
    return sorted(hits, key=lambda h: (h.rule, h.path, h.line))


def scan_source(source: str, rule: str) -> List[Tuple[int, str]]:
    """Una regla sobre un trozo de código (para probar el detector con ejemplos malos escritos a propósito)."""
    return RULES[rule][0](ast.parse(source))


def unjustified(hits: List[Hit]) -> List[Hit]:
    """Hallazgos que ``KNOWN_OK`` no cubre. Cada excepción cubre UN hallazgo con ese código en ese archivo
    (``count`` en ``KNOWN_COUNT`` si son varios): una copia nueva del mismo patrón no queda justificada sola."""
    allowed: Dict[Tuple[str, str, str], int] = {k: KNOWN_COUNT.get(k, 1) for k in KNOWN_OK}
    out = []
    for hit in hits:
        if allowed.get(hit.key, 0) > 0:
            allowed[hit.key] -= 1
        else:
            out.append(hit)
    return out


def stale_exceptions(hits: List[Hit]) -> List[Tuple[str, str, str]]:
    """Excepciones que cubren más hallazgos de los que hay hoy (o ninguno): se achican o se borran."""
    seen: Dict[Tuple[str, str, str], int] = {}
    for h in hits:
        seen[h.key] = seen.get(h.key, 0) + 1
    return [k for k in KNOWN_OK if seen.get(k, 0) < KNOWN_COUNT.get(k, 1)]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--all", action="store_true", help="también los hallazgos justificados en KNOWN_OK")
    args = parser.parse_args(argv)
    hits = scan()
    shown = hits if args.all else unjustified(hits)
    for hit in shown:
        why = KNOWN_OK.get(hit.key)
        print(hit if not why else f"{hit}\n{'':16}↳ ok: {why}")
    stale = stale_exceptions(hits)
    for key in stale:
        print(f"EXCEPCIÓN VIEJA (ya no se dispara): {key}")
    print(f"\n{len(shown)} hallazgos{' (con justificados)' if args.all else ' sin justificar'}, "
          f"{len(KNOWN_OK)} excepciones, {len(stale)} viejas", file=sys.stderr)
    return 1 if (not args.all and shown) or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
