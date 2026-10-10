"""Oráculo STREAMLIT-ALIGN: un solo juego de versiones para el CI, Docker y el venv.

Hasta 2026-10-10 había tres: el CI instalaba ``requirements-dev.txt`` por rangos
(Streamlit 1.65.0), el Dockerfile el lock (1.61.1) y el venv local lo que había al
crearlo (1.57.0). El lock se compilaba sin ``--universal``, resuelto para macOS, y
omitía ``greenlet``, que SQLAlchemy 2.0 pide en Linux: ``docker build`` fallaba con
``--require-hashes`` (medido en arm64). Nadie lo vio porque ningún workflow construye
la imagen.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_lock_is_compiled_for_every_platform():
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    [recipe] = re.findall(r"^lock:\n((?:\t.*\n?)+)", make, flags=re.M)
    assert "--universal" in recipe


def test_ci_installs_the_lock_before_the_dev_tools():
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    lock = ci.index("pip install --require-hashes -r requirements.lock")
    dev = ci.index("pip install -r requirements-dev.txt")
    assert lock < dev


def test_the_docker_image_installs_the_same_lock():
    docker = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in docker


def test_the_lock_carries_markers_for_more_than_one_platform():
    """Un lock resuelto para una sola plataforma no tiene marcadores de entorno."""
    lock = (REPO / "requirements.lock").read_text(encoding="utf-8")
    assert re.search(r"^[a-z0-9_.-]+==\S+ ; ", lock, flags=re.M)
