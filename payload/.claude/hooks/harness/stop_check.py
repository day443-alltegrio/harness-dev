#!/usr/bin/env python3
"""Stop hook for Claude Code: fast checks before the agent finishes its answer (QG0).

Takes the files changed since the last clean check of this session (git status plus
modification time, so edits made through sed or scripts are caught too, which a
PostToolUse hook on Edit would miss) and runs the quick checks configured in the
"stop" section of .claude/harness-hooks.json: syntax, style, whatever the project adds.
A failure sends the agent back to work with the output ({"decision": "block"}); after
max_blocks blocks in a row the answer may end, with a warning to the human. Claude
Code itself lifts a Stop block after 8 in a row.

Decision log, as for the guard: .claude/hooks/harness/log/<date>.jsonl (rule
stop-check), never the file contents.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HOOKS = Path(os.environ.get("HARNESS_HOOKS_DIR") or HERE)
CONFIG = Path(os.environ.get("HARNESS_HOOKS_CONFIG") or ROOT / ".claude" / "harness-hooks.json")

DEFAULTS = {
    "enabled": True,
    "max_blocks": 2,
    "timeout_s": 60,
    "checks": [
        {"name": "syntax", "glob": ["*.py", "*.json", "*.toml", "*.sh"],
         "cmd": "python3 harness/core/scripts/syntax_check.py {files}"},
    ],
}
MAX_FILES = 200


def load_conf(path: Path = CONFIG) -> dict:
    try:
        conf = json.loads(path.read_text(encoding="utf-8")).get("stop", {})
    except FileNotFoundError:
        conf = {}
    return {**DEFAULTS, **{k: v for k, v in conf.items() if not k.startswith("_")}}


def changed_files(root: Path, since: float) -> list[str]:
    """Uncommitted files (new and modified, not deleted) written after `since`."""
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                         capture_output=True, text=True).stdout
    files = []
    for line in out.splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        p = root / path
        if p.is_file() and p.stat().st_mtime >= since:
            files.append(path)
    return sorted(files)


def matches(path: str, globs: list[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(name, g) for g in globs)


def run_checks(root: Path, files: list[str], conf: dict) -> list[str]:
    """One line of output tail per failed check."""
    failures = []
    for check in conf["checks"]:
        hit = [f for f in files if matches(f, check["glob"])]
        if not hit:
            continue
        cmds = ([check["cmd"].replace("{file}", shlex.quote(f)) for f in hit]
                if "{file}" in check["cmd"]
                else [check["cmd"].replace("{files}", " ".join(shlex.quote(f) for f in hit))])
        for cmd in cmds:
            try:
                r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True,
                                   timeout=conf["timeout_s"])
            except subprocess.TimeoutExpired:
                failures.append(f"{check['name']}: over {conf['timeout_s']} s")
                continue
            if r.returncode != 0:
                tail = (r.stdout + r.stderr).strip().splitlines()[-12:]
                failures.append(f"{check['name']} ({cmd}):\n  " + "\n  ".join(tail))
    return failures


def state_path(session: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session)[:80]
    return HOOKS / "state" / f"stop-{safe}.json"


def session_start(transcript: str | None) -> float:
    """When the session began: the first timestamp of its transcript, else an hour ago."""
    try:
        with open(transcript or "", encoding="utf-8") as f:
            for line in f:
                ts = json.loads(line).get("timestamp")
                if ts:
                    from datetime import datetime  # noqa: PLC0415
                    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError):
        pass
    return time.time() - 3600


def log(event: dict, decision: str) -> str:
    """Append the decision to the hook log; returns its id (for a false-block mark)."""
    log_dir = HOOKS / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    did = hashlib.sha256(f"{time.time_ns()}|{event.get('session_id')}".encode()).hexdigest()[:8]
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "Stop",
           "agent": event.get("agent_type") or "main", "rule": "stop-check",
           "decision": decision, "session": event.get("session_id"), "id": did}
    with open(log_dir / f"{time.strftime('%Y-%m-%d')}.jsonl", "a", encoding="utf-8") as out:
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return did


def handle(event: dict, root: Path = ROOT, conf: dict | None = None) -> dict | None:
    conf = conf or load_conf()
    if not conf["enabled"]:
        return None
    sp = state_path(event.get("session_id", "none"))
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    since = st.get("since") or session_start(event.get("transcript_path"))
    now = time.time()
    files = changed_files(root, since)[:MAX_FILES]
    failures = run_checks(root, files, conf) if files else []
    sp.parent.mkdir(parents=True, exist_ok=True)
    if not failures:
        sp.write_text(json.dumps({"since": now, "blocks": 0}), encoding="utf-8")
        return None
    blocks = st.get("blocks", 0)
    if blocks >= conf["max_blocks"]:
        # Let the answer end, but the human sees that checks still fail.
        sp.write_text(json.dumps({"since": now, "blocks": 0}), encoding="utf-8")
        log(event, "warn")
        return {"systemMessage": f"Stop checks still fail after {blocks} rounds: "
                                 + "; ".join(f.splitlines()[0] for f in failures)}
    sp.write_text(json.dumps({"since": since, "blocks": blocks + 1}), encoding="utf-8")
    did = log(event, "block")
    return {"decision": "block",
            "reason": f"[stop-check #{did}] Fast checks failed on the files you changed; fix them "
                      "before finishing:\n" + "\n".join(failures)}


def main() -> int:
    out = handle(json.load(sys.stdin))
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
