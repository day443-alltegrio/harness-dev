---
name: harness-cleanup
description: Monthly entropy pass over the harness - false blocks in the hook log, rules that never fire or have no failure behind them, context budget, agent memory, CLAUDE.md and skills, deferred decisions, kit drift. Use once a month or when the context budget passes 90%.
---

# Monthly harness cleanup

Goal: the harness stays small and true. Delete what no longer earns its place; do not
add rules in this pass unless a failure demands it. Numbers only in the report.

1. **Hook decisions.** `python3 harness/core/scripts/hook_review.py report --days 31`:
   decisions and marked false blocks per rule. Go through the unmarked asks and blocks
   with the user (`hook_review.py list --days 31`) and mark the false ones by id. A rule
   over 20% false gets a narrower pattern or is removed (project patterns in
   `.claude/harness-hooks.json`; kit patterns via a note for harness-dev).
2. **Rules without failures.** For every project rule, check, test and Stop check: which
   failure is it for (`harness/project/incidents.md`, registry)? None, and nothing
   caught in 6 months: propose removal.
3. **Context.** `python3 harness/core/scripts/context_budget.py`: anything over 90% of
   its budget is cleaned (move detail out of `CLAUDE.md` into linked docs, shorten skill
   descriptions, merge or delete stale memory files). Never raise a limit in this pass.
4. **Freshness.** Every path and command in `CLAUDE.md` and `harness/project/rules.md`
   still exists; deferred documentation decisions are within 90 days; accepted
   vulnerabilities are within their review dates.
5. **Kit.** `python3 <harness-dev>/harness.py status .`: local drift in kit files is
   either moved to harness-dev or reverted by an upgrade; if the kit is ahead, plan the
   upgrade (skill `harness-upgrade`).
6. **Agent model.** If the model or the harness changed since the last pass, run the
   golden tasks with the user's "yes" (they call the model:
   `python3 harness/core/scripts/golden_tasks.py`) and compare with the last run; then
   review hooks, budgets and thresholds against the new behaviour.
7. **Evidence.** Data checks ran within `stale_hours` (QG6), regression cases pass, the
   sandbox state is as `harness/config/sandbox.json` says.
8. Record a dated line in `harness/project/design.md`, "Decisions": what was removed,
   narrowed, cleaned, and the budget numbers before and after. End with the gate report.
