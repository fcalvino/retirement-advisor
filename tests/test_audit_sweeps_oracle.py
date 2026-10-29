"""Los barridos de ``scripts/audit_sweeps.py`` detectan lo que dicen y el repo está limpio.

La serie AUDIT-* (#283–#311) volvió a encontrar las mismas clases de defecto en lugares nuevos. Cuatro se pueden
detectar sin entender el negocio y viven como reglas sobre el AST. Este archivo prueba dos cosas:

1. **El detector funciona**: cada regla marca el patrón malo escrito a propósito (con la forma real del defecto que
   motivó la regla) y deja pasar la forma correcta. Sin esto, un detector que no detecta nada parecería «limpio».
2. **El repo no tiene hallazgos nuevos**: todo lo que el barrido encuentra hoy está en ``KNOWN_OK`` con su
   justificación, y una excepción que ya no se dispara hace fallar el test (se borra, no se deja vieja).
"""

from __future__ import annotations

import pytest

from scripts import audit_sweeps as sweeps


@pytest.fixture(scope="module")
def repo_hits():
    """El barrido del repo entero, una sola vez (lee unos 300 archivos)."""
    return sweeps.scan()

# --------------------------------------------------------------------------- #
#  1 — el detector                                                             #
# --------------------------------------------------------------------------- #

LOST_MESSAGE_BAD = """
if st.button("Guardar"):
    save()
    st.success("Guardado.")
    st.rerun()
"""
LOST_MESSAGE_SIDEBAR_BAD = """
with st.sidebar:
    st.sidebar.warning("Ojo")
    st.rerun()
"""
LOST_MESSAGE_GOOD = """
if st.button("Guardar"):
    save()
    flash("k", "success", "Guardado.")
    st.rerun()
"""
LOST_MESSAGE_OTHER_BLOCK_GOOD = """
try:
    work()
    st.rerun()
except Exception as exc:
    st.error(f"falló {exc}")
"""


@pytest.mark.parametrize("source", [LOST_MESSAGE_BAD, LOST_MESSAGE_SIDEBAR_BAD])
def test_a_message_drawn_before_a_rerun_is_flagged(source):
    assert len(sweeps.scan_source(source, "lost_message")) == 1


@pytest.mark.parametrize("source", [LOST_MESSAGE_GOOD, LOST_MESSAGE_OTHER_BLOCK_GOOD])
def test_a_flash_or_a_message_in_another_branch_is_not_flagged(source):
    assert sweeps.scan_source(source, "lost_message") == []


@pytest.mark.parametrize("source", [
    "x = ratio.clip(upper=2.4)",                  # el cociente sin piso (MOAT-FCF-CONVERSION)
    "x = ratio.clip(lower=-2.4)",
    "x = np.clip(values, 0.01, None)",
    "x = np.clip(values, None, 1.0)",
])
def test_a_clip_with_one_end_is_flagged(source):
    assert len(sweeps.scan_source(source, "one_sided_clip")) == 1


@pytest.mark.parametrize("source", [
    "x = ratio.clip(lower=-2.4, upper=2.4)",
    "x = ratio.clip(-2.4, 2.4)",
    "x = np.clip(values, 0.0, 1.0)",
    "x = np.clip(values, lb, ub)",
])
def test_a_clip_with_both_ends_is_not_flagged(source):
    assert sweeps.scan_source(source, "one_sided_clip") == []


@pytest.mark.parametrize("source", [
    "value = int(prefs.margin_pct or profile.margin_of_safety_pct)",   # AUDIT-UI-VERDAD: un 0 % volvía al perfil
    "if override:\n    return float(override)",
    "g = result.eps_growth or 4.0",
    "r = settings.withdrawal_rate or 0.04",
    "infl = mc_params.get('inflation_rate') or 3.0",       # PDF: una inflación de 0 % pasaba a ser 3 %
    "m = prefs['margin_pct'] or 5",
    "g = float(result.eps_growth) or 4.0",
])
def test_a_falsy_default_on_a_magnitude_is_flagged(source):
    assert len(sweeps.scan_source(source, "falsy_default")) == 1


@pytest.mark.parametrize("source", [
    "value = int(profile.margin_of_safety_pct if prefs.margin_pct is None else prefs.margin_pct)",
    "if override is not None:\n    return float(override)",
    "name = user.name or 'anónimo'",                 # no es una magnitud
    "if items:\n    pass",
    "g = result.growth or 0.0",                       # el default es 0: x vale 0 o cae a 0, igual resultado
    "m = prefs.get('margin_pct') or 0",
])
def test_the_is_none_form_and_non_magnitudes_are_not_flagged(source):
    assert sweeps.scan_source(source, "falsy_default") == []


@pytest.mark.parametrize("source", [
    "def test_a():\n    if not ok:\n        pytest.skip('sin datos')",
    "@pytest.mark.skip(reason='x')\ndef test_a():\n    pass",
    "@pytest.mark.skipif(sys.platform == 'win32', reason='x')\ndef test_a():\n    pass",
])
def test_a_skipped_test_is_flagged(source):
    assert len(sweeps.scan_source(source, "test_skip")) == 1


def test_an_optional_dependency_guard_is_not_a_skip():
    assert sweeps.scan_source("anthropic = pytest.importorskip('anthropic')", "test_skip") == []


def test_an_exception_covers_one_hit_not_every_copy_of_the_pattern(monkeypatch):
    """Una copia nueva de un patrón justificado no queda justificada sola (lo marcó la revisión)."""
    one = sweeps.Hit("falsy_default", "a.py", 1, "m or 5")
    copy = sweeps.Hit("falsy_default", "a.py", 9, "m or 5")
    monkeypatch.setattr(sweeps, "KNOWN_OK", {one.key: "justificado a propósito para este caso"})
    monkeypatch.setattr(sweeps, "KNOWN_COUNT", {})
    assert sweeps.unjustified([one]) == []
    assert sweeps.unjustified([one, copy]) == [copy]
    monkeypatch.setattr(sweeps, "KNOWN_COUNT", {one.key: 2})
    assert sweeps.unjustified([one, copy]) == []
    assert sweeps.stale_exceptions([one]) == [one.key]            # promete 2 y hay 1: se achica


def test_a_hit_survives_a_line_shift_because_its_key_is_the_code():
    a = sweeps.Hit("falsy_default", "x.py", 10, "m or 0.0")
    b = sweeps.Hit("falsy_default", "x.py", 99, "m or 0.0")
    assert a.key == b.key


# --------------------------------------------------------------------------- #
#  2 — el repo                                                                 #
# --------------------------------------------------------------------------- #

def test_a_bad_file_in_a_tree_makes_the_scan_report_it(tmp_path):
    """De punta a punta: un archivo malo escrito a propósito en un árbol de juguete aparece en el barrido."""
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "bad.py").write_text(LOST_MESSAGE_BAD)
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "bad.py").write_text("x = ratio.clip(upper=2.4)\ny = prefs.margin_pct or 5\n")
    found = {(h.rule, h.path) for h in sweeps.scan(tmp_path)}
    assert found == {("lost_message", "dashboard/bad.py"), ("one_sided_clip", "analysis/bad.py"),
                     ("falsy_default", "analysis/bad.py")}
    assert len(sweeps.unjustified(sweeps.scan(tmp_path))) == 3          # y ninguno está en KNOWN_OK


def test_the_repo_has_no_unjustified_hit(repo_hits):
    new = sweeps.unjustified(repo_hits)
    assert not new, (
        "Hallazgos nuevos de los barridos de la serie AUDIT-* (corré `./venv/bin/python scripts/audit_sweeps.py`):\n"
        + "\n".join(f"  {h}" for h in new)
        + "\nArreglalos, o —si el patrón es correcto acá— agregalos a KNOWN_OK con la razón."
    )


def test_every_exception_still_fires(repo_hits):
    stale = sweeps.stale_exceptions(repo_hits)
    assert not stale, f"excepciones que ya no se disparan (borralas de KNOWN_OK): {stale}"


def test_every_exception_says_why():
    assert all(len(why.strip()) > 20 for why in sweeps.KNOWN_OK.values())
