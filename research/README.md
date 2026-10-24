# Research behind the harness

Why the kit looks the way it does, and how it keeps up. The kit's design
(`payload/harness/core/docs/design.md`) cites only claims that survived the fact check
here.

| File | What |
|---|---|
| `evidence.md` | what the kit does and the evidence for the current version: kit tests, the live run, the mutation check, golden tasks with the real agent, the practices it follows and its limits |
| `evidence/` | the scripts behind it: `live_run.py`, `mutation_check.py`, `guard_cases.json` (`sh check.sh --evidence`) |
| `harness-engineering.md` | overview of harness engineering as of 22.10.2026: challenges, risks, trends, practice, sources |
| `case-study-pilot.md` | anonymized lessons of the pilot the kit was extracted from: numbers, what worked, what did not |
| `reviews/` | periodic reviews (`prompts/harness-review.md`): verdict, radar of practices, gaps, what was implemented |
| `sources/` | source material kept verbatim or as translated, not style-checked: the trends dialogue that started it, its fact check, the Ukrainian version of the overview |

The fact check (`sources/2026-10-21-fact-check.uk.md`) refers to the pilot's own design
and failure catalog by file name; those stay in the pilot repository, their generic
content is in `payload/harness/core/docs/`.

## How the research is kept current

`prompts/harness-review.md` runs periodically (monthly is a good default, and after any
major model or tool release). Each run reads the last review, looks for what changed in
the field since then, judges it against the evidence and the kit, writes a dated review
in `reviews/` and implements the best few improvements as a new kit version on a review
branch. A human merges.

Rules for any new research note: primary sources first, vendor numbers marked as such,
every claim the kit relies on checked against its source, no client names, personal
data or internal identifiers.
