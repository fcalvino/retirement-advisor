"""P1 audit D13 — resolve_optimizer_profile maps names to ProfileConfig."""

from analysis.ai_analyzer import resolve_optimizer_profile
from config import AGGRESSIVE_PROFILE, CONSERVATIVE_PROFILE, MODERATE_PROFILE


class TestResolveOptimizerProfile:
    def test_key_lookup(self):
        assert resolve_optimizer_profile("aggressive").name == AGGRESSIVE_PROFILE.name
        assert resolve_optimizer_profile("conservative").max_position_pct == 8.0

    def test_display_name_lookup(self):
        assert resolve_optimizer_profile("Agresivo").max_position_pct == AGGRESSIVE_PROFILE.max_position_pct
        assert resolve_optimizer_profile("Moderado").min_positions == MODERATE_PROFILE.min_positions
        assert resolve_optimizer_profile("Conservador").name == CONSERVATIVE_PROFILE.name

    def test_fuzzy_fragments(self):
        assert resolve_optimizer_profile("perfil agresivo").max_crypto_pct == AGGRESSIVE_PROFILE.max_crypto_pct
        assert resolve_optimizer_profile("moderate risk").name == MODERATE_PROFILE.name

    def test_unknown_defaults_conservative(self):
        cfg = resolve_optimizer_profile("totally-unknown-xyz")
        assert cfg.name == CONSERVATIVE_PROFILE.name

    def test_empty_defaults_conservative(self):
        assert resolve_optimizer_profile("").name == CONSERVATIVE_PROFILE.name
        assert resolve_optimizer_profile(None).name == CONSERVATIVE_PROFILE.name

    def test_aggressive_differs_from_hardcoded_old_defaults(self):
        """Old hardcodes were max_pos=8, min_pos=8, max_vol=18 — aggressive must differ."""
        cfg = resolve_optimizer_profile("Agresivo")
        assert cfg.max_position_pct == 18.0
        assert cfg.min_positions == 5
        assert cfg.max_volatility_pct == 25.0
        assert cfg.max_crypto_pct == 10.0
