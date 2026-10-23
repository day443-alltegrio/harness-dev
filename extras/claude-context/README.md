# Context pack: continue agent work on another machine

Optional, not installed by `harness.py`. A self-contained pack of the Claude Code
context of one repository: agent memory, local rules outside git, uncommitted work,
readable digests of every conversation, raw transcripts for `claude --resume`. It holds
conversation text, so it lives only in an untracked folder and travels by disk or
encrypted archive, never through git or chat.

## Set up (once per repository)

1. Copy this folder into an untracked folder of the repository, e.g.
   `sandbox/claude-context/`, and make sure git ignores it (`export.sh` refuses
   otherwise).
2. Optional `pack.conf` next to `export.sh`: `RULES="..."` lists local files to carry
   (default: `.claude/settings.local.json CLAUDE.local.md`).
3. Run `sh sandbox/claude-context/export.sh` once and read `last-export.txt`.
4. Nightly export on macOS: a LaunchAgent plist in `~/Library/LaunchAgents/` running
   `/bin/sh <repo>/sandbox/claude-context/export.sh` at a fixed hour
   (`StartCalendarInterval`), output to `export.log` in the pack; load it with
   `launchctl bootstrap gui/$(id -u) <plist>`. On Linux, a cron line:
   `30 21 * * * sh <repo>/sandbox/claude-context/export.sh >> <repo>/sandbox/claude-context/export.log 2>&1`.
   Creating either is a persistent change on the machine: the user decides.
5. Ask the agent to keep `CONTEXT.md` in the pack current (what is done, in progress,
   waiting for a decision) at the end of a working day.

## Restore

1. Install Claude Code and sign in.
2. Clone the repository, check out the branch, copy the pack into the same untracked
   folder. Secrets travel separately, never through the pack or a chat.
3. From the repository root: `sh sandbox/claude-context/install.sh` (memory, local
   rules, skills, settings; nothing existing is overwritten).
4. Uncommitted work not committed anywhere else:
   `sh sandbox/claude-context/install.sh --repo` (only on the same base commit and a
   clean tree).
5. Start `claude` in the repository root with a first prompt like:

```
We continue the work on this repository from another machine. Read CLAUDE.md, then
sandbox/claude-context/CONTEXT.md (state of the work); the project memory is loaded.
For details of a decision, grep sandbox/claude-context/sessions/. Change nothing on
servers and commit nothing without my "yes". Summarize the state and what is in
progress, then wait for my task.
```

## Not carried

Sessions of other projects, caches, limits; sign-ins to external services; virtual
environments and `node_modules` (rebuild them).
