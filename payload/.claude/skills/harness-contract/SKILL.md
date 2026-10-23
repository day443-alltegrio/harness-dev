---
name: harness-contract
description: Write a task contract before a big change (schema, deploy scripts, data pipelines, agent boundaries, more than 30 files) - goal, non-goals, acceptance criteria, boundaries, risks and rollback, related failures. Use before starting such a change, or when preflight reports a missing contract.
---

# Task contract

A contract is written before the work and agreed with the user; it keeps the change
small enough to verify and says up front what proves it is done.

1. Check that one is needed: `python3 harness/core/scripts/contract_check.py` after the
   change, or judge from `contracts.risky` in `harness/config/harness.json` before it.
2. Copy `harness/project/contracts/TEMPLATE.md` to
   `harness/project/contracts/YYYY-MM-DD-<slug>.md`. Keep every section heading as is:
   the check looks for them.
3. Fill it in 8..15 lines of substance:
   - **Goal**: what changes for a person or the system;
   - **Non-goals**: what this change deliberately leaves out;
   - **Acceptance criteria**: tests, checks, reference cases, a live check - only what
     can be verified;
   - **Boundaries**: what is not touched; which steps need a "yes";
   - **Risks and rollback**: what can break, how to return;
   - **Related failures**: patterns from the catalogs, or "none".
4. Show it to the user before the work starts; state "plan". Update it to "done" with
   the commit hashes when the change lands; "written after the fact" is honest but
   counts against the metric.
5. The contract file goes into the same commit (or deploy range) as the change, or
   preflight stops the deploy.
