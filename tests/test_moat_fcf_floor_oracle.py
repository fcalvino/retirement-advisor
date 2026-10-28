"""AUDIT-RESIDUALES (moat) — un año con ganancia diminuta y caja muy negativa no decide el promedio.

``_fcf_conversion`` promedia ``OCF / NI`` por año. El techo por año (``fcf_conversion_year_cap``) evita que
una ganancia diminuta dé un cociente enorme hacia arriba, pero el ``clip`` sólo topaba hacia arriba: con
NI = 1 y OCF = -100 el cociente es -100, y un solo año así hunde el promedio de cuatro (tres años de 2,4
y uno de -100 promedian -23: 0 puntos, cuando la conversión de los otros tres era excelente). Es el mismo
defecto del techo, del otro lado. Ahora el cociente de un año queda entre ``fcf_conversion_year_floor`` y
``fcf_conversion_year_cap`` (±2,4). Eso ACOTA lo que un año puede hacer (±2,4 / n sobre la media) sin
quitárselo: un año en el piso contra uno en el techo todavía mueve la media de cuatro en 1,2, el ancho de la
banda «excelente». Un cociente moderadamente negativo (NI 100, OCF -20: -0,2) no cambia: dice algo real.
El piso no es 0 (donde está un año de pérdida) porque eso cambiaría los años de ganancia con caja negativa
que el oráculo de MOAT-FCF-CONVERSION fija como sin cambios.

Los esperados están calculados a mano con los topes de config, no leídos del motor. Sin red.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from config import MOAT
from tests.test_moat_fcf_conversion_oracle import _engine, _points


def test_the_floor_is_the_mirror_of_the_cap():
    assert MOAT.fcf_conversion_year_floor == -MOAT.fcf_conversion_year_cap == -2.4


def test_a_sliver_of_profit_with_heavy_cash_burn_is_floored_not_averaged_at_minus_one_hundred():
    ni, ocf = [100.0, 100.0, 100.0, 1.0], [240.0, 240.0, 240.0, -100.0]     # 2.4, 2.4, 2.4 y -100 → -2.4
    assert _engine(ni, ocf) == pytest.approx((2.4 + 2.4 + 2.4 - 2.4) / 4) == pytest.approx(1.2)


def test_the_points_follow_the_floored_mean():
    ni, ocf = [100.0, 100.0, 100.0, 1.0], [230.0, 230.0, 230.0, -100.0]     # 2,3 ×3 y -100 → -2,4
    assert _engine(ni, ocf) == pytest.approx((2.3 * 3 - 2.4) / 4) == pytest.approx(1.125)
    assert _points(ni, ocf) == 1.0            # ≥ 0,9 (bueno); con la media vieja (-23,3) eran 0


def test_a_moderately_negative_ratio_is_unchanged():
    ni, ocf = [100.0, 100.0], [-20.0, 150.0]                                # -0,2 y 1,5
    assert _engine(ni, ocf) == pytest.approx((-0.2 + 1.5) / 2)


def test_a_ratio_exactly_at_the_floor_is_unchanged():
    ni, ocf = [100.0, 100.0], [-240.0, 240.0]
    assert _engine(ni, ocf) == pytest.approx(0.0)


def test_the_floor_comes_from_config():
    ni, ocf = [1.0, 1.0], [-100.0, -100.0]
    with patch.object(MOAT, "fcf_conversion_year_floor", -1.0):
        assert _engine(ni, ocf) == pytest.approx(-1.0)
    assert _engine(ni, ocf) == pytest.approx(MOAT.fcf_conversion_year_floor)
