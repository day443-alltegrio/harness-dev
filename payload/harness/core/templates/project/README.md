# Harness: quick reference

Project-owned quick reference for developers. The harness stops code, deploy and data
failures before people see them and turns each new failure into a check.

| What | Where |
|---|---|
| Generic design, gates, principles (kit, read-only) | `harness/core/docs/design.md` |
| Generic failure patterns (kit, read-only) | `harness/core/docs/failure-patterns.md` |
| Generic agent rules (kit, read-only) | `harness/core/rules.md` |
| Project rules for the agent | `harness/project/rules.md` |
| Project decisions, trade-offs, risks | `harness/project/design.md` |
| Project incidents and patterns | `harness/project/incidents.md` |
| Task contracts | `harness/project/contracts/` |
| Regression cases (closed tickets with a confirmed result) | `harness/project/regressions/` |
| Data checks (QG6), sandbox, golden tasks | `harness/config/data-checks.json`, `sandbox.json`, `golden-tasks.json` |
| Project harness tests (`test_project_*.py`) | `harness/project/tests/` |
| Settings of the checks | `harness/config/harness.json` |
| Gate states | `harness/config/gates.json` |
| Hook settings (guard, Stop checks) | `.claude/harness-hooks.json` |
| Hook decision log (ids, no command text), marks | `.claude/hooks/harness/log/` |
| Installed version and kit file hashes | `harness/harness.lock.json` |

## Commands

| Task | Command |
|---|---|
| All harness checks | `sh harness/core/scripts/run.sh [--offline]` |
| Gate report for the chat | `python3 harness/core/scripts/gates.py` |
| Preflight alone | `python3 harness/core/scripts/preflight.py` |
| Gated deploy | `sh harness/core/scripts/deploy.sh -m "[*] what changed"` |
| Nightly snapshot | `python3 harness/core/scripts/snapshot.py` |
| Data checks, nightly (QG6) | `python3 harness/core/scripts/data_checks.py` |
| Regression cases | `python3 harness/core/scripts/regressions.py --when all` |
| Mark a wrong hook decision | `python3 harness/core/scripts/hook_review.py mark <id> --reason "..."` |
| Hook decisions per rule | `python3 harness/core/scripts/hook_review.py report` |
| Sandbox state, apply | `python3 harness/core/scripts/sandbox_config.py --check` / `--apply` |
| Golden tasks (calls the model) | `python3 harness/core/scripts/golden_tasks.py` |
| Text style | `python3 harness/core/scripts/style_check.py` |
| Upgrade from the kit | `python3 <path to harness-dev>/harness.py upgrade .` |

## How to add a rule

1. Classify the failure (`harness/core/docs/failure-patterns.md`, then
   `harness/project/incidents.md`); a new pattern is a new row there.
2. Put the check at the earliest point where it is deterministic: guard or Stop hook,
   preflight, deploy check, data check, pipeline counter. A behaviour a person confirmed
   becomes a regression case (skill `harness-regression`).
3. Reproduce the failure as a test in `harness/project/tests/`; record it in
   `harness/config/incident-coverage.json`.
4. A big change starts with a contract; once a month, the cleanup (skill
   `harness-cleanup`).
5. A check that would help any project goes to harness-dev, not into `harness/core/`
   here.
