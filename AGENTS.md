# AGENTS.md — Retirement Advisor

Project rules for Grok Build (and compatible agents). Keep this file short; deep context lives in `docs/CONTEXT.md`.

## Before any plan or code

1. Read `docs/CONTEXT.md` in full (architecture, standards §5, feature status §6, limitations §8).
2. Treat `config.py` as the single source of truth for thresholds, profiles, and tunables. Never hardcode analysis numbers in feature code.
3. If touching AI prompts or decision logic → also read `analysis/prompts.py` and `analysis/ai_analyzer.py`.
4. Start non-trivial work in **Plan Mode**. Wait for explicit approval before writing or structural edits.

At the start of a substantive response, include:
```
✅ He leído CONTEXT.md actualizado
```

## Commands (use the project venv)

```bash
make test          # ./venv/bin/pytest tests/ -q  (creates venv if needed)
make lint          # ruff check .
make check         # lint + test (CI parity)
make lock          # regenerate requirements.lock (hashes, Python 3.11)
./venv/bin/python3 scripts/refresh_context.py   # helper for CONTEXT.md updates
streamlit run dashboard/app.py                  # or: make run / ./run.sh
```

Prefer `./venv/bin/python3` / `make *` over system `python3`.

## Coding standards (hard rules)

- **Config-driven**: new thresholds → `config.py` dataclasses + module-level singletons (`THRESHOLDS`, `MONTE_CARLO`, `OPTIMIZER_PROFILES`, …).
- **Dashboard cache**: `@st.cache_data`; pass simulation params as **tuples** (not lists) so Streamlit can hash them.
- **AI config in UI**: use `_get_ai_config()` from `dashboard/shared.py`.
- **Logging**: `from loguru import logger` — no `print()` / stdlib `logging`.
- **SQLite**: SQLAlchemy only — no raw SQL.
- **No async** unless explicitly discussed.
- **Dependencies**: edit `requirements.txt` (ranges), then `make lock`. Never hand-edit `requirements.lock`.
- **Dead deps**: do not add packages that nothing imports (`TestNoDeadDependencies` guards this).
- **PII**: never commit `data/user_preferences.json` or `.env`. Template is `data/user_preferences.example.json`.

## Financial / motor changes (critical)

When changing math in `portfolio/`, `analysis/scoring.py`, withdrawal/decumulation, optimizer expected returns, or backtest metrics:

1. Write or update an **oracle test** first (`tests/test_engine_oracles.py`, `tests/test_withdrawal_oracle.py`) that compares the vectorized code against a slow reference written from the *financial definition*, not from the current production source.
2. Do **not** seed test data with `hash()` (process-randomized). Use `zlib.crc32(s.encode())`.
3. Prefer opt-in flags so the default path stays **byte-identical** to the previous baseline when the new feature is off.
4. Run `make test` before claiming done.

LLM layers interpret and narrate; they must not become the calculation engine. The no-AI path must always produce a valid portfolio and actionable core.

## Docs hygiene

- Large feature or architecture change → update `docs/CONTEXT.md` (use `scripts/refresh_context.py` for §7/§9 drafts).
- New/removed `.md` under root or `docs/` → update the canonical table in `docs/INDEX.md` and run `scripts/check_doc_catalog.py` if available.
- Canonical AI onboarding path remains `docs/PROMPT_INSTRUCTIONS.md` (points here and to CONTEXT).

## Skills in this repo

Project skills live under `.grok/skills/`. Prefer invoking them for repeatable workflows instead of re-deriving the procedure:

- `/verify` — lint + test the right way
- `/refresh-context` — update CONTEXT after a large change
- `/engine-change` — safe protocol for financial-motor edits

## Out of scope reminders

This is a **local single-user** Streamlit app, not a multi-tenant SaaS. Do not introduce auth, multi-user DB, or server-side accounts unless the user explicitly asks for a product pivot.
