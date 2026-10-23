---
name: harness-setup
description: Configure the installed generic harness for this repository - inspect the stack, fill harness/config/*.json and .claude/harness-hooks.json, set gate states, write the adoption contract, run the checks. Use right after harness.py install, or when the project's stack, deploy or data change.
---

# Configure the harness for this repository

The kit files are installed (`harness/harness.lock.json` exists). This skill fills the
project-owned settings from what the repository actually contains. Change only
project-owned files: `harness/config/`, `harness/project/`, `.claude/harness-hooks.json`
and the map part of `CLAUDE.md`. Never edit `harness/core/` or `.claude/hooks/harness/`.

## 1. Inspect (read only)

Find and note, with the file that proves each fact:
- languages, package managers, test runner and its command, linters;
- the default branch and the branch deploys go from;
- build outputs that are committed or rewritten by the build (generated paths);
- deploy scripts and commands (scripts, kubectl, helm, terraform, CI jobs);
- schema and migration folders, data pipelines;
- where secrets live (env files, secret folders, vaults) - names only, never contents;
- internal hosts the agent legitimately reaches (servers, registries);
- publishing tools (wiki, tracker, design, chat scripts);
- identifiers that must never land in git or chat (customer, patient, order, document
  numbers) and their formats - from code and schema, never from real records;
- the existing `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, `.mcp.json`, CI.

## 2. Fill the settings

- `.claude/harness-hooks.json`, section guard: `secret_dirs`, `secret_files`, `deploy`,
  `internal_hosts`, `publish`; section stop: add the project's fast checks (linter for
  undefined names, type check) with a timeout that keeps an answer under a minute.
- `harness/config/harness.json`: `project`, `deploy_branch`, `generated`,
  `build_stamp` (only if the build writes one), `contracts.risky` (schema, deploy,
  pipelines, boundaries), `scan.id_patterns` (regexes for the identifier formats, each
  tested on made-up values), `scan.name_detectors`, `supply_chain` apps and lock files,
  `deploy_check` (the OpenAPI command if the service has one, test glob and command,
  variables that switch tests to live systems, security test files).
- `harness/config/budgets.json`: measure first (`python3 harness/core/scripts/context_budget.py`),
  set limits with about 20% headroom.
- `harness/config/style.json`: scope (human-facing docs), excluded folders, languages.
- `harness/config/gates.json`: active only what runs now; for the rest the reason.
- `harness/config/deploy-hooks.sh`: only if the user wants the gated deploy now.

## 3. Write the project parts

- `harness/project/rules.md`: language, data, approvals, servers, exemptions.
- `harness/project/design.md`: level (L0..L3), gate table with reasons, trade-offs.
- `CLAUDE.md`: keep it a map; make sure the harness block with both imports is there.
- A contract for the adoption itself in `harness/project/contracts/`
  (`YYYY-MM-DD-harness-adoption.md`), all sections filled.

## 4. Verify

Run `sh harness/core/scripts/run.sh --offline` and
`python3 harness/core/scripts/gates.py`. A failing kit test after configuration means a
setting is wrong (or a kit bug: report it for harness-dev, do not patch core). Show
the gate table as is, name every non-pass gate and why.

## 5. Hand over

Do not commit without the user's "yes". Propose the commit message in the project's
format and list what the user must still decide (deploy hooks, nightly snapshot,
scenarios map, sandbox).
