# harness/core: kit-owned

Installed from harness-dev by `harness.py`. Every file here is replaced on upgrade and
listed with its hash in `harness/harness.lock.json`; do not edit them in the project.
A change made here shows up as drift in the gate table and as a conflict on the next
upgrade. Improve the kit instead, then upgrade.

| Path | What |
|---|---|
| `VERSION` | kit version installed here |
| `rules.md` | generic rules for the agent, imported by `CLAUDE.md` |
| `docs/design.md` | generic design: principles, gates, boundaries, levels, entropy |
| `docs/failure-patterns.md` | generic failure patterns and the kit checks for them |
| `scripts/` | gate table, preflight, deploy wrapper and deploy check, scanners, budgets, snapshot, data checks, regression cases, hook review, sandbox settings, golden tasks |
| `tests/` | tests of the kit checks, run with the project's own harness tests |
| `templates/` | sources of the project-owned files (created once, never overwritten) |
| `migrations/` | numbered config migrations, run once each by `harness.py upgrade` |
| `settings.fragment.json` | what `harness.py` merges into `.claude/settings.json` |

Project-owned counterparts: `harness/config/` (settings), `harness/project/` (rules,
decisions, incidents, contracts, tests), `.claude/harness-hooks.json` (hook settings).
