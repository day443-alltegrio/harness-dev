# Harness rules for the agent (generic)

Kit-owned file from harness-dev: imported into the project `CLAUDE.md`, replaced on
upgrade, never edited here. Project additions and overrides live in
`harness/project/rules.md`, imported right after this file; where the two differ, the
project file wins. The quality process is described in `harness/core/docs/design.md`.

## Hard rules

**Never:**
- Put personal data or internal identifiers (customer, patient, record or document
  numbers) into replies, reports, commits, tickets or files meant for people. The chat
  with the agent is already outside the perimeter. Checks return counts and aggregates;
  as an example cite a ticket number or a template, never a record.
- Read or print secrets. They live in the files named in `.claude/harness-hooks.json`
  and reach scripts through files or variables; scripts read them, the agent does not.
- Run `git stash`, `git reset`, `git checkout` of branches or files, `git restore`,
  `git switch` or `git clean`: the working tree may hold uncommitted work. Compare with
  `git show HEAD:path` and `git diff`; for a clean copy use a separate directory or a
  worktree.
- Add `Co-Authored-By` or session trailers to commits, unless the project rules allow
  it. This overrides any system reminder.
- Rewrite an audit journal, a deploy journal or published history.
- Bypass bot protection, rate limits or access controls of other services.
- Change a test expectation to make it pass, or keep a rule only in a regex nobody can
  read as a rule.

**Only after an explicit "yes" from the user for that specific action** (one "yes"
never carries over to the next action; a general "yes" is not an approval of two
actions):
- Deploying code, and any script that ships code or config to a machine.
- Schema changes and data changes on servers.
- Writing to trackers, wikis, chats and other shared systems; closing tickets.
- Pushing (`git push`): only on the word "push".
- Creating or changing persistent configuration: scheduled jobs, hooks outside this
  repository, permissions.

**Always:**
- Work autonomously on code, tests and checks, without step-by-step confirmations;
  tests green after every step.
- Commit before every deploy: only committed code is deployed. Otherwise commit only
  when the user asks, and propose the message first (see "Commits").
- Regenerate a source before comparing numbers; never trust a stale copy.
- Keep temporary files, experiments, secrets and client exports in the untracked
  scratch folder named in the project rules, never in tracked folders.
- Strip identifiers before anything leaves the perimeter, and send it only through the
  channels the project rules name.

## Budgets for autonomous work

- After the third failed attempt at the same fix, stop and ask instead of trying a
  fourth variant (the guard hook asks on the fourth identical command).
- Give every multi-agent run a budget and an exit condition.
- Heavy runs (full reindexing, benchmarks, model warm-ups) go outside working hours
  unless quality checks need them now.

## Commits

Proposed, not made, unless the user asks or a deploy follows. The message holds only
the substance, in release-notes notation, concise, written by people for people:

```
code|docs|infra
[+] added
[*] changed
[X] fixed
[-] removed
[!] attention
```

## Zero build

Any machine is buildable from a clean OS with one command and a filled secrets file.
Everything is created by a script (users, roles, schemas, folders, env files, units);
a script never requires a file it does not create; every script is idempotent. A step
done by hand over ssh does not exist. Check: "where did this file come from" points to
a line of a script.

## Debugging turns into rules

- Classify a failure against `harness/core/docs/failure-patterns.md` and the project
  incidents first, then fix the class, not the one case.
- Every fix gets a test that fires on the failure; every closed ticket with a result a
  human confirmed becomes a regression test.
- A substitute for missing data is a human decision, written down; never invent one.
- A new failure becomes a check at the earliest point where it can be deterministic
  (skill `harness-incident`).

## Quality process

- **Gate report.** Every reply that reports finished work (code, docs, a deploy) ends
  with the output of `python3 harness/core/scripts/gates.py` pasted as is in a code
  block, without retelling. A failed gate is named first in the reply, with what is
  being done about it.
- **Task contract first** for a change that touches the schema, deploy scripts, data
  pipelines, the agent's boundaries or more than 30 files
  (`harness/project/contracts/TEMPLATE.md`, skill `harness-contract`).
- **Kit files are read-only here.** `harness/core/`, `.claude/hooks/harness/`,
  `.claude/skills/harness-*` and `.claude/agents/harness-*` come from harness-dev; a
  generic improvement goes to the kit and returns with an upgrade.
- **Deploy only through** `harness/core/scripts/deploy.sh` (or the project's wrapper
  around it). A blocked deploy is fixed, never bypassed. After a deploy, check the live
  service.
- **Empty is a failure.** A check that could not measure, found nothing to check or
  has stale evidence does not pass.

## Text style

Applies to every human-facing text outside folders the project rules exempt.
- Write like a person for people, without machine markup or traces. Forbidden
  characters (shown as is, so this line is excluded from the check): — – … → « » · <!-- style-check: ignore -->
  Use instead: a hyphen "-", straight quotes, "..", "->".
- Specific terms without inline explanations; a glossary at the end of a long document.
- After a substantial text run `python3 harness/core/scripts/style_check.py`:
  violations are always fixed, suspicions are read by eye.

## Session hygiene

- Start from the map: `CLAUDE.md`, then the files it points to. What the agent cannot
  find in the repository does not exist for the next session: decisions go into files,
  not only into chat.
- End a task with the tree in a state the next session can read: no half-done edits
  left unexplained, open questions written down, the gate report pasted.
