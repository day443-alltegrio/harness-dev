#!/usr/bin/env python3
"""Agent telemetry from the Claude Code conversation logs (harness/core/docs/design.md, "Measure").

Reads ~/.claude/projects/<slug>/*.jsonl (main sessions) and
<session>/subagents/*.jsonl (subagents), plus the guard hook log
.claude/hooks/harness/log/*.jsonl. Counts per day (timezone in harness.json), numbers only:
  sessions, prompts      - sessions and human prompts;
  tool_calls, by_tool    - tool calls (main agent and subagents separately);
  tool_errors            - tool results with an error;
  hook_blocks            - guard hook decisions by rule (deny/ask);
  repeat_streaks         - runs of 3+ identical Bash commands (the agent loops on a fix);
  tokens                 - input, output, cache (one message counted once);
  compactions            - context compactions.
No prompt, command or result text reaches the output.

    python3 harness/core/scripts/agent_metrics.py [--days 30]   # JSON on stdout
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
SKIP_PROMPT = ("<command-", "<local-command", "<system-reminder", "<task-notification",
               "Caveat:", "[Request interrupted")


def zone() -> tzinfo | None:
    name = harness_config.load()["timezone"]
    if not name:
        return None
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    return ZoneInfo(name)


TZ = zone()


def slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def day_of(ts: str) -> str | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
    except (ValueError, AttributeError):
        return None


def empty() -> dict:
    return {"sessions": set(), "prompts": 0, "tool_calls": 0, "subagent_tool_calls": 0,
            "by_tool": Counter(), "tool_errors": 0, "hook_blocks": Counter(),
            "repeat_streaks": 0, "tokens": Counter(), "compactions": 0, "subagents": 0}


def prompt_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def scan(path: Path, days: dict, since: str, subagent: bool) -> None:
    seen_msg = set()
    last_cmd, streak = None, 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            day = day_of(d.get("timestamp") or "")
            if not day or day < since:
                continue
            m = days[day]
            kind = d.get("type")
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("sessionId") and not subagent:
                m["sessions"].add(d["sessionId"])
            if kind == "user":
                if d.get("isCompactSummary"):
                    m["compactions"] += 1
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                            m["tool_errors"] += 1
                text = prompt_text(content).strip()
                if not subagent and not d.get("isMeta") and text and not text.startswith(SKIP_PROMPT):
                    m["prompts"] += 1
            elif kind == "assistant":
                mid = msg.get("id") or d.get("requestId")
                usage = msg.get("usage") or {}
                if mid and mid not in seen_msg and usage:
                    seen_msg.add(mid)
                    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                              "cache_creation_input_tokens"):
                        m["tokens"][k] += int(usage.get(k) or 0)
                for b in msg.get("content") or []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    name = b.get("name", "?")
                    m["subagent_tool_calls" if subagent else "tool_calls"] += 1
                    m["by_tool"][name] += 1
                    if name in ("Agent", "Task"):
                        m["subagents"] += 1
                    if name == "Bash":
                        cmd = (b.get("input") or {}).get("command", "")
                        h = hashlib.sha256(cmd.strip().encode()).hexdigest()
                        streak = streak + 1 if h == last_cmd else 1
                        last_cmd = h
                        if streak == 3:
                            m["repeat_streaks"] += 1


def scan_hooks(log_dir: Path, days: dict, since: str) -> None:
    for f in sorted(log_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            day = (rec.get("ts") or "")[:10]
            if day >= since:
                days[day]["hook_blocks"][f"{rec.get('rule')}:{rec.get('decision')}"] += 1


def collect(project_dir: Path, hooks_dir: Path, n_days: int = 30) -> dict:
    since = (datetime.now(TZ).date() - timedelta(days=n_days - 1)).isoformat()
    days: dict = defaultdict(empty)
    files = 0
    for f in sorted(project_dir.glob("*.jsonl")):
        scan(f, days, since, subagent=False)
        files += 1
        for sub in sorted((project_dir / f.stem / "subagents").glob("*.jsonl")):
            scan(sub, days, since, subagent=True)
            files += 1
    scan_hooks(hooks_dir, days, since)
    out = {}
    for day in sorted(days):
        m = days[day]
        out[day] = {**{k: v for k, v in m.items() if not isinstance(v, (set, Counter))},
                    "sessions": len(m["sessions"]),
                    "by_tool": dict(m["by_tool"].most_common(12)),
                    "hook_blocks": dict(m["hook_blocks"]),
                    "tokens": dict(m["tokens"])}
    return {"generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            "transcripts": files, "days": out}


def main(argv: list[str]) -> int:
    n = int(argv[argv.index("--days") + 1]) if "--days" in argv else 30
    project = Path.home() / ".claude" / "projects" / slug(ROOT)
    print(json.dumps(collect(project, harness_config.HOOK_LOG, n), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
