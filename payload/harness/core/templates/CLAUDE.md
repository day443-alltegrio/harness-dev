# CLAUDE.md

<Project name>: <one sentence: what the system does and for whom>.

Keep this file a map of about 100 lines: what lives where, which commands to run, where
the rules are. Details belong in `docs/` and are linked from here. The harness rules are
imported below; project rules are in `harness/project/rules.md`.

## Repository map

| Path | What |
|---|---|
| `src/` | <service code> |
| `tests/` | <tests> |
| `docs/` | <architecture, decisions, scenarios> |
| `harness/` | quality process: `core/` from harness-dev (read-only here), `config/` and `project/` of this project |

## Commands

| Task | Command |
|---|---|
| Tests | `<command>` |
| Build | `<command>` |
| Deploy | `sh harness/core/scripts/deploy.sh -m "[*] what changed"` (after a commit and the user's "yes") |
| Harness checks | `sh harness/core/scripts/run.sh` |
| Gate report | `python3 harness/core/scripts/gates.py` |
| Text style | `python3 harness/core/scripts/style_check.py [file]` |

## Architecture invariants

- <the few rules that must never break, each with the reason>

<!-- harness:begin - managed by harness-dev (harness.py); edit harness/project/rules.md instead -->
@harness/core/rules.md
@harness/project/rules.md
<!-- harness:end -->
