"""Reproducibility + PII guards (audit D5, D6).

D5 — a plan is a set of numbers someone retires on. Those numbers depend on the
build of numpy/scipy/pandas that produced them, so the environment is sealed
into the snapshot and can be re-checked later.

D6 — the user's real financial profile must not be versioned. These tests fail
if someone re-adds it to git, or if a fresh clone stops booting because the
tracked template drifted away from the dataclass.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from data.env_provenance import NUMERIC_LIBS, env_drift, format_drift, numeric_env
from data.plan_store import PlanSnapshot
from data.preferences import UserPreferences

REPO_ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ #
#  D5 — numeric environment provenance                                 #
# ------------------------------------------------------------------ #

class TestNumericEnv:
    def test_reports_python_and_numeric_libs(self):
        env = numeric_env()
        assert env["python"].count(".") == 2          # major.minor.patch
        for lib in NUMERIC_LIBS:
            # All three are hard dependencies — if one is missing the engine
            # cannot run at all, so absence here is a real failure.
            assert lib in env, f"{lib} version not captured"
            assert env[lib], f"{lib} captured as empty"

    def test_is_json_serializable(self):
        # It gets written straight into the plan JSON file.
        assert json.loads(json.dumps(numeric_env())) == numeric_env()

    def test_no_drift_against_itself(self):
        assert env_drift(numeric_env()) == {}

    def test_detects_a_bumped_library(self):
        saved = dict(numeric_env())
        saved["numpy"] = "0.0.1-ancient"
        drift = env_drift(saved)
        assert set(drift) == {"numpy"}
        was, now = drift["numpy"]
        assert was == "0.0.1-ancient"
        assert now == numeric_env()["numpy"]

    def test_unknown_env_is_not_reported_as_equal(self):
        # A plan saved before sealing has no environment recorded. That is
        # "unknown", and must not silently read as "matches".
        assert env_drift(None) == {}
        assert env_drift({}) == {}

    def test_missing_key_in_current_env_is_not_drift(self):
        # A lib recorded then but absent now yields no false "changed" claim.
        assert env_drift({"pandas-ta": "0.4.71b0"}, current={"numpy": "2.0.0"}) == {}

    def test_format_drift_is_empty_when_clean(self):
        assert format_drift({}) == ""

    def test_format_drift_lists_each_library(self):
        line = format_drift({"scipy": ("1.11.0", "1.17.1"), "numpy": ("1.24.0", "2.2.6")})
        assert "scipy 1.11.0→1.17.1" in line
        assert "numpy 1.24.0→2.2.6" in line
        assert line.index("numpy") < line.index("scipy")   # sorted, stable output


class _FakeOptResult:
    """Minimal duck-typed stand-in for an OptimizationResult."""
    tickers: list = []
    sector_weights: dict = {}
    profile_name = "Moderado"
    expected_return_pct = 7.0
    volatility_pct = 12.0
    sharpe_ratio = 0.5


class TestSnapshotSealsEnv:
    def test_from_session_seals_the_environment(self):
        snap = PlanSnapshot.from_session(name="Plan", opt_result=_FakeOptResult())
        assert snap.has_sealed_env()
        assert snap.lib_versions == numeric_env()
        assert snap.numeric_env_drift() == {}

    def test_old_snapshot_without_env_is_flagged_unknown(self):
        snap = PlanSnapshot(id="old", name="Viejo", created_at="", updated_at="")
        assert not snap.has_sealed_env()
        # Unknown must not masquerade as "no drift detected but verified".
        assert snap.numeric_env_drift() == {}

    def test_env_drift_is_independent_of_engine_version(self):
        """Formulas changing and libraries changing are separate signals.

        A plan built by the current engine on an older scipy is not "stale
        maths" — it is reproducible-unknown. Conflating them would either hide
        the library bump or nag about maths that never changed.
        """
        snap = PlanSnapshot.from_session(name="Plan", opt_result=_FakeOptResult())
        snap.lib_versions = {**snap.lib_versions, "scipy": "0.0.1-ancient"}
        assert not snap.is_engine_stale()
        assert "scipy" in snap.numeric_env_drift()

    def test_survives_a_json_roundtrip_through_the_store(self, tmp_path):
        from data.plan_store import PlanStore
        store = PlanStore(path=tmp_path / "plans.json")
        store.upsert(PlanSnapshot.from_session(name="Retiro 2045", opt_result=_FakeOptResult()))
        loaded = store.list()[0]
        assert loaded.lib_versions == numeric_env()
        assert loaded.numeric_env_drift() == {}


# ------------------------------------------------------------------ #
#  D5 — the lockfile                                                   #
# ------------------------------------------------------------------ #

class TestLockfile:
    LOCK = REPO_ROOT / "requirements.lock"

    def test_lockfile_exists(self):
        assert self.LOCK.exists(), "requirements.lock missing — run `make lock`"

    def test_every_requirement_is_hash_pinned(self):
        """No `>=` may survive into the lock, and every pin carries a hash.

        This is the property that makes two runs of the same plan comparable;
        a single unpinned transitive dep is enough to break it.
        """
        text = self.LOCK.read_text(encoding="utf-8")
        pins, unpinned = 0, []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("--hash"):
                continue
            if "==" in line:
                pins += 1
            elif ">=" in line or "<=" in line or line.startswith("~="):
                unpinned.append(line)
        assert not unpinned, f"unpinned entries in the lock: {unpinned[:5]}"
        assert pins > 20, f"lock looks truncated ({pins} pins)"
        assert "--hash=sha256:" in text

    def test_numeric_libs_are_pinned_in_the_lock(self):
        text = self.LOCK.read_text(encoding="utf-8")
        for lib in NUMERIC_LIBS:
            assert f"\n{lib}==" in f"\n{text}", f"{lib} not pinned in requirements.lock"


# ------------------------------------------------------------------ #
#  Dead dependencies                                                   #
# ------------------------------------------------------------------ #

def _imported_top_level_modules() -> set[str]:
    """Every top-level module the project's own source imports."""
    import ast
    skip = {"venv", ".venv", "__pycache__", ".git", "qa", "node_modules", "build", "dist"}
    found: set[str] = set()
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in skip for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


class TestNoDeadDependencies:
    """Every declared requirement must actually be imported somewhere.

    ``pandas-ta`` sat in requirements.txt long after its last import was deleted
    (see docs/DEAD_CODE_AUDIT.md). Nothing noticed, so its unpinned ``>=`` kept
    resolving upward until it demanded Python >=3.12 and quietly broke the 3.11
    leg of the support matrix — dragging numba and llvmlite along the whole
    time. ``pyyaml`` was dead the same way. A dependency nobody imports is a
    liability with no upside: it constrains the interpreter, enlarges the image,
    and widens the supply-chain surface.
    """

    # Distribution name on PyPI -> module name you actually import.
    DIST_TO_MODULE = {
        "python-dotenv": "dotenv",
        "pyyaml": "yaml",
        "pandas-ta": "pandas_ta",
        "beautifulsoup4": "bs4",
        "pillow": "PIL",
    }

    @staticmethod
    def _declared() -> list[str]:
        import re
        out = []
        for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9._-]+)", line)
            if m:
                out.append(m.group(1))
        return out

    def test_every_requirement_is_imported(self):
        imported = _imported_top_level_modules()
        dead = []
        for dist in self._declared():
            module = self.DIST_TO_MODULE.get(dist.lower(), dist.lower().replace("-", "_"))
            if module not in imported:
                dead.append(f"{dist} (import {module})")
        assert not dead, (
            "requirements.txt declares dependencies nothing imports: "
            f"{dead}. Remove them and run `make lock`."
        )

    def test_pandas_ta_stays_out(self):
        """Named guard: this one already cost us the 3.11 support leg once."""
        text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "pandas-ta" not in text and "pandas_ta" not in text
        assert "pandas_ta" not in _imported_top_level_modules()

    def test_lock_carries_no_dead_transitives_of_removed_packages(self):
        """numba/llvmlite only ever entered through pandas-ta."""
        lock = self.LOCK_TEXT()
        for gone in ("pandas-ta==", "numba==", "llvmlite=="):
            assert gone not in lock, f"{gone.rstrip('=')} is back in the lock"

    @staticmethod
    def LOCK_TEXT() -> str:
        return (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
#  D6 — personal data must not be versioned                            #
# ------------------------------------------------------------------ #

def _git_tracked(relpath: str) -> bool:
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relpath],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return out.returncode == 0


class TestNoPiiInGit:
    def test_real_preferences_file_is_not_tracked(self):
        assert not _git_tracked("data/user_preferences.json"), (
            "data/user_preferences.json is tracked again — it holds the user's real "
            "age, capital and savings. Run: git rm --cached data/user_preferences.json"
        )

    def test_gitignore_covers_it(self):
        ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "data/user_preferences.json" in ignored

    def test_example_template_is_tracked(self):
        assert _git_tracked("data/user_preferences.example.json"), (
            "the template must be versioned so a fresh clone can boot"
        )

    def test_other_runtime_json_stayed_ignored(self):
        # The D6 finding was that ONE runtime file slipped past a rule the
        # others already followed. Guard the whole family, not just the leak.
        for name in ("data/retirement_plans.json",
                     "data/plan_health_history.json",
                     "data/personal_book_convictions.json"):
            assert not _git_tracked(name), f"{name} became tracked"


class TestExampleTemplate:
    TEMPLATE = REPO_ROOT / "data" / "user_preferences.example.json"

    def test_template_carries_no_personal_data(self):
        data = json.loads(self.TEMPLATE.read_text(encoding="utf-8"))
        assert data["onboarded"] is False
        for field in ("age", "retirement_age", "current_capital", "monthly_savings"):
            assert float(data[field]) == 0.0, f"{field} leaks a real value"
        assert data["active_plan_id"] == ""
        assert data["watched_tickers"] == []

    def test_template_loads_into_the_dataclass(self):
        """A template that drifts from the dataclass breaks every fresh clone."""
        raw = json.loads(self.TEMPLATE.read_text(encoding="utf-8"))
        prefs = UserPreferences._from_raw(raw)
        assert prefs.is_onboarded is False
        # Every non-comment key should be a real field — otherwise the template
        # silently documents settings that no longer exist.
        known = set(UserPreferences.__dataclass_fields__)
        stray = [k for k in raw if not k.startswith("_") and k not in known]
        assert stray == [], f"template documents unknown prefs: {stray}"

    def test_fresh_clone_seeds_from_template(self, tmp_path, monkeypatch):
        import data.preferences as prefs_mod
        monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "user_preferences.json")
        loaded = UserPreferences.load()
        assert loaded.is_onboarded is False
        assert loaded.current_capital == 0.0

    def test_falls_back_to_defaults_when_template_unreadable(self, tmp_path, monkeypatch):
        import data.preferences as prefs_mod
        bad = tmp_path / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "user_preferences.json")
        monkeypatch.setattr(prefs_mod, "_PREFS_EXAMPLE_PATH", bad)
        assert UserPreferences.load() == UserPreferences.get_default()

    def test_real_file_still_wins_over_template(self, tmp_path, monkeypatch):
        import data.preferences as prefs_mod
        real = tmp_path / "user_preferences.json"
        real.write_text(json.dumps({"onboarded": True, "age": 41}), encoding="utf-8")
        monkeypatch.setattr(prefs_mod, "_PREFS_PATH", real)
        loaded = UserPreferences.load()
        assert loaded.age == 41
        assert loaded.is_onboarded is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
