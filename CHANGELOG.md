# Changelog

Versions follow SemVer: MAJOR - a change that needs project edits (always with a
migration or an `[!]` upgrade note), MINOR - new checks or features with
backward-compatible settings, PATCH - fixes and docs. Markers: `[+]` added,
`[*]` changed, `[X]` fixed, `[-]` removed, `[!]` attention or upgrade step.

## 0.2.0 - 2026-10-24

[+] Optional OS sandbox: harness/config/sandbox.json and sandbox_config.py (--show, --check, --apply, --suggest) write the Claude Code sandbox block with the retry outside the sandbox always closed; QG0 shows its state and fails when a required sandbox is missing; skill harness-sandbox
[+] Guard sees more: Grep into secret files, secret files written with Edit or Write, keys and tokens in written text, edits of kit files and of the agent's own settings (also by shell redirection, cp, tee, sed -i), decoded or downloaded code (base64 | sh, eval, curl | sh), network code and secrets in interpreter one-liners, ssh to hosts outside the perimeter, a secret moved, linked, archived or shown from git history, read-only reviewer subagents (by agent_type), harness.py install and upgrade and sandbox_config.py --apply ask
[+] Guard reads the scripts the agent wrote or changed before they run: a new script gets every rule, an edited file of the project only the deny rules (printing a secret, destructive git), so a service that calls the network does not ask on every run; committed and kit-owned scripts are not read
[+] Guard: a copy whose only secret is the destination (cp .env.example .env) asks as a write instead of denying as a read; ~/.ssh, ~/.aws and ~/.gnupg are secret folders by default
[+] ConfigChange hook (config_guard.py): a settings change that switches hooks off, unwires them, narrows the guard, drops a deny rule for secrets or turns off a required sandbox is not applied mid-session; QG0 fails while such a file stays on disk
[+] Every hook decision has an id in its reason and in the log; hook_review.py marks false blocks by id and reports the share per rule; QG0 warns over 20% with at least 5 decisions; telemetry counts false blocks
[+] Regression cases (regressions.py, harness/project/regressions/): closed tickets with a confirmed result, replayed by run.sh, QG1, the deploy check before the swap (blocks on a failed or malformed case) and after the swap; skill harness-regression
[+] Data checks (data_checks.py, QG6): project counters against eq, min, max, range, equal, ratio_max and drop_max; drop_max keeps failing until a human accepts the new level (--accept with a reason); empty, not a number or no checks is a failure; gate check "data" reads the last run
[+] Golden tasks (golden_tasks.py, harness/config/golden-tasks.json): the real agent (claude -p) on fixed tasks in a throwaway worktree, graded by a check; integration tasks prove from the hook log that Claude Code ran the hooks and obeyed them; results compared with the last run, numbers only
[+] Task contracts: named tests and regression cases in the acceptance criteria must exist, and a contract in state done names at least one check (contracts.checkable)
[+] Hook protocol test: the hooks run through the command lines in settings and answer in the shape Claude Code documents (CLI 2.1.308)
[+] research/evidence.md with the live run and the mutation check in research/evidence/ (sh check.sh --evidence)
[*] harness.py upgrade keeps the kit hook matchers in step and moves a kit hook out of an entry the project shares
[*] Telemetry and hook review read only the day logs of the hook log
[X] The guard missed a secret named at the start of the arguments (cat .env, cat secrets/token.txt), commands on the second line of a command (cd x, then git reset) and paths given through a symlink (/var and /private/var on macOS)
[X] A test now proves the commit scanner never prints the value of a secret in the added lines
[!] Restart Claude Code after the upgrade: the ConfigChange hook is new and the guard sees more tools
[!] Review the new templates: harness/config/data-checks.json, sandbox.json, golden-tasks.json, harness/project/regressions/README.md; QG6 gets the built-in check "data" (set it active once data-checks.json has counters)
[!] The guard now asks before edits of kit files and of .claude settings, and before harness.py install and upgrade: expect one confirmation more in those cases

## 0.1.0 - 2026-10-23

[+] First version, extracted from a production pilot
