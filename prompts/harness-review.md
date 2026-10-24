# Periodic harness review (prompt)

Run in the harness-dev repository, interactively (skill `/harness-review`) or headless:

```
cd <harness-dev> && claude -p "$(cat prompts/harness-review.md)"
```

Optional arguments after the prompt text: paths of projects that use the kit, to read
their feedback (numbers only), and a budget ("implement at most N improvements").

---

You maintain harness-dev, a versioned, generic harness for repositories developed with
coding agents (Claude Code first). Your job in this run: find out what changed in
harness engineering since the last review, judge it on evidence, compare it with the
kit, and turn the best few findings into a new kit version that a human can merge.

## Rules for this run

- Evidence over fashion. Primary sources first (Anthropic, OpenAI, Thoughtworks and
  martinfowler.com, LangChain, GitHub, Google, academic papers, release notes of the
  tools the kit uses); practitioner posts second; vendor numbers are directional and
  marked as such. Open every source you cite; a claim you could not verify is marked
  "not verified" and never drives a change.
- The kit is for any project: nothing client-specific, no personal data, no internal
  identifiers, no secrets, in any file you write.
- Every change follows `CLAUDE.md` of this repository: kit files in `payload/`,
  templates for project-owned files, defaults in code so older configs keep working,
  tests for every check (a firing case and a clean case), `CHANGELOG.md` and `VERSION`
  updated together, `sh check.sh` green.
- Do not touch any project repository. Projects take the new version with
  `harness.py upgrade`.
- Work in a separate git worktree on a review branch:
  `git worktree add -b review/<date> ../harness-dev-review-<date>`. Commit there; never
  commit on main, never push, never merge.
- A change that would need project edits (a MAJOR version) is proposed, not
  implemented: it waits for a human.
- Budget: implement at most three improvements unless the arguments say otherwise; stop
  after the third failed attempt at the same change and report it.
- Write in English, plain and short; no em or en dashes, ellipsis characters, arrows or
  angle quotes (`payload/harness/core/rules.md`, "Text style").

## Steps

1. **Where we are.** Read `VERSION`, `CHANGELOG.md`, the latest file in
   `research/reviews/`, `research/harness-engineering.md`,
   `payload/harness/core/docs/design.md`. Note the date of the last review and its open
   items.
2. **Project feedback (if paths were given).** For each project: installed version and
   drift (`python3 harness.py status <path>`), gate states
   (`harness/config/gates.json`), coverage registry statuses, hook decisions per rule
   from `.claude/hooks/harness/log/` (counts only). Which patterns keep happening?
   Which rules fire most, which never? Never copy project text into the kit.
3. **What is new.** Search for what appeared since the last review: harness engineering,
   context engineering, agent guardrails and hooks, verification loops, agent evals,
   sandboxing, supply chain of agent tools, and the changelogs of Claude Code and the
   agents the kit targets. Prefer a few deep sources over many shallow ones.
4. **Judge.** For each practice: what it claims, the evidence, whether it is proven or
   hype, how it fits a small team with a closed perimeter, and its ring (adopt, trial,
   assess, hold). Say what moved since the last radar and why.
5. **Gaps.** Compare the radar with the kit. Also look at the kit's own entropy: rules
   without a failure behind them, checks that never fire in project feedback, documents
   that drifted from the code, the size of `rules.md` against the context budget,
   scaffolding a newer model no longer needs (remove it).
6. **Propose.** Rank improvements by value, cost and risk. Each names the failure
   pattern it addresses, the deterministic check (or why none is possible), the version
   bump it needs (PATCH, MINOR, MAJOR) and what a project must do to upgrade.
7. **Implement** the top ones within the budget in the review worktree: code, tests,
   docs, a migration if a setting changes, `VERSION`, a `CHANGELOG.md` section with
   `[+] [*] [X] [-] [!]` lines (`[!]` for every upgrade step). Run `sh check.sh --evidence`
   until green: the kit tests, a fresh install, the live run and the mutation check (a
   mutant that survives is a missing test). Recheck the hook protocol reference in
   `payload/harness/core/tests/test_hook_protocol.py` against the current Claude Code
   documentation. With the user's "yes" (it calls the model), run the golden tasks on a
   demo project and update `research/evidence.md`.
8. **Report.** Write `research/reviews/<date>.md` in the review worktree with these
   sections: Verdict, What changed since the last review, Radar, Gaps (ranked),
   Implemented (version, files, tests), Proposed but not implemented, Needs a human
   decision, Sources (title, URL, date, verified or not). Commit it with the changes.

End the run with a short message: the new version, what it adds, the review branch and
worktree path, how to look at it (`git -C <worktree> log --stat main..`) and what needs
a human.
