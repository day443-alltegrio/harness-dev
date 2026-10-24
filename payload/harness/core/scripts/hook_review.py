#!/usr/bin/env python3
"""Hook decisions reviewed by people: false blocks marked, a rate per rule (QG0, "Measure").

Every guard and Stop hook decision is logged with an id in
.claude/hooks/harness/log/<date>.jsonl, and the id is in the reason the agent and the
human see, e.g. "[secrets-read #3fa1c2d0] ...". When a decision was wrong (the rule
fired on something harmless), a human marks it as a false block; the marks go to
.claude/hooks/harness/log/marks/false-blocks.jsonl, outside git. A rule whose marked
false blocks pass hooks.false_block_share of its decisions over hooks.window_days
(with at least hooks.false_block_min decisions) is too broad: the gate table warns and
the monthly cleanup reviews it (harness/core/docs/design.md, section 10). A rule nobody
marks is not proven right, so the report shows the decisions too.

Numbers and ids only: the log never holds command text, and a reason should say why
the decision was wrong in general words, never quote data.

    python3 harness/core/scripts/hook_review.py list [--days 1] [--rule R]
    python3 harness/core/scripts/hook_review.py mark ID [ID ...] --reason "why it was harmless"
    python3 harness/core/scripts/hook_review.py mark --last [--rule R] --reason "..."
    python3 harness/core/scripts/hook_review.py report [--days 30] [--json]   # exit 1 over the share
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

DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")
BLOCKING = ("deny", "ask", "block")


def marks_file(log_dir: Path) -> Path:
    return log_dir / "marks" / "false-blocks.jsonl"


def decisions(log_dir: Path, days: int | None = None) -> list[dict]:
    """Logged decisions that stopped or questioned the agent, oldest first."""
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat() if days else ""
    out = []
    for f in sorted(log_dir.glob("*.jsonl")) if log_dir.is_dir() else []:
        if not DAY_FILE.match(f.name) or f.name[:10] < since:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("decision") in BLOCKING:
                out.append(rec)
    return out


def marks(log_dir: Path) -> dict[str, dict]:
    """id -> the latest mark."""
    f = marks_file(log_dir)
    out: dict[str, dict] = {}
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("id"):
                out[rec["id"]] = rec
    return out


def mark(log_dir: Path, ids: list[str], reason: str) -> list[dict]:
    """Mark decisions as false blocks; every id must be a logged decision."""
    reason = reason.strip()
    if not reason:
        raise ValueError("say why the decision was wrong (--reason)")
    known = {d.get("id"): d for d in decisions(log_dir) if d.get("id")}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"no logged decision with id {', '.join(unknown)}")
    f = marks_file(log_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    recs = [{"ts": dt.datetime.now().isoformat(timespec="seconds"), "id": i,
             "rule": known[i].get("rule"), "decision": known[i].get("decision"),
             "verdict": "false", "reason": reason} for i in ids]
    with open(f, "a", encoding="utf-8") as out:
        for rec in recs:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return recs


def report(log_dir: Path, days: int, share: float, minimum: int) -> dict:
    decs = decisions(log_dir, days)
    marked = marks(log_dir)
    per_rule: dict[str, Counter] = {}
    for d in decs:
        c = per_rule.setdefault(d.get("rule") or "?", Counter())
        c["decisions"] += 1
        if d.get("id") in marked:
            c["false"] += 1
    rules = {}
    for rule, c in sorted(per_rule.items()):
        rate = c["false"] / c["decisions"]
        rules[rule] = {"decisions": c["decisions"], "false": c["false"], "share": round(rate, 3),
                       "over": c["decisions"] >= minimum and rate > share}
    return {"window_days": days, "share_limit": share, "min_decisions": minimum,
            "decisions": len(decs), "false": sum(r["false"] for r in rules.values()),
            "rules": rules, "over": sorted(r for r, v in rules.items() if v["over"])}


def settings() -> dict:
    return harness_config.load()["hooks"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="False blocks of the harness hooks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--days", type=int, default=1)
    ls.add_argument("--rule")
    mk = sub.add_parser("mark")
    mk.add_argument("ids", nargs="*")
    mk.add_argument("--last", action="store_true", help="the most recent decision")
    mk.add_argument("--rule", help="with --last: the most recent decision of this rule")
    mk.add_argument("--reason", default="")
    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int)
    rp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    log_dir = harness_config.HOOK_LOG
    conf = settings()

    if args.cmd == "list":
        marked = marks(log_dir)
        rows = [d for d in decisions(log_dir, args.days) if not args.rule or d.get("rule") == args.rule]
        for d in rows:
            flag = "  false block" if d.get("id") in marked else ""
            print(f"{d.get('ts', '?')}  {d.get('id') or '-':<8}  {d.get('decision'):<5}  "
                  f"{d.get('rule')}  ({d.get('tool')}, {d.get('agent')}){flag}")
        print(f"{len(rows)} decisions")
        return 0

    if args.cmd == "mark":
        ids = list(args.ids)
        if args.last:
            rows = [d for d in decisions(log_dir) if d.get("id")
                    and (not args.rule or d.get("rule") == args.rule)]
            if not rows:
                print("no logged decision to mark")
                return 2
            ids.append(rows[-1]["id"])
        if not ids:
            print("give decision ids or --last")
            return 2
        try:
            recs = mark(log_dir, ids, args.reason)
        except ValueError as err:
            print(err)
            return 2
        for rec in recs:
            print(f"marked {rec['id']} ({rec['rule']}, {rec['decision']}) as a false block")
        return 0

    rep = report(log_dir, args.days or int(conf["window_days"]), float(conf["false_block_share"]),
                 int(conf["false_block_min"]))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for rule, r in rep["rules"].items():
            mark_ = "  OVER" if r["over"] else ""
            print(f"{rule:<18} {r['decisions']:>5} decisions  {r['false']:>3} false  "
                  f"{r['share'] * 100:5.1f}%{mark_}")
        print(f"{rep['decisions']} decisions in {rep['window_days']} days, {rep['false']} marked "
              f"false; limit {rep['share_limit'] * 100:.0f}% from {rep['min_decisions']} decisions")
    return 1 if rep["over"] else 0


if __name__ == "__main__":
    sys.exit(main())
