# harness-dev

A generic, versioned harness for repositories developed with coding agents (Claude Code
first): agent rules, guard and Stop hooks, quality gates with a one-table report,
preflight and a gated deploy, task contracts, a failure catalog that turns every
failure into a check, skills and reviewer subagents, budgets, telemetry, and the
research behind it. Extracted from a production pilot and anonymized.

**With an agent:** say "from `/path/to/harness-dev` deploy the generic harness in my
repository `/path/to/repo`". The agent follows [ADOPT.md](ADOPT.md): dry run, your
"yes", install, configuration for your stack, checks, a proposed commit.

**By hand:**
```
python3 harness.py install /path/to/repo --dry-run   # see the plan
python3 harness.py install /path/to/repo
cd /path/to/repo && sh harness/core/scripts/run.sh --offline && python3 harness/core/scripts/gates.py
```
Then fill `harness/config/*.json` and `.claude/harness-hooks.json` (skill
`harness-setup` does it from the repository), commit with an adoption contract.

Requirements: git, Python 3.10+ (standard library only), POSIX sh. Optional: `uvx` for
pip-audit, shellcheck and bandit; `npm` for npm audit.

## What a project gets

| Part | Where in the project | Owner |
|---|---|---|
| Generic agent rules, imported by `CLAUDE.md` | `harness/core/rules.md` | kit |
| Design, gates, levels, failure patterns | `harness/core/docs/` | kit |
| Guard hook (deny or ask), Stop hook (fast checks before an answer ends) | `.claude/hooks/harness/` | kit |
| Gate table, preflight, deploy wrapper, deploy check, commit scanner, supply chain, context budget, doc coverage, style and syntax checks, telemetry, snapshot | `harness/core/scripts/` | kit |
| Tests of all of the above | `harness/core/tests/` | kit |
| Skills: setup, incident, contract, cleanup, upgrade | `.claude/skills/harness-*` | kit |
| Subagents: change reviewer, docs reviewer | `.claude/agents/harness-*` | kit |
| Settings of the checks, gate states, budgets, allowlists, coverage registry, deploy steps | `harness/config/` | project |
| Project rules, decisions, incidents, contracts, project tests | `harness/project/` | project |
| Hook settings (secret paths, hosts, deploy and publish commands, Stop checks) | `.claude/harness-hooks.json` | project |
| Hook wiring and deny rules | `.claude/settings.json` | merged |
| Map of the repository plus a block importing the rules | `CLAUDE.md` | project, block merged |
| Installed version and kit file hashes | `harness/harness.lock.json` | written by `harness.py` |

## Generic and project parts

The split is by path, so an update never has to guess:
- **Kit-owned** files are replaced on upgrade and never edited in the project. A local
  edit shows as drift in the gate table and as a conflict on upgrade; the fix goes to
  this repository and comes back with the next version.
- **Project-owned** files are created once from `harness/core/templates/` and never
  overwritten. When their template changes, the upgrade only says "review".
- **Merged**: `.claude/settings.json` gets missing hook entries and deny rules (nothing
  of the project is removed); `CLAUDE.md` gets one marked block with two `@imports`.
- **Extension, not edits**: projects customize through settings (`harness.json`,
  `harness-hooks.json`, `gates.json` with `command` gates), the deploy steps file,
  project tests and project rules. New settings keys always get defaults in code, so
  an older config keeps working.

## Versions and upgrades

- `VERSION` follows SemVer. MAJOR: the project must change something (always with a
  migration or an `[!]` upgrade note). MINOR: new checks or features, compatible
  settings. PATCH: fixes and docs.
- `CHANGELOG.md` has a section per version with `[+] [*] [X] [-] [!]` lines; `[!]`
  marks an upgrade step.
- `harness/harness.lock.json` in a project records the version, the kit commit, the
  config schema number and a sha256 per kit file as last written.
- `python3 harness.py status <repo>` shows the versions a project is behind, with their
  changelog, and any local drift. `upgrade` replaces only files whose hash still
  matches the lock; a locally changed file is kept and the new one is written next to
  it as `<file>.harness-new` (`--force` replaces it and keeps `<file>.harness-old`).
  Settings format changes run as numbered migrations, once each.
- Tag each release in git (`v0.1.0`).

## Gates

| Gate | What |
|---|---|
| QG0 | guard hook (destructive git, secrets, push, deploy, outbound, loops) and Stop hook |
| QG1 | harness tests, context budget, pinned dependencies, plugin and MCP allowlist |
| QG2 | preflight: committed code, branch, lineage, build stamp, contract, scanners, vulnerabilities |
| QG3 | deploy check on the target before the swap: API contract, tests, security tests |
| QG4 | candidate on a separate port (off by default, a trade-off) |
| QG5 | after the swap: service up, smoke checks |
| QG6 | data invariants (project counters) |
| QG7 | nightly snapshot |
| QG8 | scenarios of people tied to the code |

Adopt in levels: L0 rules and hooks, L1 local gates, L2 gated deploy, L3 data, docs
and metrics (`payload/harness/core/docs/design.md`, section 9).

## This repository

| Path | What |
|---|---|
| `harness.py` | install, upgrade, status (standard library only) |
| `ADOPT.md` | instructions for an agent asked to install, upgrade, check or migrate |
| `CLAUDE.md` | rules for working on the kit itself |
| `payload/` | everything a project receives, laid out as in the project |
| `tests/` | tests of `harness.py`; the payload tests run inside a fresh install (`check.sh`) |
| `check.sh` | all checks of the kit before a release |
| `research/` | the evidence behind the design, the pilot case study, periodic reviews |
| `prompts/harness-review.md` | the periodic review: trends, verdicts, improvements as a new version |
| `extras/claude-context/` | optional: export and restore of an agent's working context between machines |

## Keeping it current

Run `prompts/harness-review.md` (skill `/harness-review` in this repository) monthly
and after major model or tool releases. It reads the last review, researches what
changed, writes a dated verdict with a radar of practices to `research/reviews/`, and
implements the best few improvements as a new version on a review branch in a separate
worktree. A human reads the review and merges; projects then upgrade.
