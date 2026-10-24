# Failure patterns

The generic catalog the harness checks grew from. It was collected from a real pilot
(an agent-built data product, dozens of deploys a day) out of conversation history,
the deploy journal and tickets; examples are anonymized. A project keeps its own
incidents in `harness/project/incidents.md`: each one is either an example of a pattern
below or a new project pattern (P1, P2...). Which check covers which pattern, proven by
which test, lives in `harness/config/incident-coverage.json`; the titles there match
this table word for word (a test checks it).

Coverage words: "covered" - a check exists and a test shows it firing on the failure;
"partial" - a check closes part of the pattern; "none" - no check yet. For data
patterns (B) the kit brings the rule and its test, the project brings the counter
(`harness/config/data-checks.json`): until the counter exists the pattern is not caught.

## A. Changes and deploys

| # | Pattern | Typical examples | Root cause | What catches it | Kit check |
|---|---|---|---|---|---|
| A1 | The server runs the wrong code | the repo copy was updated instead of the install folder; tests ran on an old archive; uncommitted edits of agents shipped; a deploy went out before tests were green; a long process kept the old code after the deploy | dirty working tree, no version hash, long processes not restarted | commit before deploy; only the committed state ships; hash check after the swap; long jobs log their code version | preflight: clean tree, main copy, branch, lineage; deploy.sh packs `git archive HEAD` |
| A2 | Code runs ahead of the database schema | `CREATE TABLE IF NOT EXISTS` never added a column; a missing grant gave 500; the schema went out before the merge; `ALTER` hung in an interactive client | manual, unversioned migrations | schema snapshot check before restart; versioned migrations inside the deploy (`ON_ERROR_STOP`, `lock_timeout`) | contract required for schema paths |
| A3 | Config drifts between machines | an env file not loaded; a hard-coded model name; `sed -i` silently changed nothing; two scripts with different defaults | several sources of config, hand edits | required keys and duplicates check; the same versions and files on every machine | supply chain: pinned versions and lock files |
| A4 | The build is stale or wipes files | old assets served; the build tool deleted tracked neighbour folders; deploys without a fresh build | the build is a separate manual step; the build folder overlaps tracked files | build from the deployed commit (build stamp); the build never deletes tracked files | preflight build stamp |
| A5 | Permissions, access and secrets | a missing role in the auth config; hand-made grants broke an invariant; a role got 403 on routes; env files readable by all; passwords in argv and logs; path traversal | grants and routes without tests | route access matrix test; grant snapshot; env files at most 640; sign-in with each role after the deploy | guard: secrets read or written, keys in written text, Grep and agent scripts; commit scanner: secrets; deploy check: required security tests; optional OS sandbox; ConfigChange hook |
| A6 | Broken edits without a linter | a NameError on a full run; syntax errors; an unescaped `%` in a prompt template; a deleted function | a syntax check does not see undefined names | linter (ruff F, tsc) and tests; smoke after the deploy; a probe on a few items before a full run | Stop hook syntax checks; shellcheck and bandit in the commit scanner |
| A7 | Deploys and background jobs collide | an OS auto-update restarted the database mid-run; a deploy cut a long run short; batch jobs took the cores the API needed | no coordination | preflight "no long job running"; auto-updates off; liveness checks | none |
| A8 | Regressions between waves of fixes | a ticket closed with a wrong result; closed tickets broke again unnoticed | a closed ticket does not become a test | every ticket closed with a human-confirmed result becomes a regression test replayed on each deploy | regression cases replayed by run.sh, the deploy check and after the swap |
| A9 | The deploy process stops the deploy | one general "yes" taken as approval of two actions; macOS metadata files in the archive broke tests on the server | one approval for two actions; OS metadata in archives | a separate approval per action; the archive comes from git; server files compared with git | guard asks per deploy command; deploy.sh packs from git |
| A10 | Documentation diverges from the code | most admin pages and routes were in no scenario; a documented session length was not what the code did | scenarios are edited by hand, nothing ties them to the code | scenario-to-code map, fingerprints after each change, a test per scenario of people | QG8 documentation coverage |

## B. Data and the checks themselves

For data failures scale matters more than the count: one failure runs through a whole
pipeline run.

| # | Pattern | Typical examples | Root cause | What catches it | Kit check |
|---|---|---|---|---|---|
| B1 | A transformation damages the data | one masking rule made almost only wrong replacements; masks in the middle of words broke search | the rule was measured by recall alone, with no false-positive counter | a false-positive counter on a frozen reference set as a start condition; a negative set of domain terms | data checks (max, ratio_max) with the project's counter |
| B2 | Sensitive data survives a cleanup step | a labelled field was never masked; phone numbers stayed in every sample while the unit test was green | checked with the same rules that did the masking | an independent detector; known values never appear in the output (a counter only) | data checks (eq 0) with the project's counter |
| B3 | Identifiers leak in exports | ID front matter in exported documents; IDs sent to an external checker; the mask missed one format | exports without a scanner | a scanner before every export, non-zero exit on a finding | guard asks on outbound commands; commit scanner with project ID patterns |
| B4 | Stale derived data and mixed versions | several generations of a text side by side; duplicate facts; zero vectors; caches without the prompt version | derived data does not know the version of its source | nightly "derived version equals source version"; an alarm on zero or a sharp drop | data checks (equal, eq 0, drop_max) |
| B5 | Extraction rules produce false positives | a pattern matched inside words; a negation produced thousands of facts | patterns without word boundaries or negative examples | negative control phrases; facts against text mentions per term | data checks (eq 0) |
| B6 | Dictionaries and code groups give wrong sets | a substring matched a different word; local codes not mapped to the standard; a set forty times too big | substring matching, groups without control numbers | golden sets with control numbers; a test of group expansion | data checks (range) |
| B7 | Deterministic rules misread the intent | OR became AND; an age bound inverted; a year read as an age; the last day of a period dropped | rules are not checked against the request; plan caches without a version | plan validation: every condition of the request is in the plan; a cached plan equals a fresh one | regression cases of confirmed answers |
| B8 | Results are silently truncated | an index parameter cut results at a fixed size; hybrid search added results without the searched term | parameters without a completeness check; silent degradation | a smoke check with a non-empty result; completeness against a direct query | data checks (min, drop_max until a human accepts) |
| B9 | ETL and decoders lose or shift data | empty rows reported as "no empty rows"; shifted table columns in thousands of documents | the report counted the wrong thing; input not reconciled with output | input equals output; zero-length counters; an anomaly counter as a quality condition | data checks (equal, eq 0) |
| B10 | Monitors report success on emptiness | an empty report looked normal; "0 alerts" because the monitor could not read the log | an empty result was taken as success | an empty or zero result of a check is a failure; meters self-test on synthetic pairs | gate table: no evidence is unknown, stale is warn, a crash is error; a scanner that fails is a failure; no tests means blocked; data checks: empty, not a number or none configured fails; hooks switched off fail QG0 |
| B11 | Service traffic and translations pollute results | service queries counted in statistics; duplicate tickets from an automated run; translations lost placeholders | service traffic not separated; translations without a placeholder check | author checks; deduplication; a placeholder check in translations | data checks (ratio_max) for service traffic |

## The patterns behind the patterns

1. No gate on "what exactly ships" (A1, A4, A9): dirty trees, manual builds, no
   version hash. The most frequent deploy failure.
2. Schema, grants and environment live apart from the code (A2, A3, A5).
3. Quiet wrong numbers instead of a crash (B4..B8): found late, by people.
4. Data cleanup without paired metrics: leaks and over-correction at once (B1..B3).
5. Long processes and deploys are not coordinated (A7).
6. A closed ticket does not become a regression test (A8).
7. The meters lie: empty is taken for "all is well" (B10).
8. What people see diverges from the code: scenarios (A10) and translations (B11).

## How to add a failure

1. Classify it against this table and the project patterns in
   `harness/project/incidents.md`; add it there with a date.
2. Put the check at the earliest point where it can be deterministic: the guard or
   Stop hook, preflight, the deploy check, a pipeline counter.
3. Reproduce the failure as a test in `harness/project/tests/` (or the kit tests, if
   the check is generic) that fires on it and stays silent on the clean case.
4. Record the check and the test name in `harness/config/incident-coverage.json`.
5. A pattern that turns out to be generic goes to the kit (`harness-dev`), with its
   check, in the next version.
