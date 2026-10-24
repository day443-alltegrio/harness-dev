---
name: harness-sandbox
description: Turn on the operating system sandbox for the agent's Bash commands - list the network needs, fill harness/config/sandbox.json, write it into .claude/settings.json with sandbox_config.py, verify that it holds. Use when the user wants the strongest boundary, before production, or when the sandbox settings drift.
---

# Turn on the sandbox

The sandbox is the strongest boundary: the operating system limits every Bash command
and what it starts (network through an allowlist proxy, writes in the project and temp
folders, reads denied where listed). Read, Edit, Write and WebFetch stay under
permission rules and the guard. Changing it is a change of the agent's boundaries:
a task contract and the user's "yes".

1. **Platform.** macOS works as is; Linux and WSL2 need `bubblewrap` and `socat`
   (ask the user to install them; never install system packages yourself).
2. **Network needs.** `python3 harness/core/scripts/sandbox_config.py --suggest --days 30`
   lists the hosts the agent used. With the user, keep the ones the work needs: code
   hosting, package registries, internal servers. Everything else stays blocked.
3. **Fill** `harness/config/sandbox.json`: `allowed_domains`, `deny_read` (machine
   credentials; the project's secret folders when no script the agent runs needs them),
   `allow_write` for tools that write outside the project, `excluded_commands` only for
   tools that cannot run inside, `required` once it works (Claude Code then refuses to
   start without it, and the ConfigChange hook keeps it on).
4. **Contract and dry run.** A contract (agent boundaries) and
   `python3 harness/core/scripts/sandbox_config.py --show`. Show the block to the user.
5. **Apply** after the "yes": `python3 harness/core/scripts/sandbox_config.py --apply`
   (the guard asks for it). The user restarts Claude Code.
6. **Verify** in the new session: `touch ~/sandbox-probe` must fail, a request to a host
   that is not allowed must fail, the project's tests and build must still pass,
   `sandbox_config.py --check` and the QG0 line say "sandbox on". If a needed command
   fails, add its host or path and apply again; decline any retry outside the sandbox.
