"""Digest of a Claude Code conversation transcript (*.jsonl) as readable Markdown.

Keeps: the user's prompts (including those sent mid-turn), the text of Claude's answers,
context compaction summaries. Drops: tool calls and output, images, thinking, system
insertions (reminders, hook output, tool lists). A new session in another account can
read what was decided and why without the raw transcript.

Identifiers should not appear in conversations, but long numbers are masked anyway as
[number]: a number of 6+ digits after words like id, doc, record, patient, key, and any
standalone integer of 6..9 digits. Counts written with spaces between digit groups
("499 190") stay. Extra patterns: env DIGEST_MASK, one regex per line.

    python3 digest.py <transcript.jsonl> <out.md>
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ID_NEAR = re.compile(
    r"((?:id|ID|Id|doc\w*|record\w*|patient\w*|customer\w*|key|/document/|/patient/)[^\d\n]{0,30})(\d{6,})")
LONG_NUMBER = re.compile(r"(?<![\w.,:/-])\d{6,9}(?![\w.,:/-])")
EXTRA = [re.compile(p) for p in os.environ.get("DIGEST_MASK", "").splitlines() if p.strip()]
SKIP_USER = ("<command-", "<local-command", "<system-reminder", "<task-notification",
             "Caveat:", "[Request interrupted")


def mask(text: str) -> tuple[str, int]:
    text, a = ID_NEAR.subn(lambda m: m.group(1) + "[number]", text)
    text, b = LONG_NUMBER.subn("[number]", text)
    n = a + b
    for rx in EXTRA:
        text, k = rx.subn("[masked]", text)
        n += k
    return text, n


def user_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def main(src: Path, dst: Path) -> None:
    out, masked, turns, title = [], 0, 0, ""
    for line in src.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind, at = d.get("type"), (d.get("timestamp") or "")[:16].replace("T", " ")
        if kind == "ai-title" and d.get("aiTitle"):
            title = d["aiTitle"]
        if d.get("isSidechain"):
            continue
        text, who = "", ""
        if kind == "user" and not d.get("isMeta"):
            text = user_text(d.get("message", {}).get("content", "")).strip()
            if d.get("isCompactSummary"):
                who = "Context compaction summary"
            elif text and not text.startswith(SKIP_USER):
                who = "User"
            else:
                text = ""
        elif kind == "attachment" and (d.get("attachment") or {}).get("type") == "queued_command":
            text, who = (d["attachment"].get("prompt") or "").strip(), "User (mid-turn)"
        elif kind == "assistant":
            blocks = d.get("message", {}).get("content", [])
            if isinstance(blocks, list):
                text = "\n".join(b.get("text", "") for b in blocks
                                 if isinstance(b, dict) and b.get("type") == "text").strip()
            who = "Claude"
        if not text or not who:
            continue
        text, n = mask(text)
        masked += n
        turns += 1
        out.append(f"### {who} ({at} UTC)\n\n{text}\n")
    head = (f"# Conversation {src.stem}\n\n"
            f"{('Topic: ' + title + chr(10) + chr(10)) if title else ''}"
            f"Turns: {turns}. Numbers masked: {masked}. Tool output not included.\n\n")
    dst.write_text(head + "\n".join(out), encoding="utf-8")
    print(f"{dst.name}: turns {turns}, masked {masked}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
