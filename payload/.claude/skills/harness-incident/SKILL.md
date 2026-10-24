---
name: harness-incident
description: Turn a failure into a harness rule - classify it against the failure patterns, add a deterministic check at the earliest point, prove it with a test that fires on the failure, record it in the coverage registry. Use after a bug, a bad deploy, a data error or an agent mistake that a check should have caught.
---

# A failure becomes a check

Input: what happened (symptom, where it was seen, how it was found). No personal data,
identifiers or secrets in anything this skill writes.

1. **Classify.** Read `harness/core/docs/failure-patterns.md` and
   `harness/project/incidents.md`. Pick the pattern (A1..A10, B1..B11, P...). If none
   fits, define a project pattern P<next> in the project patterns table: title, root
   cause, what catches it. Add a log row: date, what happened, pattern.
2. **Find the root, not the symptom.** One sentence: why nothing stopped it. Fix the
   class of failure, not the one case.
3. **Pick the earliest deterministic point**, in this order: guard or Stop hook
   (`.claude/harness-hooks.json`), a project test run by QG1, preflight, the deploy
   check, a data check (`harness/config/data-checks.json`, for data failures), the
   nightly snapshot. A behaviour a person confirmed becomes a regression case (skill
   `harness-regression`). An inferential check (a reviewer
   subagent) only where no deterministic one is possible.
4. **Write the test first.** In `harness/project/tests/test_project_<topic>.py`: one
   case reproducing the failure (the check fires) and one clean case (it stays
   silent). Run it and watch it fail before the check exists.
5. **Add the check** with a message that says how to fix, not only what broke. Prefer
   configuration (`harness/config/*.json`, `.claude/harness-hooks.json`) and project
   tests over new scripts. Never edit `harness/core/`: if the check is generic, write it
   up for harness-dev (step 7).
6. **Record it** in `harness/config/incident-coverage.json`: the check, where it runs,
   the test as `module.Class.method`, the status (covered only with a firing test) and
   what is still missing. Run `sh harness/core/scripts/run.sh --offline`.
7. **Generic?** If any project could hit this failure, add a short note for the kit:
   pattern, check, test idea, in the reply to the user (harness-dev applies it in a
   new version).
8. End with the gate report (`python3 harness/core/scripts/gates.py`).
