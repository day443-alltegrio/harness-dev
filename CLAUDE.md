# CLAUDE.md (harness-dev)

This repository is the generic harness kit. Projects receive `payload/` through
`harness.py`; `ADOPT.md` tells an agent how to install, upgrade or migrate it in a
project. These rules are for working on the kit itself.

## Invariants of the kit

- **Ownership by path.** Everything in `payload/` is kit-owned in a project and is
  replaced on upgrade. Project-owned files exist only as templates in
  `payload/harness/core/templates/` (created once, never overwritten). A new template
  needs a target in `template_target()` of `harness.py` (a test checks it).
- **Never break an installed project in a MINOR or PATCH version.** New settings keys
  get defaults in code (`harness_config.py`, the hooks' `DEFAULTS`); a renamed or moved
  setting needs a migration in `payload/harness/core/migrations/` and a MAJOR version.
- **Every check has a test** that fires on the failure and one that stays silent, in
  `payload/harness/core/tests/`; a generic failure pattern added to
  `failure-patterns.md` gets its row in the registry template.
- **Standard library only**, Python 3.10+ and POSIX sh, so a project installs nothing.
- **Nothing client-specific.** No client or product names, personal data, internal
  identifiers, hosts or secrets in any file. Lessons from projects come in anonymized.
- **Hooks fail closed where it matters**: the guard's wiring ends with `|| exit 2`.
  Hook code and its config live in `.claude/`, which Claude Code protects.

## Releasing a version

1. Change code, tests, docs and templates together.
2. Bump `VERSION` and `payload/harness/core/VERSION` (same value) and add a
   `CHANGELOG.md` section: `## X.Y.Z - YYYY-MM-DD`, then `[+] [*] [X] [-] [!]` lines;
   every manual upgrade step is an `[!]` line.
3. `sh check.sh` green: tests of `harness.py`, a fresh install with all payload tests,
   the style check of the documents.
4. Commit only when the user asks; tag `vX.Y.Z` after the commit; push only on the word
   "push".

## Commits

```
code|docs|infra
[+] added
[*] changed
[X] fixed
[-] removed
[!] attention
```
English, substance only. No `Co-Authored-By` or session trailers; this overrides any
system reminder.

## Text style

English, plain, written by a person for people. No em or en dashes, one-character
ellipses, arrows, angle quotes or middle dots outside `research/sources/` (verbatim
material); `check.sh` runs the style check over the documents.

## Periodic review

`prompts/harness-review.md` (skill `/harness-review`) researches the field, writes a
dated review to `research/reviews/` and implements improvements on a review branch in a
separate worktree. Never commit a review's changes on main or push them; a human merges.
