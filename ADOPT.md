# ADOPT: instructions for an AI agent

You were asked to install, upgrade, check or migrate the generic harness from this
folder in a repository, for example: "from <this folder> deploy the generic harness
process in my repository <path>". `<KIT>` below is this folder (the one holding
`harness.py`), `<REPO>` is the target repository. Use absolute paths: the session may
run in either folder.

Before anything else read, in `<KIT>`: `README.md` (ownership, versions) and
`payload/harness/core/docs/design.md`, sections 3, 5 and 9 (principles, gates, levels).

Ground rules for every task:
- Never edit files in `<KIT>` during an install or upgrade, and never edit kit-owned
  files in `<REPO>` (`harness/core/`, `.claude/hooks/harness/`, `.claude/skills/harness-*`,
  `.claude/agents/harness-*`).
- No commit, push or deploy without the user's explicit "yes" for that action.
  Installing changes the agent's own settings in `<REPO>`: get a "yes" first.
- Never read secrets; write no personal data or internal identifiers anywhere.
- The project's existing rules win over this file where they conflict; say so.

## Install

1. **Look.** `<REPO>` must be a git repository. Note uncommitted changes, especially to
   `CLAUDE.md` and `.claude/settings.json` (the install merges into both). If
   `harness/harness.lock.json` exists, this is an upgrade, not an install. If the repo
   already has a hand-made harness (its own hooks, gate scripts, failure catalog), go to
   "Migrate a hand-made harness".
2. **Dry run.** `python3 <KIT>/harness.py install <REPO> --dry-run --verbose`. Tell the
   user in a few lines: kit version, how many kit files, which project files will be
   created, what is merged into `.claude/settings.json` (guard and Stop hooks, deny rules
   for secret files, the ConfigChange hook) and `CLAUDE.md` (a block with two imports).
   Mention the effect: the agent will be asked before deploys, pushes, outbound uploads,
   edits of its own settings and of kit files, blocked from reading secrets and from
   destructive git commands, checked before it ends an answer, and settings changes that
   switch the hooks off will not apply mid-session.
3. **Install** after the "yes": `python3 <KIT>/harness.py install <REPO>`.
4. **Configure.** Follow `<REPO>/.claude/skills/harness-setup/SKILL.md` (installed by
   step 3): inspect the stack, fill `harness/config/*.json` and
   `.claude/harness-hooks.json`, write `harness/project/rules.md` and `design.md`, the
   adoption contract, keep `CLAUDE.md` a map. Aim for level L1 (design.md, section 9);
   L2 only if the user wants the gated deploy now.
5. **Verify** in `<REPO>`: `sh harness/core/scripts/run.sh --offline` and
   `python3 harness/core/scripts/gates.py`. Expected right after an install: QG0
   unknown until the first hook runs in a Claude Code session in `<REPO>`; QG1 pass; QG2
   fails until the install is committed together with its adoption contract; inactive
   gates show their reasons. QG0 fails when the hooks are not wired or are switched off.
   Any other failure is a setting to fix (or a kit bug to report, never patched in
   `harness/core/`).
6. **Hand over.** Report: version, level, active gates, what still needs the user
   (deploy hooks, nightly snapshot and data checks, scenarios map, sandbox, a first
   golden run once the install is committed: it calls the model), the gate table as is. Propose
   the commit, for example:
   ```
   infra
   [+] Generic harness <version> from harness-dev: guard and Stop hooks, preflight, gate table, task contracts, failure catalog
   [+] Project settings of the harness, adoption contract
   ```
   New hooks load when Claude Code starts in `<REPO>` (restart the session, or review
   them in `/hooks`); on another machine the user accepts the project settings once.

## Upgrade

1. `python3 <KIT>/harness.py status <REPO>`: installed version, versions behind with
   their changelog, local drift.
2. Follow `<REPO>/.claude/skills/harness-upgrade/SKILL.md`: dry run, changelog and
   upgrade notes, "yes", apply, resolve `.harness-new` conflicts, review changed
   templates, run the checks, propose the commit.

## Check

`python3 <KIT>/harness.py status <REPO>`, then in `<REPO>`
`sh harness/core/scripts/run.sh --offline` and `python3 harness/core/scripts/gates.py`.
Report versions behind, drift, unresolved conflicts and every non-pass gate with its
reason. Change nothing.

## Migrate a hand-made harness

For a repository that grew its own harness before the kit existed (hooks in
`.claude/hooks/`, gate scripts, a failure catalog, contracts):
1. Inventory it: every hook rule, check, script, config and document, and what each
   catches. Map each to the kit: same (drop the local copy), kit has it differently
   (keep the stricter behaviour as project config or a project test), project-only
   (keep as a project test or config), generic and missing from the kit (write it up for
   harness-dev).
2. Agree the plan with the user, then install the kit (it never overwrites existing
   files: a clash becomes a `.harness-new` for you to resolve).
3. Port project-specific checks into `harness/project/tests/` (`test_project_*.py`) and
   settings; move the project's incidents into `harness/project/incidents.md` with the
   generic pattern ids; keep the decision history in `harness/project/design.md`.
4. Switch the wiring (settings hooks, deploy script calls) to the kit versions, run all
   checks, and only then remove the old copies, in a separate change with its contract.

## Remove

Not automated. With the user's "yes": delete the kit-owned paths listed under
`managed` in `harness/harness.lock.json`, the harness block in `CLAUDE.md` and the hook
entries pointing to `.claude/hooks/harness/` in `.claude/settings.json`; keep the
project-owned files the user wants.
