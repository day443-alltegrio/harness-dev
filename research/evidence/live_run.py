#!/usr/bin/env python3
"""Live run of the kit on a throwaway project: every claim of research/evidence.md, executed.

Installs the kit from this repository into a new git repository with a project of its
own (CLAUDE.md, settings, an app), then walks through the boundaries, the gates, the
gated deploy to a local folder that stands in for a server, the data checks, the
sandbox settings and an upgrade to a made-up next version. Every step states what it
expects; the run prints one line per expectation and exits 1 if any is not met.

Nothing outside the temporary folder is touched: harness-dev is only read (the upgrade
works on a copy), no model is called (the guard and the other hooks get their events on
stdin, the way Claude Code sends them), nothing goes to the network.

    python3 research/evidence/live_run.py [--keep]   # --keep: leave the folder for a look
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
WORK = Path(tempfile.mkdtemp(prefix="harness-live-"))
REPO = WORK / "repo"
TARGET = WORK / "target"
FAILS: list[str] = []
COUNT = {"ok": 0}
BEGAN = time.monotonic()

APP_OK = 'def status() -> str:\n    return "ok"\n\n\nif __name__ == "__main__":\n    print(status())\n'
APP_BROKEN = APP_OK.replace('return "ok"', 'return "ready"')
APP_TEST = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


class Status(unittest.TestCase):
    def test_status_is_ok(self):
        self.assertEqual(app.status(), "ok")


if __name__ == "__main__":
    unittest.main()
'''
# The "server" is a local folder ($TARGET); the service is app/app.py.
DEPLOY_HOOKS = '''# Live run deploy steps: the target is a local folder, not a machine.
TARGET="${TARGET:?TARGET must point to the target folder}"
deploy_package() { git archive --format=tar.gz -o "$1" HEAD; }
deploy_ship() { cp "$1" "$TARGET/incoming.tar.gz" && echo ship >> "$TARGET/ops.log"; }
deploy_verify() {
  S="$TARGET/stage"; rm -rf "$S"; mkdir -p "$S"
  tar -xzf "$TARGET/incoming.tar.gz" -C "$S" || return 1
  echo verify >> "$TARGET/ops.log"
  python3 "$S/harness/core/scripts/deploy_check.py" check --staged "$S/app" --current "$TARGET/current" ${1:+--allow-breaking "$1"}
}
deploy_swap() { rm -rf "$TARGET/current" && cp -R "$TARGET/stage/app" "$TARGET/current" && echo swap >> "$TARGET/ops.log"; }
deploy_health() { echo health >> "$TARGET/ops.log"; [ "$(python3 "$TARGET/current/app.py")" = ok ]; }
'''
CASE = {"id": "R-0001", "ticket": "DEMO-1", "title": "the service answers ok",
        "confirmed": {"by": "QA lead", "date": "2026-10-24", "how": "checked on the deployed code"},
        "when": "before", "cmd": "python3 app/app.py", "expect": {"stdout_has": ["ok"]}}


def contract(name: str, state: str, criteria: str) -> str:
    return f"""# Contract: {name}

- Date: 2026-10-24
- State: {state}

## Goal

{name.capitalize()}.

## Non-goals

No server, no data, nothing outside this folder.

## Acceptance criteria

{criteria}

## Boundaries

Only this throwaway repository.

## Risks and rollback

None outside the run; delete the folder.

## Related failures

A1, A8, A9
"""


def run(cmd, cwd: Path = REPO, env: dict | None = None, inp: str | None = None):
    return subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}, input=inp,
                          capture_output=True, text=True, shell=isinstance(cmd, str))


def git(*args: str, cwd: Path = REPO) -> str:
    r = run(["git", *args], cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def title(text: str) -> None:
    print(f"\n=== {text}")


def out(text: str, keep=None, limit: int = 40) -> None:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if keep:
        lines = [ln for ln in lines if keep(ln)]
    for ln in lines[:limit]:
        print("  | " + ln[:200])
    if len(lines) > limit:
        print(f"  | ... {len(lines) - limit} more lines")


def expect(cond: bool, what: str) -> None:
    print(f"  [{'ok' if cond else 'MISMATCH'}] {what}")
    if cond:
        COUNT["ok"] += 1
    else:
        FAILS.append(what)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(rel: str, text: str, root: Path = REPO) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def gates(*ids: str) -> str:
    text = run(["python3", "harness/core/scripts/gates.py"]).stdout
    if ids:
        text = "\n".join(ln for ln in text.splitlines() if ln.split(" ", 1)[0] in ids)
    return text


def state_of(gate_line: str) -> str:
    parts = gate_line.split()
    return parts[3] if len(parts) > 3 and parts[2] == "check" else gate_line[24:37].strip()


def harness(*args: str, kit: Path = KIT):
    return run(["python3", str(kit / "harness.py"), *args], cwd=WORK)


def hook(script: str, event: dict, root: Path = REPO):
    return run(["python3", f".claude/hooks/harness/{script}"], cwd=root, inp=json.dumps(event))


def guard(tool: str, value, session: str, agent: str | None = None) -> tuple[str, str]:
    if tool == "Bash":
        args = {"command": value}
    elif tool == "Read":
        args = {"file_path": value}
    else:
        args = value
    ev = {"session_id": session, "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_input": args, "cwd": str(REPO)}
    if agent:
        ev["agent_type"] = agent
    r = hook("guard.py", ev)
    if r.returncode != 0:
        return "error", r.stderr.strip()[-120:]
    if not r.stdout.strip():
        return "allow", "-"
    o = json.loads(r.stdout)["hookSpecificOutput"]
    m = re.match(r"\[([\w-]+) #([0-9a-f]{8})\]", o["permissionDecisionReason"])
    return o["permissionDecision"], f"{m.group(1)} #{m.group(2)}" if m else "?"


def main() -> int:
    keep = "--keep" in sys.argv
    print(f"kit {(KIT / 'VERSION').read_text().strip()} from {KIT}; work folder {WORK}")

    title("0. An existing project before the install")
    REPO.mkdir()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "dev@example.com")
    git("config", "user.name", "Dev")
    write("README.md", "# Demo shop\n")
    write("CLAUDE.md", "# Demo shop\n\nMap: app/ is the service, app/tests/ its tests.\n")
    write(".claude/settings.json", json.dumps({
        "permissions": {"allow": ["Bash(npm test)"], "deny": ["Read(./private/**)"]},
        "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": "echo project-hook"}]}]}}, indent=2) + "\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    print("  a repository with its own CLAUDE.md and .claude/settings.json (allow, deny, a hook)")

    title("1. Install: the dry run writes nothing; project files are merged, never replaced")
    r = harness("install", str(REPO), "--dry-run")
    out(r.stdout, keep=lambda ln: not ln.strip().startswith("create"))
    expect(r.returncode == 0 and git("status", "--porcelain") == "", "dry run: exit 0, the tree is untouched")
    expect(harness("install", str(REPO)).returncode == 0, "install: exit 0")
    s = json.loads((REPO / ".claude/settings.json").read_text())
    expect("Bash(npm test)" in s["permissions"]["allow"] and "Read(./private/**)" in s["permissions"]["deny"],
           "the project's own allow and deny rules are kept")
    expect(any("project-hook" in h["command"] for e in s["hooks"]["PostToolUse"] for h in e["hooks"]),
           "the project's own hook is kept")
    guard_entry = next(e for e in s["hooks"]["PreToolUse"] if "guard.py" in e["hooks"][0]["command"])
    expect(guard_entry["hooks"][0]["command"].endswith("|| exit 2") and "Edit" in guard_entry["matcher"]
           and "Grep" in guard_entry["matcher"], "guard wired for Bash, Read, Grep, Edit and Write, failing closed")
    expect(any("stop_check.py" in h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"]), "Stop hook wired")
    expect(any("config_guard.py" in h["command"] for e in s["hooks"]["ConfigChange"] for h in e["hooks"]),
           "ConfigChange hook wired")
    md = (REPO / "CLAUDE.md").read_text()
    expect(md.startswith("# Demo shop\n\nMap: app/") and "@harness/core/rules.md" in md,
           "CLAUDE.md kept; a harness block with two imports appended")
    lock = json.loads((REPO / "harness/harness.lock.json").read_text())
    print(f"  lock: version {lock['version']}, {len(lock['managed'])} kit files with sha256, "
          f"{len(lock['templates'])} templates")
    expect(harness("install", str(REPO)).returncode == 2, "a second install refuses")

    title("2. Checks right after the install, nothing committed yet")
    r = run(["sh", "harness/core/scripts/run.sh", "--offline"])
    out(r.stdout, keep=lambda ln: ln.startswith(("Ran", "OK", "FAILED", "ok ", "OVER", "no regression")))
    expect(r.returncode == 0, "run.sh --offline: exit 0")
    expect(" unknown " in gates("QG0"), "QG0 without a hook log is unknown, not pass")

    title("3. Contract first: the install commit without a contract fails QG2, with one it passes")
    git("add", "-A")
    git("commit", "-qm", "harness")
    g = gates("QG2")
    out(g)
    expect(" fail " in g and "contract" in g, "QG2 fails: the change needs a task contract")
    write("harness/project/contracts/2026-10-24-adoption.md",
          contract("adopt the generic harness", "plan", "The gate table and run.sh pass."))
    git("add", "-A")
    git("commit", "-q", "--amend", "--no-edit")
    g = gates("QG2")
    out(g)
    expect(" pass " in g, "QG2 passes once the contract is part of the same change")

    title("4. QG0 guard: events on stdin the way Claude Code sends them")
    cases = json.loads((HERE / "guard_cases.json").read_text())
    decided = {}
    for i, c in enumerate(cases["cases"]):
        d, rule = guard(c["tool"], c["input"], f"case-{i}", c.get("agent_type"))
        ok = d == c["expect"] and (c["expect"] == "allow" or rule.startswith(c.get("rule", "")))
        COUNT["ok"] += ok
        if not ok:
            FAILS.append(f"guard: {c['input']} gave {d} {rule}, expected {c['expect']} {c.get('rule', '')}")
        shown = c["input"] if isinstance(c["input"], str) else json.dumps(c["input"])[:70]
        who = f" ({c['agent_type']})" if c.get("agent_type") else ""
        print(f"  [{'ok' if ok else 'MISMATCH'}] {d:<5} {rule:<28} {c['tool']}{who}: {shown[:90]!r}")
        decided[i] = rule
    rep = cases["repeat"]
    got = [guard("Bash", rep["input"], "loop")[0] for _ in range(rep["times"])]
    expect(got == rep["expect"], f"the same command {rep['times']} times in a row: {', '.join(got)}")
    r = run("python3 .claude/hooks/harness/guard.py || exit 2", inp="not json")
    expect(r.returncode == 2, "the hook itself crashes: exit 2, which blocks the call")
    log_text = "".join(p.read_text() for p in (REPO / ".claude/hooks/harness/log").glob("*.jsonl"))
    texts = [c["input"] for c in cases["cases"] if isinstance(c["input"], str) and len(c["input"]) > 8]
    leaked = [t for t in texts if t in log_text]
    expect(bool(log_text) and not leaked and '"id"' in log_text,
           f"decision log: {len(log_text.splitlines())} lines with ids, command texts in it: {len(leaked)}")
    expect(git("status", "--porcelain") == "", "log and state stay out of git")

    title("5. Scripts the agent wrote are read before they run; committed ones are not")
    write("tools/reviewed.sh", "grep -c '=' .env\n")
    git("add", "-A")
    git("commit", "-qm", "a reviewed script")
    write("tmp/dump.sh", "#!/bin/sh\necho start\ncat .env\n")
    write("tmp/upload.py", "import urllib.request\nurllib.request.urlopen('https://x.example.com', data=b'1')\n")
    d1, r1 = guard("Bash", "sh tmp/dump.sh", "script-1")
    d2, r2 = guard("Bash", "cd tmp && python3 upload.py", "script-2")
    d3, r3 = guard("Bash", "sh tools/reviewed.sh", "script-3")
    print(f"  sh tmp/dump.sh -> {d1} {r1}; cd tmp && python3 upload.py -> {d2} {r2}; sh tools/reviewed.sh -> {d3}")
    expect((d1, r1.split()[0]) == ("deny", "secrets-read") and (d2, r2.split()[0]) == ("ask", "outbound")
           and d3 == "allow", "an agent script that prints a secret is denied, one that uploads asks, a committed one runs")
    shutil.rmtree(REPO / "tmp")

    title("6. A wrong decision is marked by its id; the rate per rule is measured")
    ssh_id = next(r for i, r in decided.items() if cases["cases"][i]["input"] == "ssh ops@203.0.113.9 uptime").split("#")[1]
    r = run(["python3", "harness/core/scripts/hook_review.py", "mark", ssh_id, "--reason",
             "the live run's own build host"])
    out(r.stdout)
    r = run(["python3", "harness/core/scripts/hook_review.py", "report"])
    out(r.stdout, keep=lambda ln: ln.startswith(("outbound", "decisions")) or "decisions in" in ln)
    expect("1 marked false" in r.stdout or " 1 false" in r.stdout, "the mark counts in the report")
    g = gates("QG0")
    out(g)
    expect("marked false" in g, "QG0 shows the false blocks of the last 30 days")

    title("7. ConfigChange: a settings change that switches the hooks off is not applied")
    write(".claude/settings.local.json", '{"disableAllHooks": true}\n')
    r = hook("config_guard.py", {"hook_event_name": "ConfigChange", "source": "local_settings",
                                 "session_id": "cfg", "file_path": str(REPO / ".claude/settings.local.json")})
    o = json.loads(r.stdout) if r.stdout.strip() else {}
    print(f"  decision: {o.get('decision')}; reason: {o.get('reason', '')[:90]}")
    expect(o.get("decision") == "block", "the change is blocked for the running session")
    g = gates("QG0")
    out(g)
    expect(" fail " in g and "disableAllHooks" in g, "the file stays on disk for the next session, so QG0 fails until it is gone")
    (REPO / ".claude/settings.local.json").unlink()
    expect(" fail " not in gates("QG0"), "QG0 recovers once the file is removed")

    title("8. Stop hook: fast checks of changed files before the answer ends")
    ev = {"session_id": "stop", "hook_event_name": "Stop", "stop_hook_active": False}
    write("app/broken.py", "def total(items:\n    return sum(items)\n")
    seen = []
    for i in range(3):
        r = hook("stop_check.py", ev)
        o = json.loads(r.stdout) if r.stdout.strip() else {}
        kind = "block" if o.get("decision") == "block" else ("warn" if "systemMessage" in o else "pass")
        seen.append(kind)
        print(f"  round {i + 1}: {kind}: {(o.get('reason') or o.get('systemMessage') or '').splitlines()[0][:110]}")
    expect(seen == ["block", "block", "warn"], "broken file: block, block, then a warning (bounded at 2)")
    write("app/broken.py", "def total(items):\n    return sum(items)\n")
    expect(not hook("stop_check.py", ev).stdout.strip(), "after the fix the answer ends normally")
    (REPO / "app/broken.py").unlink()

    title("9. Gated deploy to a local folder: contract, tests and a regression case on the target")
    TARGET.mkdir()
    (TARGET / "current").mkdir()
    write("app/app.py", APP_OK)
    write("app/tests/test_app.py", APP_TEST)
    write("harness/config/deploy-hooks.sh", DEPLOY_HOOKS)
    write("harness/project/regressions/R-0001-status.json", json.dumps(CASE, indent=1) + "\n")
    gj = json.loads((REPO / "harness/config/gates.json").read_text())
    gj["gates"]["QG3"] = {"name": "deploy check", "state": "active", "check": "deploy_report"}
    write("harness/config/gates.json", json.dumps(gj, indent=1) + "\n")
    write("harness/project/contracts/2026-10-24-deploy.md",
          contract("deploy steps to a local folder", "done", "`test_status_is_okay` and `R-0001` pass on the target."))
    git("add", "-A")
    git("commit", "-qm", "app, deploy steps, a regression case")
    g = gates("QG2")
    out(g)
    expect(" fail " in g and "test_status_is_okay" in g, "a contract that names a test nobody wrote fails QG2")
    write("harness/project/contracts/2026-10-24-deploy.md",
          contract("deploy steps to a local folder", "done", "`test_status_is_ok` and `R-0001` pass on the target."))
    git("add", "-A")
    git("commit", "-q", "--amend", "--no-edit")
    expect(" pass " in gates("QG2"), "with the real test name QG2 passes")
    env = {"TARGET": str(TARGET)}

    def deploy(*notes: str):
        args = ["sh", "harness/core/scripts/deploy.sh"]
        for n in notes:
            args += ["-m", n]
        return run(args, env=env)

    def ops() -> list[str]:
        p = TARGET / "ops.log"
        return p.read_text().split() if p.is_file() else []

    expect(deploy().returncode == 2, "no release notes: refused before anything runs")
    r = deploy("[+] first release")
    out(r.stdout + r.stderr, keep=lambda ln: ln.startswith(("deployed", "archive")))
    expect(r.returncode == 0 and git("rev-parse", "refs/harness/deployed") == git("rev-parse", "HEAD"),
           "deploy 1: DONE, the deployed ref moved to HEAD")
    live = sha(TARGET / "current/app.py")
    write("app/app.py", APP_BROKEN)
    git("commit", "-qam", "new status text")
    n = len(ops())
    r = deploy("[*] new status text")
    out(r.stderr, keep=lambda ln: "failed" in ln or "stopped" in ln)
    expect(r.returncode == 1 and sha(TARGET / "current/app.py") == live and "swap" not in ops()[n:]
           and "R-0001" in r.stderr, "deploy 2: the test and the regression case fail on the target: BLOCKED, no swap")
    out(gates("QG3"))
    write("app/app.py", APP_BROKEN + "# uncommitted\n")
    n = len(ops())
    r = deploy("[*] from a dirty tree")
    expect(r.returncode == 1 and len(ops()) == n, "deploy 3 from a dirty tree: preflight stops it, nothing shipped")
    write("app/app.py", APP_OK)
    git("commit", "-qam", "status text is ok again")
    expect(deploy("[X] status text is ok again").returncode == 0, "deploy 4 after the fix: DONE")
    journal = [json.loads(ln) for ln in (REPO / "harness/.state/deploys.jsonl").read_text().splitlines()]
    print("  deploy journal: " + ", ".join(f"{j['id']} {j['status']}" for j in journal))
    print("  operations on the target: " + " ".join(ops()))
    g = gates("QG1", "QG3")
    out(g)
    expect("regressions 1/1" in g, "QG1 and QG3 show the regression case passing")

    title("10. QG6 data checks: counters against fixed rules, sticky until a human accepts")
    write("data/search_rows.txt", "0\n")
    write("data/index_size.txt", "1000\n")
    write("harness/config/data-checks.json", json.dumps({"checks": [
        {"id": "rows-in-out", "pattern": "B9", "title": "every loaded row reaches the store",
         "cmd": "python3 -c \"import json; print(json.dumps({'in': 100, 'out': 100}))\"",
         "expect": {"equal": ["in", "out"]}},
        {"id": "search-nonempty", "pattern": "B8", "title": "a smoke query returns rows",
         "cmd": "cat data/search_rows.txt", "expect": {"min": 1}},
        {"id": "index-size", "pattern": "B8", "title": "the index never shrinks by more than 20%",
         "cmd": "cat data/index_size.txt", "expect": {"drop_max": 0.2}}]}, indent=1) + "\n")
    gj = json.loads((REPO / "harness/config/gates.json").read_text())
    gj["gates"]["QG6"] = {"name": "data invariants", "state": "active", "check": "data"}
    write("harness/config/gates.json", json.dumps(gj, indent=1) + "\n")
    dc = ["python3", "harness/core/scripts/data_checks.py"]
    r = run(dc)
    out(r.stdout)
    expect(r.returncode == 1 and "search-nonempty" in gates("QG6"), "an empty smoke query fails, and QG6 names it")
    write("data/search_rows.txt", "5\n")
    expect(run(dc).returncode == 0 and " pass " in gates("QG6"), "with rows again every check passes")
    write("data/index_size.txt", "700\n")
    r1, r2 = run(dc), run(dc)
    out(r2.stdout, keep=lambda ln: "index-size" in ln)
    expect(r1.returncode == 1 and r2.returncode == 1, "a 30% drop fails, and fails again on the next run")
    r = run(dc + ["--accept", "index-size", "--reason", "old documents were archived on purpose"])
    out(r.stdout)
    expect(run(dc).returncode == 0, "after a human accepts the new level it is the baseline")

    title("11. QG2 commit scanner: a secret is reported by place and kind, never by value")
    write("app/settings.py", 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    git("add", "-A")
    git("commit", "-qm", "settings")
    r = run(["python3", "harness/core/scripts/commit_scan.py"])
    out(r.stderr)
    expect(r.returncode == 1 and "app/settings.py:1" in r.stderr and "AKIA" not in r.stdout + r.stderr,
           "the finding names the place and the kind; the value is not printed")

    title("12. Sandbox settings: required, written, kept on")
    write("harness/config/sandbox.json", json.dumps({"enabled": True, "required": True,
                                                      "allowed_domains": ["github.com", "pypi.org"],
                                                      "deny_read": ["~/.ssh"]}) + "\n")
    g = gates("QG0")
    expect(" fail " in g and "differs" in g, "a required sandbox missing from the settings fails QG0")
    r = run(["python3", "harness/core/scripts/sandbox_config.py", "--apply"])
    out(r.stdout)
    block = json.loads((REPO / ".claude/settings.json").read_text())["sandbox"]
    expect(block["enabled"] and block["failIfUnavailable"] and block["allowUnsandboxedCommands"] is False,
           "written: on, required, no retry outside the sandbox")
    g = gates("QG0")
    out(g)
    expect("sandbox on, 2 allowed domains, required" in g, "QG0 shows the sandbox")
    write(".claude/settings.local.json", '{"sandbox": {"enabled": false}}\n')
    r = hook("config_guard.py", {"hook_event_name": "ConfigChange", "source": "local_settings", "session_id": "cfg2"})
    expect('"block"' in r.stdout and "sandbox is off" in r.stdout, "switching a required sandbox off is blocked")
    (REPO / ".claude/settings.local.json").unlink()

    title("13. Upgrade: untouched kit files are replaced; a local edit becomes .harness-new")
    nxt = WORK / "kit-next"
    shutil.copytree(KIT, nxt, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    old_v = (nxt / "VERSION").read_text().strip()
    major, minor, patch_n = (int(x) for x in old_v.split("."))
    new_v = f"{major}.{minor}.{patch_n + 1}"
    for rel in ("VERSION", "payload/harness/core/VERSION"):
        write(rel, new_v + "\n", root=nxt)
    for rel in ("payload/harness/core/rules.md", "payload/harness/core/docs/design.md"):
        p = nxt / rel
        p.write_text(p.read_text() + f"\nA line added in kit {new_v}.\n")
    cl = nxt / "CHANGELOG.md"
    cl.write_text(cl.read_text().replace(f"## {old_v}", f"## {new_v} - 2026-10-25\n\n[*] One line added to rules.md and design.md\n\n## {old_v}", 1))
    p = REPO / "harness/core/rules.md"
    p.write_text(p.read_text() + "\nLocal tweak made in the project.\n")
    hj = REPO / "harness/config/harness.json"
    hj.write_text(hj.read_text().replace('"my-project"', '"demo-shop"'))
    g = gates("QG1")
    out(g)
    expect(" warn " in g and "changed locally" in g, "the gate table warns about the local edit of a kit file")
    out(harness("status", str(REPO), kit=nxt).stdout)
    r = harness("upgrade", str(REPO), kit=nxt)
    out(r.stdout, keep=lambda ln: "conflict" in ln or "(" in ln)
    expect(r.returncode == 1, "upgrade exits 1: one conflict to resolve")
    expect(sha(REPO / "harness/core/docs/design.md") == sha(nxt / "payload/harness/core/docs/design.md"),
           "the untouched design.md is replaced by the new version")
    rules = (REPO / "harness/core/rules.md").read_text()
    hn = REPO / "harness/core/rules.md.harness-new"
    expect("Local tweak" in rules and hn.is_file() and f"kit {new_v}" in hn.read_text(),
           "the edited rules.md is kept; the new version waits next to it as .harness-new")
    expect('"demo-shop"' in hj.read_text(), "the project-owned harness.json is untouched")
    expect(json.loads((REPO / "harness/harness.lock.json").read_text())["version"] == new_v,
           f"the lock records {new_v}")

    title("14. The gate table at the end")
    out(gates())
    print(f"\n{COUNT['ok']} expectations met, {len(FAILS)} not met, {time.monotonic() - BEGAN:.0f} s")
    for f in FAILS:
        print("  " + f)
    if FAILS or keep:
        print(f"work folder kept: {WORK}")
    else:
        shutil.rmtree(WORK, ignore_errors=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
