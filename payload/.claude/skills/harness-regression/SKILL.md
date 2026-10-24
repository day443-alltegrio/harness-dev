---
name: harness-regression
description: Record a closed ticket whose result a human confirmed as a regression case in harness/project/regressions/, so the behaviour is replayed on every deploy - the command, the expected result, who confirmed it and how. Use when a ticket is closed with a confirmed result, or when the user says a fixed behaviour must never break again.
---

# A confirmed result becomes a regression case

A case records behaviour a person checked; it is not written for a fix nobody has
confirmed yet (that gets a test). Format and rules:
`harness/project/regressions/README.md`. No personal data, record identifiers or
secrets in a case: expected values are numbers or short phrases.

1. **The confirmation.** From the ticket: what was asked, what result the person
   accepted, who (a role or a team member) and when. Without it, stop and ask.
2. **The command.** The smallest command that reproduces the question on the code
   alone ("before") or against the running service ("after"). Prefer a project CLI or
   a test helper to a raw query; it must print a number, JSON or a short text.
3. **The expectation.** The narrowest rule that would have caught the original failure:
   an exact number, a range with a stated tolerance, a JSON field, a phrase that must or
   must not appear.
4. **Write** `harness/project/regressions/R-<next>-<slug>.json` with `confirmed.by`,
   `confirmed.date`, `confirmed.how`.
5. **Prove it.** Run `python3 harness/core/scripts/regressions.py --when all`: the case
   passes on the fixed code. If the old code is at hand (a worktree of the commit before
   the fix), it fails there.
6. A changed expectation later is a new human decision: update `confirmed` with the new
   date and reason, never just the number. End with the gate report.
