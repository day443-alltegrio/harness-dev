#!/usr/bin/env python3
"""Context budget of the agent (QG1): how much text Claude Code loads into a session.

Counts UTF-8 bytes; the limits live in harness/config/budgets.json, one entry per
budget, by kind:
  imports - a file and everything it imports with `@path` lines (CLAUDE.md is loaded
            into every session, imports included);
  files   - a fixed list of files (rules loaded for one kind of work);
  skills  - descriptions of the project skills: the list of skills with their
            descriptions also goes into every session; max_bytes_each per skill;
  memory  - the agent memory of this project on this machine (optional).

Excess context makes the agent worse, so going over is a failure, not a warning. A
limit is raised on purpose, by an ordinary change of budgets.json.

    python3 harness/core/scripts/context_budget.py          # report, exit 1 over a limit
    python3 harness/core/scripts/context_budget.py --json   # numbers for the snapshot
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
BUDGETS = ROOT / "harness" / "config" / "budgets.json"
IMPORT = re.compile(r"^@(\S+)\s*$")


def slug(path: Path) -> str:
    """Folder name of the project in ~/.claude/projects: the path with non-letters as '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def with_imports(entry: Path, seen: set[Path] | None = None) -> list[Path]:
    """The file and everything it imports with `@path` lines (recursive, no cycles)."""
    seen = set() if seen is None else seen
    entry = entry.resolve()
    if entry in seen or not entry.is_file():
        return []
    seen.add(entry)
    out = [entry]
    for line in entry.read_text(encoding="utf-8").splitlines():
        m = IMPORT.match(line.strip())
        if m:
            target = Path(m.group(1)).expanduser()
            if not target.is_absolute():
                target = entry.parent / target
            out += with_imports(target, seen)
    return out


def size(paths: list[Path]) -> int:
    return sum(p.stat().st_size for p in paths if p.is_file())


def skill_description(skill_md: Path) -> str:
    """The description field of the SKILL.md front matter (folded >- included)."""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ""
    head = text.split("---", 2)[1]
    lines, grab = [], False
    for line in head.splitlines():
        if line.startswith("description:"):
            grab = True
            rest = line[len("description:"):].strip()
            if rest and rest not in (">-", ">", "|", "|-"):
                lines.append(rest)
            continue
        if grab:
            if line and not line[0].isspace():
                break
            lines.append(line.strip())
    return " ".join(x for x in lines if x)


def _rel(root: Path, p: Path) -> str:
    r = root.resolve()
    return str(p.relative_to(r)) if str(p).startswith(str(r)) else str(p)


def measure(root: Path = ROOT, budgets: dict | None = None) -> list[dict]:
    """Report rows: name, bytes, limit, within the limit, details."""
    if budgets is None:
        budgets = json.loads((root / "harness" / "config" / "budgets.json").read_text(encoding="utf-8"))
    rows = []
    for b in budgets["budgets"]:
        row = {"name": b["name"], "max": b["max_bytes"]}
        kind = b["kind"]
        if kind == "imports":
            files = with_imports(root / b["entry"])
            row.update(bytes=size(files), files=[_rel(root, p) for p in files])
        elif kind == "files":
            row.update(bytes=size([root / f for f in b["files"]]), files=b["files"])
        elif kind == "skills":
            total, over = 0, []
            for skill in sorted((root / b["dir"]).glob("*/SKILL.md")):
                n = len(skill_description(skill).encode("utf-8"))
                total += n
                if n > b["max_bytes_each"]:
                    over.append(f"{skill.parent.name}: {n}")
            row.update(bytes=total, over_each=over, max_each=b["max_bytes_each"])
        elif kind == "memory":
            mem = Path(b["dir"].replace("{slug}", slug(root.resolve()))).expanduser()
            if not mem.is_dir() and b.get("optional"):
                continue
            row.update(bytes=size(sorted(mem.glob("*.md"))))
        else:
            raise ValueError(f"unknown budget kind {kind!r} in {b['name']}")
        row["ok"] = row["bytes"] <= row["max"] and not row.get("over_each")
        rows.append(row)
    return rows


def main(argv: list[str]) -> int:
    rows = measure()
    if "--json" in argv:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            mark = "ok  " if r["ok"] else "OVER"
            print(f"{mark} {r['name']:28} {r['bytes']:>7} / {r['max']} bytes")
            for o in r.get("over_each", []):
                print(f"      skill description over {r['max_each']}: {o}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
