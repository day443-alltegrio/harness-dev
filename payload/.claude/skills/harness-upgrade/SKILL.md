---
name: harness-upgrade
description: Upgrade the generic harness of this repository from harness-dev - dry run, read the changelog between versions, apply, resolve .harness-new conflicts, follow upgrade notes and migrations, run the checks. Use when the kit has a newer version or the user asks to update the harness.
---

# Upgrade the harness from harness-dev

The kit path is in `harness/harness.lock.json` (`source`); if it is missing or moved,
ask the user for it.

1. `python3 <kit>/harness.py status .`: installed version, kit version, local drift.
   Local edits of kit files must be resolved first: move each to harness-dev, or accept
   that the upgrade keeps it as a conflict.
2. `python3 <kit>/harness.py upgrade . --dry-run --verbose`: read the plan and every
   changelog section it prints. Entries marked `[!]` are upgrade notes: list the manual
   steps they require.
3. Show the user the plan in short: versions, files updated, conflicts, templates to
   review, migrations, manual steps. The upgrade changes `.claude/settings.json` and the
   agent's hooks: ask for a "yes" before applying.
4. Apply: `python3 <kit>/harness.py upgrade .`.
5. For every `<file>.harness-new`: merge the kit version into the file (the kit version
   wins unless the local change is a project need that belongs in config), delete the
   `.harness-new`, run the upgrade again until it reports no conflicts.
6. For every "review" line: compare the project file with the new template in
   `harness/core/templates/` and carry over what the project needs (new settings keys
   have defaults; adding them is optional unless an upgrade note says otherwise).
7. Run `sh harness/core/scripts/run.sh --offline` and
   `python3 harness/core/scripts/gates.py`; fix project settings, never kit files.
   New or changed hooks load when Claude Code restarts: ask the user to restart.
   After a version that changes hooks or rules, offer a golden run (it calls the
   model): `python3 harness/core/scripts/golden_tasks.py`.
8. Do not commit without the user's "yes"; propose the message, e.g.
   `infra` / `[*] harness 0.1.0 -> 0.2.0: <the main changes>`.
