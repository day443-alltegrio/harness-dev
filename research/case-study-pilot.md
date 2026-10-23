# Case study: the pilot the kit came from

Anonymized. A data warehouse pilot with personal data and plain-language search, built
by one engineer with a coding agent (Claude Code) in October 2026: Python services,
a React admin panel, PostgreSQL, local models on two servers inside a closed perimeter,
no external CI. The harness was designed on 21.10 and its first version ran the same
day; numbers below are from 21..23.10.

## Why a harness was needed

The agent deployed dozens of times a day (358 deploys in 13 days, up to 72 a day), and
failures were caught by people: the server ran the wrong code, the schema lagged
behind, a data run damaged text, a search result quietly shrank. The failure catalog
collected from conversation digests, the deploy journal and tickets had 21 patterns;
they became `payload/harness/core/docs/failure-patterns.md`.

## What worked

- **A gate on what ships.** Preflight (only committed code from the main copy, lineage
  from the last deploy, build from the same commit) and a deploy check on the server
  before the swap (API contract diff, all tests, security tests). The most frequent
  class of deploy failure stopped appearing.
- **The guard hook.** Over two days: 68 deploy confirmations, 4 push confirmations, 5
  secret reads blocked, 1 destructive git command blocked. No complaint of false
  blocks; the confirmation per deploy became the normal rhythm.
- **Empty means fail.** Scanners that could not run, missing evidence and stale reports
  stopped looking like a green light.
- **Documentation tied to code.** A map of 40 scenarios of people to routes, pages and
  tests found that 19 of 23 admin pages and 86 of 106 routes were in no scenario. After
  one review round (20 docs fixed to match the code, 6 code fixes, 14 no change) only
  new drift blocks a deploy.
- **The gate table in the chat.** One fixed table at the end of each work report
  replaced retelling; a failed gate named first gets attention.

## What did not, or not yet

- **Contracts after the fact.** Of 30 recent commits 11 needed a contract and 4 had one;
  half of the contracts were written after the change. Writing the contract first is a
  habit, not a check, until preflight blocks it.
- **Hooks are a second line.** A script in a file, Python instead of ssh or a planted
  instruction pass a regex hook; Edit and Write are outside it. The real boundary is
  server-side permissions and a sandbox, deferred to production as a trade-off.
- **One laptop runs the nightly snapshot.** When it sleeps, the evidence goes stale;
  the gate table says so after 36 hours.
- **Behaviour remains the human's job.** Correct numbers in answers, the meaning of a
  documentation mismatch and closing a ticket stay with a person.

## Lessons about agent context

- A `CLAUDE.md` in a subfolder loads only when the work touches that folder: the
  engineering rules were invisible in most sessions while 79 KB of another team's
  methodology loaded into every one. The fix: a short root map importing the
  engineering rules, the other methodology loaded only for its own work.
- Rules that lived only in the agent's memory on one laptop did not travel; they moved
  into versioned files.
- Instructions to the agent in English were shorter and more precise than in the team's
  language; rules about the output language stayed rules about the output.
- The always-loaded context sat at 96% of its budget: every new rule pushed the task
  out. A budget check and the "map, not manual" rule hold it now.

## Numbers at the start (23.10)

| What | Value |
|---|---|
| Failure patterns | 21: covered 3, partial 6, none 12 |
| Harness tests | 144, all green |
| Deploy check, last deploy | tests 56 of 56, security 5 of 5 |
| Always-loaded context | 96% of budget, being reduced |
| Critical dependency vulnerabilities | 3 in one package, deploys of that app blocked until it is upgraded |
| Secrets in git history | 0 |
