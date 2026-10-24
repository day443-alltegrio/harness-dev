# Contract: <short name of the change>

- Date: YYYY-MM-DD
- State: plan / done / written after the fact
- Commits: <hashes, when they exist>

A contract is needed when a change touches the database schema, deploy scripts, data
pipelines, the agent's boundaries (`.claude/settings.json`, `.claude/harness-hooks.json`)
or more than 30 files (`contracts.risky` in `harness/config/harness.json`;
`harness/core/scripts/contract_check.py` checks it). Written before the work; 8..15
lines of substance, no retelling of the code.

## Goal

What should be different for a person or the system, in one or two sentences.

## Non-goals

What this change deliberately does not do.

## Acceptance criteria

What proves it is done: which tests, quality checks, reference cases, a check on the
live system. Only what can be checked. Name each check in backticks: a test
(`test_name`), a command (`sh harness/core/scripts/run.sh`) or a regression case
(`R-0001`); preflight checks that the named tests and cases exist, and a contract in
state "done" names at least one.

## Boundaries

What is not touched; which actions need a "yes" (schema, deploy, data, trackers).

## Risks and rollback

What can break and how to return to the previous state.

## Related failures

Patterns from `harness/core/docs/failure-patterns.md` or `harness/project/incidents.md`
(A1..A10, B1..B11, P1...) this change is about, or "none".
