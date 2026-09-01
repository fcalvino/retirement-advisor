"""The repo declares a Streamlit theme (backlog N3).

``99_PRIORIZACION.md`` listed dark mode + contrast + readable type as a quick
win. There was no ``.streamlit/config.toml``, so the app inherited whatever
Streamlit shipped and the local ``run.sh`` path even sent usage stats (Docker
already turned them off via env).

This oracle is the file, not a screenshot: parseable TOML, a ``[theme]`` with
the colours Streamlit actually reads, body text vs background at WCAG AA
(≥ 4.5:1), and telemetry off. No runtime toggle, no Plotly palette — those
are other ideas.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOML_PATH = ROOT / ".streamlit" / "config.toml"
GITIGNORE = ROOT / ".gitignore"

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
_THEME_KEYS = (
    "base",
    "primaryColor",
    "backgroundColor",
    "secondaryBackgroundColor",
    "textColor",
    "font",
)


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    h = value[1:] if value.startswith("#") else value
    return int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0


def _lin(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture(scope="module")
def theme_cfg():
    if not TOML_PATH.is_file():
        pytest.fail(f"falta {TOML_PATH.relative_to(ROOT)} — N3 no está cerrado")
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover — CI is 3.11+
        import tomli as tomllib  # type: ignore
    with TOML_PATH.open("rb") as fh:
        return tomllib.load(fh)


class TestThemeFileExistsAndIsTracked:
    def test_config_toml_lives_at_the_app_root(self):
        assert TOML_PATH.is_file(), (
            "Streamlit lee .streamlit/config.toml desde el cwd de run.sh / Docker"
        )

    def test_gitignore_does_not_drop_the_theme(self):
        text = GITIGNORE.read_text(encoding="utf-8")
        dropped = [
            line.strip()
            for line in text.splitlines()
            if line.strip() in {".streamlit", ".streamlit/", ".streamlit/*", "**/.streamlit/**"}
        ]
        assert not dropped, f".streamlit está gitignoreado: {dropped}"


class TestThemeSection:
    def test_has_theme_keys(self, theme_cfg):
        theme = theme_cfg.get("theme") or {}
        missing = [k for k in _THEME_KEYS if k not in theme]
        assert not missing, f"[theme] incompleto, faltan: {missing}"

    def test_base_is_light_or_dark(self, theme_cfg):
        assert theme_cfg["theme"]["base"] in {"light", "dark"}

    def test_colors_are_hex(self, theme_cfg):
        theme = theme_cfg["theme"]
        for key in (
            "primaryColor",
            "backgroundColor",
            "secondaryBackgroundColor",
            "textColor",
        ):
            assert _HEX.match(str(theme[key])), f"{key}={theme[key]!r} no es #RRGGBB"

    def test_body_contrast_meets_wcag_aa(self, theme_cfg):
        theme = theme_cfg["theme"]
        ratio = _contrast(theme["textColor"], theme["backgroundColor"])
        assert ratio >= 4.5, (
            f"texto {theme['textColor']} sobre {theme['backgroundColor']} "
            f"da {ratio:.2f}:1; WCAG AA del cuerpo pide 4.5:1"
        )


class TestTelemetryOff:
    def test_local_run_does_not_phone_home(self, theme_cfg):
        browser = theme_cfg.get("browser") or {}
        assert browser.get("gatherUsageStats") is False, (
            "run.sh no setea STREAMLIT_BROWSER_GATHER_USAGE_STATS; "
            "el toml tiene que apagarlo"
        )
