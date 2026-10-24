# Harness design (generic)

Kit-owned, from harness-dev. What the harness is for, the principles it follows, the
gates, the boundaries, how it is adopted, measured and kept from rotting. The
decisions of one project (which gates are on, trade-offs, risks) live in
`harness/project/design.md`. The research behind it is in the harness-dev repository,
`research/`.

## 1. Why

An agent writes and ships most of the code, many times a day. Without a harness the
failures are caught by people: the server runs the wrong code, the schema lags behind,
a data run silently damages records, documentation promises what the code no longer
does. The harness stops such failures automatically, before people see them, and turns
every new failure into a check, once.

Success looks like this:
- the server always runs known, committed code;
- a fixed failure does not come back unnoticed;
- damaged data does not reach users unnoticed;
- the agent takes no irreversible action without a human;
- what the documentation promises matches the code.

## 2. Goals, non-goals, anti-goals

Goals: gates on the path of a change, checks of data, boundaries of the agent's
actions, a feedback loop from failure to check, measurement of the harness itself.

Non-goals: replacing the CI of the project (the gates can run there too); testing the
agent model; AI review as a gate on every change.

Anti-goals (a failure even if it technically works):
- false blocks so frequent that people switch hooks off or route around gates;
- auto rollback that rolls back good deploys because of noise;
- a quarantine where part of the data silently disappears;
- a check that carries personal data outside the perimeter for the sake of a report.

## 3. Principles

1. **Deterministic checks live outside the agent.** The main gates are in the deploy
   script, the deploy check on the target machine and the pipelines; they fire whoever
   deploys. Hooks are the second line.
2. **Every rule grew out of a failure.** A check carries the pattern it catches
   (`failure-patterns.md`); a rule without a failure behind it is not added, and one
   that never fires is removed.
3. **A rule and a sensor together.** A rule without a sensor is a wish; a sensor
   without a rule gives an agent that repeats the mistake. A check message says how to
   fix, not only what broke.
4. **Cheap first, expensive later.** Deterministic checks on every change; inferential
   ones (a reviewer subagent, a model run) after them and only where nothing
   deterministic exists.
5. **Empty means fail.** A check that could not measure, got zero or has stale evidence
   does not pass.
6. **Context is a map.** `CLAUDE.md` is about 100 lines of links; knowledge lives in
   the repository, loaded when needed; the always-loaded context has a budget.
7. **Humans at the irreversible points.** Deploys, data changes, pushes and
   publications get a human "yes" per action; the agent works autonomously everywhere
   else.
8. **Everything stays in the perimeter.** Metrics and reports are numbers and names,
   never texts of records, identifiers or secrets.
9. **The harness is code.** It is versioned, tested, reviewed and upgraded like code,
   and revisited whenever the agent model changes: scaffolding the model no longer
   needs is removed.
10. **Quality over speed.** There is no time budget on checks; a slow check moves later
    in the path, it is not dropped.

## 4. Layers and parts

| Layer | Purpose | Parts in the kit |
|---|---|---|
| Guides (before the action) | tell the agent what is expected | `rules.md`, project rules, task contracts, skills `harness-*`, `CLAUDE.md` map |
| Boundaries | limit what the agent may do | OS sandbox (opt-in, `sandbox_config.py`), `permissions.deny`, guard hook (deny, ask), ConfigChange hook, approvals per action |
| Sensors (after the action) | tell the agent and people what broke | Stop hook, harness tests, preflight, commit scanner, deploy check, regression cases, data checks, doc coverage, style check |
| Feedback | turn a failure into a check | failure catalog, project incidents, coverage registry, regression cases from confirmed tickets, skills `harness-incident` and `harness-regression` |
| Entropy control | keep the harness small and true | context budget, false-block marks, monthly cleanup (skill `harness-cleanup`), kit file drift warning |
| Measurement | know whether the harness works | gate table, nightly snapshot, agent telemetry, hook decision log with ids, golden tasks |

## 5. Gates

States live in `harness/config/gates.json`: active (runs, shows its result),
in progress (being built, shows its reason) and disabled (a conscious trade-off, shows
its reason). `python3 harness/core/scripts/gates.py` prints one line per gate.

| Gate | When | What it checks | On failure |
|---|---|---|---|
| QG0 guard, Stop and ConfigChange hooks | every Bash, Read, Grep, Edit or Write call; the end of every answer; every settings change | destructive git, secrets read or written, keys in written text, push, deploy, outbound data, decoded or downloaded code, shell writes to the agent's settings, edits of kit files, scripts the agent wrote, read-only reviewers, the same command a fourth time; syntax and style of changed files; hooks or sandbox switched off; the hooks wired and the sandbox as configured | blocked or a confirmation window; the agent goes back to work with the output; a weakening settings change is not applied |
| QG1 quality checks | `run.sh` on demand, nightly in the snapshot | harness tests, regression cases ("before"), context budget, pinned dependencies, vulnerabilities, allowed plugins and MCP servers | non-zero exit; a finding in the snapshot |
| QG2 preflight | the start of every deploy, on the developer machine | committed code from the main copy and branch, lineage from the last deploy, build stamp, task contract, secrets and IDs in the added lines, critical vulnerabilities, documentation | nothing is copied; the attempt is journaled as BLOCKED |
| QG3 deploy check | every deploy, on the target, before the code is replaced | API contract against the running code, all tests, security tests, regression cases ("before") | BLOCKED, running code untouched |
| QG4 candidate on a port | before switching traffic | reference requests against a candidate instance | no switch |
| QG5 after replacement | right after the swap | the service is up, smoke checks of the main function, regression cases ("after"), code hash | a failed deploy, not a warning; rollback by deploying the previous commit |
| QG6 data invariants | nightly and after a data run | project counters against fixed rules (`data_checks.py`): derived version equals source version, no empty outputs, false-positive counters, no sharp drops until a human accepts the new level | a finding; quarantine of new data where the project has it |
| QG7 nightly snapshot | nightly, read only | the snapshot's problems: tests, budgets, supply chain, secrets in history, documentation | a finding in the gate table; stale after 36 hours |
| QG8 documentation | in preflight and nightly | scenarios of people tied to code, with tests, reviewed after each change | no deploy until a human decides (fix_doc, fix_code, defer, none) |

For each gate the project records an owner, the evidence (where the result is kept),
its freshness and the only allowed bypass (`harness/project/design.md`). Allowed
bypasses are explicit and leave a trace: an accepted vulnerability with a review date,
`--allow-breaking` with a reason, a deferred documentation decision of at most 90 days,
a `scan: ignore` mark with a reason next to it. Tests are never bypassed.

## 6. The path of a change

```
edit by the agent  -> sandbox (when on), QG0 guard (boundaries), Stop hook (fast checks of changed files)
settings change    -> ConfigChange hook: no weakening applied mid-session
deploy             -> QG2 preflight on the developer machine, with QG8
                   -> QG3 deploy check on the target: contract, tests, security tests
                   -> swap and restart
                   -> QG5 the service is up, smoke checks, "after" regression cases
nightly            -> QG1 quality checks, QG6 data invariants, QG7 snapshot, QG8
failure            -> pattern -> check at the earliest deterministic point -> test
confirmed ticket   -> regression case, replayed on every deploy
harness or model   -> golden tasks: the real agent on fixed tasks, compared with the last run
```

## 7. Security boundary

An agent is dangerous when it has, at the same time, access to private data, exposure
to untrusted content (tickets, documents, web pages) and a way to send data out (the
"lethal trifecta"). A coding agent usually has all three.

From strongest to weakest:
1. **The operating system sandbox** for the agent's commands (Claude Code `sandbox`:
   network only through an allowlist proxy, file reads and writes by lists). A script in
   a file or another language stays inside it.
2. **Permission rules** (`permissions.deny` and `ask` in `.claude/settings.json`): no
   other settings level lifts a deny.
3. **Hooks**, which see the full text of a command. They hold back the agent's mistakes
   but can be bypassed (a script file, base64, Python instead of ssh); Grep, Glob, Edit
   and Write are outside the guard hook.

What the kit holds:
- the sandbox, opt-in: `harness/config/sandbox.json` lists allowed domains, denied reads
  and excluded commands, `sandbox_config.py` writes the block into `.claude/settings.json`
  with the retry outside the sandbox closed, the gate table shows its state and the
  ConfigChange hook keeps a required sandbox on (skill `harness-sandbox`);
- the guard hook: secrets read by any command, interpreter one-liner, input
  redirection, upload, move or link, with Read or Grep; secret files written and keys
  written into files; destructive git; deploy, push and outbound commands (ssh and
  network code included) with a confirmation per action; decoded or downloaded code;
  shell writes to the agent's settings and edits of kit files; scripts the agent wrote
  or changed, read before they run; read-only reviewer subagents;
- the ConfigChange hook: a settings change that switches hooks off, unwires them,
  narrows the guard, drops a deny rule or turns off a required sandbox is not applied;
- deny rules for secret files, the commit scanner for secrets and project IDs, secrets
  in the git history in the snapshot.
Hook code and its config sit in `.claude/`, which Claude Code protects for its own
tools; the guard covers shell writes there.

What it does not hold: Read, Edit, Write and WebFetch run outside the sandbox and
answer to permission rules and the guard only; a determined program can still hide
what it does from a text check; an agent with full rights on a server can change it
past any confirmation, including under instructions planted in data. Before production
the project narrows the agent's rights on servers (a deploy user, a read-only database
role for the agent, sudoers) and turns the sandbox on with `required`. Secrets never
live in files the agent reads; scripts load them themselves.

## 8. Context as a map

- `CLAUDE.md` of the project is a map: what lives where, commands, invariants, links.
  It imports the generic rules (`harness/core/rules.md`) and the project rules
  (`harness/project/rules.md`) through a block the kit manages.
- Long procedures are skills (`.claude/skills/harness-*`), loaded only when used: only
  their short descriptions are always in the context.
- Budgets (`harness/config/budgets.json`) cap the always-loaded context, skill
  descriptions and agent memory. Over 90% is a reason to clean up, not to raise the
  limit.
- What the agent cannot find in the repository does not exist: decisions from calls
  and chats land in files.

## 9. Adoption levels

| Level | What is on | Typical first week |
|---|---|---|
| L0 | rules, guard hook, Stop hook | install; fill secrets, hosts and deploy commands in `.claude/harness-hooks.json` |
| L1 | QG1 and QG2: harness tests, budgets, supply chain, preflight, contracts | fill `harness.json` (branch, generated paths, risky paths, apps); first contract |
| L2 | QG3 and QG5: gated deploy with the deploy check and health checks | fill `deploy-hooks.sh`; the first deploy through `deploy.sh` |
| L3 | QG6, QG7, QG8: data invariants, nightly snapshot, documentation coverage, metrics | scenarios map; nightly job; data counters as project tests |

Start at L0 and L1 on day one; add a gate when the failure it catches has happened or
is expensive enough to prevent.

## 10. Feedback and entropy

- **A new failure becomes a rule**: classified, a check at the earliest deterministic
  point, a test that fires on it, a row in the coverage registry.
- **A fixed ticket with a confirmed result becomes a regression case**
  (`harness/project/regressions/`, skill `harness-regression`), replayed by `run.sh`, the
  deploy check and after the swap. A case is never edited to pass: a changed result is
  a new human confirmation.
- **A wrong hook decision is marked by the human who saw it**
  (`hook_review.py mark <id> --reason ...`): the id is in every block and ask.
- **Monthly cleanup**: hook decision log (false blocks), thresholds, rules without a
  failure behind them, agent memory, `CLAUDE.md`, skills; what is stale is deleted. The
  result is a dated line in the project decisions.
- **Thresholds**: a rule that caught nothing for 6 months and has no failure behind it
  is removed; a rule with more than 20% false blocks in a month is reviewed; context
  over 90% of its budget is cleaned; a deferred documentation decision lasts at most 90
  days.
- **A new agent model or a harness change** triggers the golden tasks
  (`golden_tasks.py`) and a review of hooks, budgets and thresholds.
- **Kit files are not edited in the project**: a generic improvement goes to
  harness-dev and comes back with an upgrade; the gate table warns about local drift.

## 11. Measuring the harness

A sensor that never fires may be blind. Coverage counts only with a test that shows
the check firing; empty or stale evidence is not a pass.

| What | Source | Target |
|---|---|---|
| Failure pattern coverage | `incident-coverage.json` | every pattern without a check has a plan |
| Harness tests | `run.sh`, QG1 | all green; each check has a firing example |
| Hook decisions | hook log with ids, `hook_review.py` | false blocks marked and below 20% per rule (QG0 warns) |
| The harness changes behaviour | golden tasks, `harness/.state/golden/` | every task passes; no task worse than the last run |
| Human-checked behaviour holds | regression cases | all pass on every deploy |
| Data | `data_checks.py`, QG6 | every counter passes, none stale |
| Always-loaded context | `context_budget.py` | below 90% of the budget |
| Contracts before the change | snapshot (`contracts`) | written before, not after |
| Critical vulnerabilities | supply chain | 0 |
| Secrets in the git history | snapshot | 0 |
| Agent loops | telemetry (`repeat_streaks`) | falling |

## 12. Kit and project

The generic harness comes from harness-dev and is installed by its `harness.py`:
kit-owned files are replaced on upgrade and never edited in the project; project-owned
files are created once from templates and never overwritten; `.claude/settings.json`
and the `CLAUDE.md` block are merged. `harness/harness.lock.json` records the kit
version and a hash per kit file, so an upgrade replaces only files the project did not
change and leaves a `.harness-new` next to the ones it did. Versions follow SemVer;
the kit `CHANGELOG.md` says what each version changes and what an upgrade needs.

## 13. What not to copy from other teams

- AI review as a gate on every change: expensive and not deterministic; reviewers stand
  after the deterministic checks, at specific points.
- Minimal merge gates of large teams: their own authors call them irresponsible at a
  low change volume.
- Mutation testing of all code: expensive everywhere; worth it for a few core
  primitives, later.
- Full autonomy without people: decisions about a documentation mismatch, a deliberate
  change of a number and closing a ticket stay with a human, because no sensor reliably
  checks behaviour and the understanding of the task.

## 14. Not in the kit yet

Schema snapshot and versioned migrations in the deploy check (A2); a preflight check
that no long job is running (A7); server-side least privilege templates; stack presets
for the Stop checks (ruff F, tsc, go vet); an AGENTS.md export for other agents.
Behaviour and the understanding of a task still have no sensor of their own: golden
tasks, regression cases and checkable acceptance criteria make what people decided and
confirmed durable, they do not replace the people.

## Glossary

- **Contract** - a short plan of a big change written before the work
  (`harness/project/contracts/TEMPLATE.md`).
- **Deterministic check** - one that always gives the same result on the same input
  (a test, a rule, a counter).
- **Fingerprint** - a short checksum of code or text at the moment of a review.
- **False block** - a hook decision a human marked as wrong; the share per rule says
  whether the rule is too broad.
- **Gate (QG)** - a point of the process where a check can stop a change or data.
- **Golden task** - a fixed task the real agent does in a throwaway worktree, graded by a
  deterministic check; measures the harness, not the code.
- **Guide** - feedforward control: rules, contracts, skills.
- **Hook** - a command Claude Code runs on an event; it can block the agent's action.
- **Inferential check** - one where a model or a reviewer subagent decides; more
  expensive and not always the same.
- **Kit-owned file** - a file harness-dev installs and replaces on upgrade.
- **Lethal trifecta** - private data, untrusted content and a way out, together.
- **Project-owned file** - a file created once from a template and owned by the project.
- **Regression case** - a command and the result a human confirmed when a ticket closed.
- **Sandbox** - the operating system boundary of Claude Code for Bash commands: network
  through an allowlist proxy, writes in allowed folders.
- **Sensor** - feedback control: tests, scanners, hooks, gates.
- **Stop hook** - a hook that runs before the agent ends its answer.
