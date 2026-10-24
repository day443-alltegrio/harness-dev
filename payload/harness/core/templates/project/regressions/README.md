# Regression cases

A ticket closed with a result a person confirmed becomes a case in this folder: a
command and the result it must give. The cases replay on every deploy and nightly, so a
fixed behaviour cannot break again unnoticed (pattern A8 in
`harness/core/docs/failure-patterns.md`). This folder is the record of behaviour people
checked; `harness/core/scripts/regressions.py` replays it.

## When to add a case

When a ticket is closed and a person confirmed the result: re-asked the question on the
deployed code, compared the number with the source, accepted the refusal. A fix nobody
has checked yet gets a test, not a case; the case comes with the confirmation.

## Format

One JSON file per case, named after its id, e.g. `R-0001-age-in-months.json`; ids are
`R-` and a number, in order. Every `.json` file directly in this folder runs as a case,
so never keep an example or a draft here as `.json`. Files a case reads go into a
subfolder. Keys starting with `_` are comments.

```json
{
  "id": "R-0001",
  "ticket": "TICKET-123",
  "title": "age under one year counts as 0 full years",
  "confirmed": {"by": "QA lead", "date": "2026-10-22", "how": "re-asked on the deployed code"},
  "when": "before",
  "cmd": "python3 -m app.cli count --age-max 0",
  "timeout_s": 60,
  "expect": {"exit": 0, "number": 42}
}
```

Required: `id` (unique), `ticket`, `confirmed.by`, `confirmed.date` (YYYY-MM-DD), `cmd`,
`expect`. A case without a human confirmation is rejected. Optional: `title`, `when`
(default `before`), `cwd` (where `cmd` runs, a folder relative to the repository root),
`timeout_s` (default `regressions.timeout_s` in `harness/config/harness.json`).

Every rule of `expect` must hold:

| Rule | Holds when |
|---|---|
| `exit` | the command exits with this code (default 0) |
| `number` | the number equals `N`, fits `{"min": a, "max": b}` or `{"value": N, "tolerance": t}`; it is the last non-empty line of stdout, or the JSON field `number_key` (a dotted path: `total.count`, `items.0.n`) |
| `json` | stdout is JSON and every `{"dotted.path": value}` matches |
| `stdout_has` | each text of the list appears in stdout |
| `stdout_lacks` | no text of the list appears in stdout |

An `expect` with only `"exit": 0` checks nothing and is rejected; a non-zero `exit`
alone is a rule (the command must refuse). An unknown rule is rejected too, so a typo
never drops a check.

## Before and after

- `before` (default): the case needs only the code, such as a CLI call over a fixture.
  The deploy check replays it on the new code before that code replaces the running
  one, and `run.sh` replays it on every run.
- `after`: the case needs the running service, such as a request to its API. It runs
  right after the swap (in `deploy_health`) and nightly.

## Running them

```
python3 harness/core/scripts/regressions.py                # before cases
python3 harness/core/scripts/regressions.py --when after   # against the running service
python3 harness/core/scripts/regressions.py --when all --json
```

One line per case, then a summary:

```
pass  R-0001  TICKET-123
FAIL  R-0002  TICKET-9: expected number 42, got 41
```

Exit 1 when a case fails or cannot start, 2 when a case file is malformed (then nothing
runs). No cases at all is not a pass: the gate table shows it as unknown.

## Privacy

The output of a command may hold personal data, so it is never printed or stored. A
failure says only "exit 1, expected 0", "expected number 42, got 41" or "expected text
#2 missing"; to see more, run the command by hand where its output may be seen. For the
same reason an expected value is a number or a short phrase, never a text of a record
or an identifier, and `confirmed.by` is a role or a team member, never a customer.

## A case is never edited to make it pass

A failing case means the behaviour changed. Fix the code. If the new behaviour is the
right one, that is a human decision: the person who decides confirms the case again,
with the new expectation and, in `confirmed`, the new date and the reason
(`"reason": "..."`). The old version stays in the git history.
