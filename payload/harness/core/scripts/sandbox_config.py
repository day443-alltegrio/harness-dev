#!/usr/bin/env python3
"""The operating system sandbox of Claude Code, from one project file (design.md, section 7).

Hooks read the text of a command and can be bypassed (a script, another language, an
encoded string). The sandbox is enforced by the operating system for every Bash command
and everything it starts: network only to allowed domains through a proxy, writes only
in the project and temp folders, reads denied where listed. It is the strongest
boundary; the guard hook stays as the second line, and Read, Edit, Write and WebFetch
stay under permission rules, which the sandbox does not cover.

harness/config/sandbox.json holds the project's choice; this script writes the matching
"sandbox" block into .claude/settings.json and checks that it is still there. Keys of
Claude Code it writes (code.claude.com/docs/en/sandboxing, CLI 2.1.308): enabled,
failIfUnavailable (when required), allowUnsandboxedCommands (always false: no retry
outside the sandbox), autoAllowBashIfSandboxed, excludedCommands, filesystem.denyRead,
filesystem.allowWrite, network.allowedDomains, network.deniedDomains.

Platforms: macOS (Seatbelt, built in); Linux and WSL2 need bubblewrap and socat.

    python3 harness/core/scripts/sandbox_config.py --show        # the block it would write
    python3 harness/core/scripts/sandbox_config.py --check       # exit 1 when settings differ
    python3 harness/core/scripts/sandbox_config.py --apply       # write it (a human confirms)
    python3 harness/core/scripts/sandbox_config.py --suggest [--days 30]   # hosts the agent used
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
DEFAULTS = {"enabled": False, "required": False, "allowed_domains": [], "denied_domains": [],
            "allow_write": [], "deny_read": [], "excluded_commands": [], "auto_allow_bash": True}
HOST = re.compile(r"(?:https?|wss?|ftp)://([A-Za-z0-9.-]+)|(?:^|[\s'\"])(?:[\w.-]+@)?"
                  r"([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+):(?!//)")
NET_CMD = re.compile(r"\b(curl|wget|git|ssh|scp|rsync|pip|pip3|uv|uvx|npm|npx|pnpm|yarn|go|cargo|"
                     r"docker|gh|helm|kubectl|terraform|apt|apt-get|brew)\b")


def conf_path(root: Path) -> Path:
    return root / harness_config.load(root)["sandbox"]["file"]


def load(root: Path = ROOT) -> dict:
    """sandbox.json over the defaults; a missing file means the sandbox is off."""
    p = conf_path(root)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    unknown = [k for k in data if not k.startswith("_") and k not in DEFAULTS]
    if unknown:
        raise ValueError(f"{p.name}: unknown keys {', '.join(unknown)}")
    return {**DEFAULTS, **{k: v for k, v in data.items() if not k.startswith("_")}}


def render(conf: dict) -> dict:
    """The "sandbox" block of .claude/settings.json for this choice."""
    block = {"enabled": bool(conf["enabled"]), "failIfUnavailable": bool(conf["required"]),
             "allowUnsandboxedCommands": False,
             "autoAllowBashIfSandboxed": bool(conf["auto_allow_bash"]),
             "network": {"allowedDomains": list(conf["allowed_domains"])}}
    if conf["denied_domains"]:
        block["network"]["deniedDomains"] = list(conf["denied_domains"])
    fs = {k: list(conf[c]) for k, c in (("denyRead", "deny_read"), ("allowWrite", "allow_write")) if conf[c]}
    if fs:
        block["filesystem"] = fs
    if conf["excluded_commands"]:
        block["excludedCommands"] = list(conf["excluded_commands"])
    return block


def settings_path(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def current(root: Path) -> dict | None:
    p = settings_path(root)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("sandbox")


def check(root: Path = ROOT) -> tuple[bool, str]:
    """(in order, a one-line state) for the gate table."""
    conf = load(root)
    have = current(root)
    if not conf["enabled"]:
        if have and have.get("enabled"):
            return False, "sandbox on in settings, but off in harness/config/sandbox.json: run --apply"
        return True, "sandbox off (harness/config/sandbox.json)"
    want = render(conf)
    if have != want:
        return False, "the sandbox in .claude/settings.json differs from harness/config/sandbox.json: run --apply"
    return True, f"sandbox on, {len(want['network']['allowedDomains'])} allowed domains" + \
        (", required" if conf["required"] else "")


def apply(root: Path = ROOT) -> dict:
    """Write the block into .claude/settings.json; the rest of the file is kept."""
    p = settings_path(root)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    data["sandbox"] = render(load(root))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data["sandbox"]


def hosts_in(command: str) -> list[str]:
    if not NET_CMD.search(command):
        return []
    out = []
    for a, b in HOST.findall(command):
        host = (a or b).lower().rstrip(".")
        if host and not re.fullmatch(r"[\d.]+", host) and "." in host:
            out.append(host)
    return out


def suggest(project_dir: Path, days: int) -> Counter:
    """Hosts in the Bash commands and WebFetch URLs of the agent's transcripts: names and
    counts only, the list to start allowed_domains from."""
    since = (dt.datetime.now() - dt.timedelta(days=days)).isoformat()
    seen: Counter = Counter()
    for f in sorted(project_dir.glob("**/*.jsonl")) if project_dir.is_dir() else []:
        with open(f, encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if (d.get("timestamp") or "") < since or d.get("type") != "assistant":
                    continue
                msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                for b in msg.get("content") or []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    args = b.get("input") or {}
                    if b.get("name") == "Bash":
                        seen.update(hosts_in(str(args.get("command", ""))))
                    elif b.get("name") == "WebFetch":
                        seen.update(h.lower() for h, _ in HOST.findall(str(args.get("url", ""))) if h)
    return seen


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description="The Claude Code sandbox from harness/config/sandbox.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--suggest", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args(argv)
    try:
        conf = load(root)
    except (ValueError, OSError) as err:
        print(err)
        return 2
    if args.show:
        print(json.dumps({"sandbox": render(conf)}, indent=2))
        return 0
    if args.check:
        ok, line = check(root)
        print(line)
        return 0 if ok else 1
    if args.apply:
        block = apply(root)
        print(f"wrote the sandbox block to .claude/settings.json (enabled: {block['enabled']}); "
              "restart Claude Code, then check with: touch ~/sandbox-probe (must fail)")
        return 0
    project = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))
    seen = suggest(project, args.days)
    allowed = set(conf["allowed_domains"])
    for host, n in seen.most_common():
        print(f"{n:>5}  {host}{'  (allowed)' if host in allowed else ''}")
    print(f"{len(seen)} hosts in {args.days} days of transcripts; add the ones the work needs to "
          "allowed_domains in harness/config/sandbox.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
