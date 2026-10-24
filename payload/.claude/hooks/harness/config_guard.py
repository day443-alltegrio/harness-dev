#!/usr/bin/env python3
"""ConfigChange hook for Claude Code: settings never weaken the harness mid-session (QG0).

Claude Code runs it when .claude/settings.json, .claude/settings.local.json,
~/.claude/settings.json, a managed settings file or a skill file changes during a
session. A change is blocked ({"decision": "block"}: the new settings are not applied
to the running session) when, after it:
  - hooks are switched off (disableAllHooks) at any level;
  - the project settings no longer wire the harness hooks (guard, Stop check, this
    hook), or the guard sees fewer tools than the kit wires it for;
  - a deny rule of the kit for secret files is gone from the project settings;
  - the sandbox is off or has its escape hatch open while harness/config/sandbox.json
    says it is required;
  - a kit-owned skill (.claude/skills/harness-*) changed: its change goes to harness-dev.
Managed settings cannot be blocked (Claude Code ignores the decision); they are logged.

Claude Code shows a blocked change to nobody, and the file on disk stays changed for
the next session. So every block is logged (.claude/hooks/harness/log/<date>.jsonl,
rule config-change), and the gate table checks the wiring at every report (gates.py,
QG0). The wiring ends with `|| exit 2`: if this hook fails, the change is blocked.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HOOKS = Path(os.environ.get("HARNESS_HOOKS_DIR") or HERE)
HOOK_SCRIPTS = ("guard.py", "stop_check.py", "config_guard.py")
SETTINGS = {"project_settings": ".claude/settings.json", "local_settings": ".claude/settings.local.json"}


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def wired(settings: dict) -> dict[str, list[dict]]:
    """Kit hook script name -> the entries of settings that run it."""
    out: dict[str, list[dict]] = {name: [] for name in HOOK_SCRIPTS}
    for entries in (settings.get("hooks") or {}).values():
        for e in entries if isinstance(entries, list) else []:
            for h in e.get("hooks", []) if isinstance(e, dict) else []:
                for name in HOOK_SCRIPTS:
                    if f".claude/hooks/harness/{name}" in str(h.get("command", "")):
                        out[name].append(e)
    return out


def problems(root: Path, source: str, file_path: str | None, home: Path | None = None) -> list[str]:
    """Why the settings after this change weaken the harness; empty when they do not."""
    home = home or Path.home()
    found: list[str] = []
    files = {"project_settings": root / SETTINGS["project_settings"],
             "local_settings": root / SETTINGS["local_settings"],
             "user_settings": home / ".claude" / "settings.json"}
    loaded = {k: read_json(p) for k, p in files.items()}
    for k, data in loaded.items():
        if data is None:
            found.append(f"{files[k].name} ({k}) is not valid JSON")
        elif data.get("disableAllHooks"):
            found.append(f"disableAllHooks in {k}")
    project = loaded["project_settings"] or {}
    frag = read_json(root / "harness" / "core" / "settings.fragment.json") or {}
    links = wired(project)
    for name in HOOK_SCRIPTS:
        if not links[name] and (name != "config_guard.py" or "ConfigChange" in (frag.get("hooks") or {})):
            found.append(f"{name} is no longer wired in .claude/settings.json")
    want = set(((frag.get("hooks") or {}).get("PreToolUse") or [{}])[0].get("matcher", "").split("|")) - {""}
    have = {t for e in links["guard.py"] for t in str(e.get("matcher", "")).split("|")}
    if links["guard.py"] and want - have:
        found.append(f"the guard no longer sees {', '.join(sorted(want - have))}")
    deny = set((project.get("permissions") or {}).get("deny") or [])
    gone = [r for r in (frag.get("permissions") or {}).get("deny") or [] if r not in deny]
    if gone:
        found.append(f"deny rules for secret files removed: {', '.join(gone)}")
    sandbox_conf = read_json(root / "harness" / "config" / "sandbox.json") or {}
    if sandbox_conf.get("required"):
        layers = [project.get("sandbox") or {}, (loaded["local_settings"] or {}).get("sandbox") or {}]
        enabled = next((s["enabled"] for s in reversed(layers) if "enabled" in s), False)
        escape = next((s["allowUnsandboxedCommands"] for s in reversed(layers)
                       if "allowUnsandboxedCommands" in s), True)
        if not enabled:
            found.append("the sandbox is off, but harness/config/sandbox.json requires it")
        elif escape:
            found.append("the sandbox lets commands retry outside it (allowUnsandboxedCommands)")
    if source == "skills" and file_path:
        rel = Path(file_path)
        try:
            rel = rel.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            pass
        if rel.as_posix().startswith(".claude/skills/harness-"):
            found.append(f"kit-owned skill {rel.as_posix()} changed: the change goes to harness-dev")
    return found


def log(event: dict, decision: str) -> str:
    log_dir = HOOKS / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    did = hashlib.sha256(f"{time.time_ns()}|{event.get('session_id')}|config".encode()).hexdigest()[:8]
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "ConfigChange",
           "agent": event.get("agent_type") or "main", "rule": "config-change",
           "decision": decision, "session": event.get("session_id"), "id": did,
           "source": event.get("source")}
    with open(log_dir / f"{time.strftime('%Y-%m-%d')}.jsonl", "a", encoding="utf-8") as out:
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return did


def handle(event: dict, root: Path = ROOT, home: Path | None = None) -> dict | None:
    source = event.get("source") or ""
    found = problems(root, source, event.get("file_path"), home)
    if not found:
        return None
    if source == "policy_settings":
        log(event, "logged")  # managed settings always apply; the change is on record
        return None
    did = log(event, "block")
    return {"decision": "block", "reason": f"[config-change #{did}] " + "; ".join(found)}


def main() -> int:
    out = handle(json.load(sys.stdin))
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
