---
name: refresh-context
description: Update docs/CONTEXT.md and the docs catalog after a large feature, config change, or architecture edit. Use when the user finishes a phase, asks to refresh context, or when AGENTS.md requires a CONTEXT update.
when-to-use: refresh context, update CONTEXT.md, maintain docs, after phase, MAINTENANCE
---

# Refresh project context docs

## Goal

Keep `docs/CONTEXT.md` accurate so every future agent session starts with truth.

## When required

- Completed a large feature or roadmap phase
- Changed important thresholds / new config dataclasses in `config.py`
- Added or removed a key module
- Architecture or data-flow change

## Steps

1. Read `docs/MAINTENANCE.md` for the full process.
2. Run the helper (drafts §7 config and §9 recent changes):

```bash
./venv/bin/python3 scripts/refresh_context.py
```

3. Manually review and merge the generated blocks into `docs/CONTEXT.md` (do not blind-overwrite narrative sections).
4. If you added/removed a markdown file under root or `docs/`:
   - Update the **canonical table** in `docs/INDEX.md`
   - Run `./venv/bin/python3 scripts/check_doc_catalog.py` if present
5. Keep role tags correct (`living-guide`, `methodology`, `historical-audit`, `ideation`, etc.).
6. Do **not** treat `docs/ROADMAP.md` as open backlog — it is a diary of **shipped** phases. Current feature status lives in `docs/CONTEXT.md` §6.

## Done criteria

- CONTEXT §6/§7/§8/§9 reflect reality
- INDEX catalog matches files on disk
- No contradictory “pending” claims for work already merged
