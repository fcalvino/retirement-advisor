---
name: engine-change
description: Safe protocol for changing financial/math engine code (Monte Carlo, withdrawals, optimizer returns, scoring, backtest metrics). Use before editing portfolio/ or core analysis math so correctness is validated by oracles, not self-comparison.
when-to-use: engine change, oracle, monte carlo, withdrawal, decumulation, optimizer math, scoring formula, backtest metrics, financial definition
paths: portfolio/**, analysis/scoring.py, analysis/fundamental.py, tests/test_engine_oracles.py, tests/test_withdrawal_oracle.py
---

# Engine change protocol

## Principle

Regression tests that only compare the new motor to the old motor **freeze bugs**. Validation requires an independent reference written from the financial definition (see audit D4 in CONTEXT §8).

## Protocol

1. **Specify the definition** in the plan (formulas, edge cases: zero capital, negative contribution as savings, absorbing ruin, weekly vs annual scaling).
2. **Write/extend the oracle first** in `tests/test_engine_oracles.py` and/or `tests/test_withdrawal_oracle.py`:
   - Slow, clear reference loop or closed form from the definition
   - Assert the production vectorized path matches within tolerance
   - Seed synthetic series with `zlib.crc32(symbol.encode())` — never `hash()`
3. **Prefer opt-in** at the motor API so the default path stays byte-identical when the new behavior is off (project pattern for drags, withdrawal strategies, realistic reference, etc.).
4. Implement the production change in `portfolio/` or analysis modules, reading tunables only from `config.py` singletons.
5. Run:

```bash
./venv/bin/python3 -m pytest tests/test_engine_oracles.py tests/test_withdrawal_oracle.py -v --tb=short
make test
```

6. Update `docs/CONTEXT.md` limitations / recent changes if the semantics user-visible numbers change.

## Anti-patterns

- “Tests still pass” after only updating snapshots of the old motor
- Hard-coding rates, haircuts, or bands outside `config.py`
- Letting LLM prompts redefine withdrawal or return math
- Claiming CAGR semantics when cashflows are present without labeling contributions

## Done criteria

- New/updated oracle fails on the pre-fix bug (if fixing) and passes after the fix
- Full suite green
- Opt-in default preserves previous baseline when flag off
