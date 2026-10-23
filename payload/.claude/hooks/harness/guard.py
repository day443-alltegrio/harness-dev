#!/usr/bin/env python3
"""PreToolUse guard hook for Claude Code: the agent's action boundaries (QG0).

Reads the hook event from stdin (Claude Code JSON) and answers with JSON:
  deny    - blocked, with a reason the agent sees;
  ask     - a confirmation prompt for the human;
  nothing - the normal permission rules apply.

Rules (each one grew out of a real failure; project patterns live in guard.json):
  git-destructive  git stash, reset, checkout, restore, clean, switch: the working
                   tree always holds uncommitted work, these commands lose it;
  git-coauthor     a commit with a Co-Authored-By trailer (commit rule, optional);
  secrets-read     reading secret files, by a command or with the Read tool;
  git-push         push only after a human confirms;
  outbound         data leaving the perimeter: curl/wget/scp/rsync to a host not in
                   internal_hosts, publishing tools, gh calls that create content;
  deploy           shipping code to machines;
  repeat-budget    the same command for the N-th time in a row: the agent is looping
                   on one fix and should stop and ask.

A failure of the hook itself blocks the action: settings.json ends the command with
`|| exit 2`. Decision log (rule and decision, never the command text):
.claude/hooks/harness/log/<date>.jsonl, outside git. Project patterns: the "guard"
section of .claude/harness-hooks.json. The hook and its config live in .claude/, so
Claude Code asks a human before the agent edits either of them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
# Tests point this at a temporary folder so they never write the real log.
HOOKS = Path(os.environ.get("HARNESS_HOOKS_DIR") or HERE)
CONFIG = Path(os.environ.get("HARNESS_HOOKS_CONFIG") or ROOT / ".claude" / "harness-hooks.json")

DEFAULTS: dict = {
    "rules": {"git-destructive": True, "git-coauthor": True, "secrets-read": True,
              "git-push": True, "outbound": True, "deploy": True, "repeat-budget": True},
    # Folders (with a trailing slash) and file names that hold secrets.
    "secret_dirs": ["secrets/", ".secrets/"],
    "secret_files": [r"[\w.-]*\.env", r"secrets\.env"],
    # Commands that ship code to machines: asked, never blocked.
    "deploy": [r"(^|[\s/])deploy/[\w.-]*(sync|deploy|release)[\w.-]*\.sh\b",
               r"harness/core/scripts/deploy\.sh\b",
               r"(^|[;&|(]\s*|\s)kubectl\s+(apply|delete|replace|rollout|scale|set)\b",
               r"(^|[;&|(]\s*|\s)helm\s+(install|upgrade|uninstall|rollback)\b",
               r"(^|[;&|(]\s*|\s)terraform\s+(apply|destroy|import)\b",
               r"(^|[;&|(]\s*|\s)ansible-playbook\b",
               r"(^|[;&|(]\s*|\s)docker\s+push\b"],
    # Hosts inside the perimeter (regex per host); everything else is outbound.
    "internal_hosts": [r"127\.0\.0\.1", r"localhost", r"0\.0\.0\.0", r"\[::1\]"],
    # Publishing commands: content leaves the perimeter even without curl.
    "publish": [
        r"(^|[;&|(]\s*|\s)gh\s+(?:pr|issue|release|gist|repo)\s+(?:create|edit|comment|close|merge|delete)",
        r"(^|[;&|(]\s*|\s)gh\s+api\b[^;&|]*(?:-X\s*(?:POST|PUT|PATCH|DELETE)"
        r"|--method\s+(?:POST|PUT|PATCH|DELETE)|-f\s|--field)",
    ],
    "repeat_limit": 4,
    "messages": {
        "git-destructive": "git stash/reset/checkout/restore/clean/switch are forbidden: the tree "
                           "holds uncommitted work. Compare with git show HEAD:path or git diff; "
                           "for a clean copy use a separate directory.",
        "git-coauthor": "Commit without Co-Authored-By or session trailers (project commit rule).",
        "secrets-read": "Secrets are never read or printed: scripts load them from the file "
                        "themselves.",
        "git-push": "Push only when the user says \"push\".",
        "outbound": "Upload outside the perimeter: the data must hold no personal data, internal "
                    "IDs or secrets (scanner: harness/core/scripts/commit_scan.py). A human confirms.",
        "deploy": "Deploying code only after the user's \"yes\" for this deploy.",
        "repeat-budget": "The same command ran {n} times in a row. After the third failed attempt "
                         "at the same fix, stop and ask the human.",
    },
}

GIT_DESTRUCTIVE = re.compile(
    r"(^|[;&|(]|\bsudo|\benv)\s*git\s+(-C\s+\S+\s+)?"
    r"(stash(?!\s+(list|show)\b)|reset|checkout|restore|clean|switch)\b")
GIT_COMMIT = re.compile(r"(^|[;&|(])\s*git\s+(-C\s+\S+\s+)?commit\b")
COAUTHOR = re.compile(r"co-authored-by\s*:", re.I)
GIT_PUSH = re.compile(r"(^|[;&|(])\s*git\s+(-C\s+\S+\s+)?push\b")
READERS = (r"\b(cat|less|more|head|tail|grep|egrep|rg|sed|awk|strings|xxd|od|base64|cp|scp|"
           r"nl|bat|open|source|\.)\s[^|;&]*")
URL_HOST = re.compile(r"https?://([^/\s:'\"]+)")
NET_TOOL = re.compile(r"(^|[;&|(]\s*|\s)(curl|wget)\b")
COPY_TOOL = re.compile(r"(^|[;&|(]\s*|\s)(scp|rsync)\b[^;&|]*?\s(?:[\w.-]+@)?([\w.-]+):")


class Rules:
    """Compiled project rules (guard.json over DEFAULTS)."""

    def __init__(self, conf: dict):
        self.on = {**DEFAULTS["rules"], **conf.get("rules", {})}
        self.messages = {**DEFAULTS["messages"], **conf.get("messages", {})}
        dirs = conf.get("secret_dirs", DEFAULTS["secret_dirs"])
        files = conf.get("secret_files", DEFAULTS["secret_files"])
        self.secret_dirs = [d.strip("/") + "/" for d in dirs]
        self.secret_file = re.compile(rf"^(?:{'|'.join(files)})$") if files else None
        parts = [rf"(^|[\s/'\"=]){re.escape(d)}" for d in self.secret_dirs]
        if files:
            parts.append(rf"(^|[\s/'\"=])(?:{'|'.join(files)})\b(?!\.example)")
        self.secret_read = re.compile(READERS + "(" + "|".join(parts) + ")") if parts else None
        self.deploy = [re.compile(p) for p in conf.get("deploy", DEFAULTS["deploy"])]
        hosts = conf.get("internal_hosts", DEFAULTS["internal_hosts"])
        self.internal = re.compile(rf"^(?:{'|'.join(hosts)})$")
        self.publish = [re.compile(p) for p in conf.get("publish", DEFAULTS["publish"])]
        self.repeat_limit = int(conf.get("repeat_limit", DEFAULTS["repeat_limit"]))

    def outbound(self, command: str) -> bool:
        """Does the command send data outside the perimeter."""
        if any(p.search(command) for p in self.publish):
            return True
        if NET_TOOL.search(command):
            if any(not self.internal.match(h) for h in URL_HOST.findall(command)):
                return True
        return any(not self.internal.match(m.group(3)) for m in COPY_TOOL.finditer(command))

    def verdict(self, rule: str, decision: str, **fmt) -> tuple[str, str, str]:
        msg = self.messages[rule]
        return decision, rule, msg.format(**fmt) if fmt else msg

    def decide_bash(self, command: str) -> tuple[str, str, str] | None:
        """(decision, rule, reason) or None when the hook stays out."""
        on = self.on
        if on["git-destructive"] and GIT_DESTRUCTIVE.search(command):
            return self.verdict("git-destructive", "deny")
        if on["git-coauthor"] and GIT_COMMIT.search(command) and COAUTHOR.search(command):
            return self.verdict("git-coauthor", "deny")
        if on["secrets-read"] and self.secret_read and self.secret_read.search(command):
            return self.verdict("secrets-read", "deny")
        if on["git-push"] and GIT_PUSH.search(command):
            return self.verdict("git-push", "ask")
        if on["outbound"] and self.outbound(command):
            return self.verdict("outbound", "ask")
        if on["deploy"] and any(p.search(command) for p in self.deploy):
            return self.verdict("deploy", "ask")
        return None

    def decide_read(self, path: str) -> tuple[str, str, str] | None:
        if not self.on["secrets-read"]:
            return None
        p = path.replace("\\", "/")
        in_dir = any(f"/{d}" in p or p.startswith(d) for d in self.secret_dirs)
        name = p.rsplit("/", 1)[-1]
        if in_dir or (self.secret_file and self.secret_file.match(name)
                      and not name.endswith(".example")):
            return self.verdict("secrets-read", "deny")
        return None


def load_rules(path: Path = CONFIG) -> Rules:
    try:
        conf = json.loads(path.read_text(encoding="utf-8")).get("guard", {})
    except FileNotFoundError:
        conf = {}
    return Rules(conf)


def repeat_streak(session: str, command: str, state_dir: Path | None = None) -> int:
    """How many times in a row this session runs the same command (this one included)."""
    state_dir = state_dir or HOOKS / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', session)[:80]}.json"
    digest = hashlib.sha256(command.strip().encode("utf-8")).hexdigest()
    try:
        st = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    streak = st.get("streak", 0) + 1 if st.get("last") == digest else 1
    f.write_text(json.dumps({"last": digest, "streak": streak}), encoding="utf-8")
    return streak


def log(event: dict, decision: str, rule: str, log_dir: Path | None = None) -> None:
    log_dir = log_dir or HOOKS / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": event.get("tool_name"),
           "agent": event.get("agent_type") or "main", "rule": rule, "decision": decision,
           "session": event.get("session_id")}
    with open(log_dir / f"{day}.jsonl", "a", encoding="utf-8") as out:
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")


def handle(event: dict, rules: Rules | None = None) -> dict | None:
    rules = rules or load_rules()
    tool = event.get("tool_name")
    args = event.get("tool_input") or {}
    verdict = None
    if tool == "Bash":
        command = args.get("command", "")
        verdict = rules.decide_bash(command)
        if (verdict is None and rules.on["repeat-budget"]
                and repeat_streak(event.get("session_id", "none"), command) >= rules.repeat_limit):
            verdict = rules.verdict("repeat-budget", "ask", n=rules.repeat_limit - 1)
    elif tool == "Read":
        verdict = rules.decide_read(args.get("file_path", ""))
    if verdict is None:
        return None
    decision, rule, reason = verdict
    log(event, decision, rule)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": decision,
                                   "permissionDecisionReason": f"[{rule}] {reason}"}}


def main() -> int:
    out = handle(json.load(sys.stdin))
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
