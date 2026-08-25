---
name: verify
description: Run project lint and tests with the correct venv and make targets. Use when finishing a change, before claiming work is done, or when the user asks to check / test / verify / CI parity.
when-to-use: verify, run tests, make check, pytest, ruff, CI, before merge
---

# Verify (lint + tests)

## Goal

Confirm the working tree matches CI expectations without inventing alternate commands.

## Steps

1. From the repo root, prefer Make targets (they create the venv if missing):

```bash
make lint
make test
# or both:
make check
```

2. If Make is unavailable, use the project venv explicitly:

```bash
./venv/bin/ruff check .
./venv/bin/python3 -m pytest tests/ -q
```

3. For a focused run after a module change:

```bash
./venv/bin/python3 -m pytest tests/test_<module>.py -v --tb=short
```

4. Network-dependent tests should already mock `data.fetcher.get_history` / crypto fetchers. Do not disable mocks to “make green”.

5. Report:
   - command(s) run
   - pass/fail counts
   - first failing test name + short failure reason if any

## Done criteria

- `ruff check .` clean (or only pre-existing issues explicitly called out)
- pytest green for the scope you claimed
- no new hard-coded thresholds outside `config.py`
