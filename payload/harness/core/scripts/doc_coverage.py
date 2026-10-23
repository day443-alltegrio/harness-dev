#!/usr/bin/env python3
"""QG8: scenarios of people stay tied to the code (harness/core/docs/design.md, "Documentation").

Scenarios live in one Markdown document, one heading per scenario (SC-01, SC-02...).
The map harness/config/scenarios-map.json ties each scenario to the files that
implement it (paths or globs) and to the tests that prove its promises. Checks:
  map      - every scenario of the document is in the map and back;
  anchors  - every file entry matches a file, every test exists;
  orphans  - a file under "watch" belongs to no scenario (service and shared files
             are listed in the map with a reason);
  tests    - a scenario of people (actor user, admin or both) has a test;
  drift    - the scenario's code or text changed since the last review (fingerprints
             in harness/config/scenarios-lock.json);
  expired  - a deferred decision is past its date or longer than 90 days.
An open decision (harness/config/doc-decisions.json) lifts the tests, drift or orphans
stop for its scenario until its date.

A mismatch is reviewed by the docs-reviewer subagent from the diff; a human decides:
    python3 harness/core/scripts/doc_coverage.py                 # exit 1 and the reasons
    python3 harness/core/scripts/doc_coverage.py --json          # summary for the snapshot
    python3 harness/core/scripts/doc_coverage.py --diff SC-21    # what changed since the review
    python3 harness/core/scripts/doc_coverage.py --accept SC-21 --decision fix_doc
    python3 harness/core/scripts/doc_coverage.py --accept SC-21 --decision defer \\
        --reason "..." --until 2026-11-15 --claim "..."
Decisions: fix_doc - the scenario text now follows the code (the text must change);
fix_code - the code now follows the scenario; none - nothing described changed;
defer - postpone with a reason and a review date at most 90 days ahead.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
MAP = "harness/config/scenarios-map.json"
LOCK = "harness/config/scenarios-lock.json"
DECISIONS = "harness/config/doc-decisions.json"
ACTORS = {"user", "admin", "both", "system"}
PEOPLE = {"user", "admin", "both"}
DECISION_KINDS = {"fix_doc", "fix_code", "none", "defer"}
MAX_DEFER_DAYS = 90


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _norm_code(text: str) -> str:
    """Without blank lines and comment lines: editing a comment is not a review."""
    keep = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith(("#", "//", "/*", "*", "--")):
            keep.append(line.rstrip())
    return "\n".join(keep)


def expand(root: Path, patterns: list[str]) -> list[str]:
    """Repo paths matched by plain paths or globs (sorted, files only)."""
    out: set[str] = set()
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            out |= {p.relative_to(root).as_posix() for p in root.glob(pat) if p.is_file()}
        elif (root / pat).is_file():
            out.add(pat)
    return sorted(out)


def test_exists(root: Path, ref: str) -> bool:
    """"tests/test_x.py::name" or "...::Class.method"; a bare path checks the file."""
    file, _, name = ref.partition("::")
    p = root / file
    if not p.is_file():
        return False
    if not name:
        return True
    text = p.read_text(encoding="utf-8", errors="replace")
    return all(re.search(rf"^\s*(async )?(def|class|function|it|test)\b\W*{re.escape(part)}\b",
                         text, re.M) for part in name.split("."))


def sections(root: Path, doc: str, heading: str) -> dict[str, str]:
    """Scenario id -> its section, up to the next heading of the same or a higher level."""
    rx = re.compile(rf"^(#{{2,4}}) ({heading})\b")
    out: dict[str, str] = {}
    current, level, buf = None, 0, []
    for line in (root / doc).read_text(encoding="utf-8").splitlines():
        h = re.match(r"^(#{1,6}) ", line)
        if h and current and len(h.group(1)) <= level:
            out[current] = "\n".join(buf)
            current = None
        m = rx.match(line)
        if m:
            current, level, buf = m.group(2), len(m.group(1)), [line]
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf)
    return out


def _key(sc: str) -> tuple[int, str]:
    m = re.search(r"\d+", sc)
    return (int(m.group()) if m else 0, sc)


class State:
    def __init__(self, root: Path):
        self.root = root
        self.map = harness_config.read_json(root / MAP, None)
        if self.map is None:
            raise FileNotFoundError(f"no {MAP}")
        self.lock = harness_config.read_json(root / LOCK, {})
        self.decisions = harness_config.read_json(root / DECISIONS, {"open": []}).get("open", [])
        self.scenarios: dict = self.map.get("scenarios", {})
        self.sections = sections(root, self.map["doc"], self.map.get("heading", r"SC-\d+"))

    def files(self, sc: str) -> list[str]:
        return expand(self.root, self.scenarios[sc].get("files", []))

    def fingerprint(self, sc: str) -> dict:
        parts = [f"== {rel}\n{_norm_code((self.root / rel).read_text(encoding='utf-8', errors='replace'))}"
                 for rel in self.files(sc)]
        doc = "\n".join(line.rstrip() for line in self.sections.get(sc, "").splitlines()
                        if line.strip())
        return {"code": _sha("\n".join(parts)), "doc": _sha(doc)}


def _covered(decisions: list, today: str, check: str, sc: str | None = None,
             anchor: str | None = None) -> bool:
    for d in decisions:
        if d.get("check") != check or d.get("until", "") < today:
            continue
        if (sc and d.get("sc") == sc) or (anchor and d.get("anchor") == anchor):
            return True
    return False


def check(st: State, today: str | None = None) -> list[str]:
    today = today or dt.date.today().isoformat()
    problems: list[str] = []
    doc, smap = st.map["doc"], st.scenarios

    for sc in sorted(set(st.sections) - set(smap), key=_key):
        problems.append(f"{sc} is in {doc} but not in the map {MAP}: add its files and tests")
    for sc in sorted(set(smap) - set(st.sections), key=_key):
        problems.append(f"{sc} is in the map but not in {doc}: removed or renamed")

    for sc, entry in sorted(smap.items(), key=lambda kv: _key(kv[0])):
        if entry.get("actor") not in ACTORS:
            problems.append(f"{sc}: actor must be one of {sorted(ACTORS)}")
        for pat in entry.get("files", []):
            if not expand(st.root, [pat]):
                problems.append(f"{sc}: no file matches {pat}")
        for ref in entry.get("tests", []):
            if not test_exists(st.root, ref):
                problems.append(f"{sc}: no test {ref}")
        if (entry.get("actor") in PEOPLE and not entry.get("tests")
                and not _covered(st.decisions, today, "tests", sc=sc)):
            problems.append(f"{sc}: scenario without a test - add a test of its promises or a"
                            " defer decision with a date")

    watched = set(expand(st.root, st.map.get("watch", [])))
    used = {f for sc in smap for f in st.files(sc)}
    exempt = set(expand(st.root, list(st.map.get("service", {})) + st.map.get("shared", [])))
    for rel in sorted(watched - used - exempt):
        if not _covered(st.decisions, today, "orphans", anchor=rel):
            problems.append(f"{rel} belongs to no scenario: describe it in {doc} and the map,"
                            " or list it under service (with a reason) or shared")

    for sc, entry in sorted(smap.items(), key=lambda kv: _key(kv[0])):
        if entry.get("actor") not in PEOPLE or sc not in st.sections:
            continue
        now, was = st.fingerprint(sc), st.lock.get(sc)
        if was is None:
            what = "not reviewed yet"
        elif was["code"] != now["code"] and was["doc"] != now["doc"]:
            what = "both the code and the scenario text changed"
        elif was["code"] != now["code"]:
            what = "the code changed, the scenario text did not"
        elif was["doc"] != now["doc"]:
            what = "the scenario text changed, the code did not"
        else:
            continue
        if _covered(st.decisions, today, "drift", sc=sc):
            continue
        names = ", ".join(Path(f).name for f in st.files(sc)) or "-"
        problems.append(f"{sc}: {what} since the review ({names}). Review: doc_coverage.py"
                        f" --diff {sc}, the docs-reviewer subagent, a human decides:"
                        f" doc_coverage.py --accept {sc} --decision fix_doc|fix_code|none|defer")

    for d in st.decisions:
        who = d.get("sc") or d.get("anchor")
        if d.get("until", "") < today:
            problems.append(f"defer decision for {who} has expired ({d.get('until')}):"
                            f" {d.get('claim', '')}")
            continue
        # The limit holds for hand edits of the journal too, not only for --accept.
        try:
            span = (dt.date.fromisoformat(d["until"]) - dt.date.fromisoformat(d["at"])).days
        except (KeyError, ValueError):
            problems.append(f"decision for {who} has no at/until dates in {DECISIONS}")
            continue
        if span > MAX_DEFER_DAYS:
            problems.append(f"decision for {who} is deferred for {span} days, over {MAX_DEFER_DAYS}")
    return problems


def summary(st: State, today: str | None = None) -> dict:
    """Numbers and names only, for the gate table and the snapshot."""
    people = [sc for sc, e in st.scenarios.items() if e.get("actor") in PEOPLE]
    synced = 0
    for sc in people:
        was = st.lock.get(sc)
        if was and sc in st.sections:
            now = st.fingerprint(sc)
            synced += was["code"] == now["code"] and was["doc"] == now["doc"]
    return {"problems": check(st, today), "people": len(people), "in_sync": synced,
            "with_tests": sum(1 for sc in people if st.scenarios[sc].get("tests")),
            "decisions_open": len(st.decisions),
            "decisions": [{k: d.get(k) for k in ("sc", "anchor", "check", "claim", "until")}
                          for d in st.decisions]}


def diff(st: State, scs: list[str]) -> str:
    out = []
    for sc in scs:
        entry = st.scenarios.get(sc)
        if entry is None:
            out.append(f"{sc}: not in the map")
            continue
        was = st.lock.get(sc, {})
        base = was.get("commit")
        out.append(f"### {sc} ({entry.get('actor')}), last review: {was.get('at', 'never')}"
                   f" {base or ''}")
        out.append(st.sections.get(sc, "(no such section in the document)"))
        files = st.files(sc)
        if base and files:
            r = subprocess.run(["git", "diff", base, "--", *files, st.map["doc"]],
                               cwd=st.root, capture_output=True, text=True)
            out.append(r.stdout.strip() or "(no changes in the scenario files)")
        else:
            out.append("scenario files: " + (", ".join(files) or "-"))
    return "\n\n".join(out)


def accept(st: State, scs: list[str], decision: str, reason: str = "", until: str = "",
           claim: str = "", today: str | None = None) -> list[str]:
    """Record a decision: new fingerprints in the lock, a deferral in the journal.
    Returns the errors (empty means recorded)."""
    today = today or dt.date.today().isoformat()
    if decision not in DECISION_KINDS:
        return [f"decision must be one of {sorted(DECISION_KINDS)}"]
    if scs == ["all"]:
        scs = sorted((sc for sc, e in st.scenarios.items() if e.get("actor") in PEOPLE), key=_key)
    errors = [f"{sc}: not in the map or the document" for sc in scs
              if sc not in st.scenarios or sc not in st.sections]
    if decision == "defer":
        if not reason or not claim:
            errors.append("defer needs --reason and --claim")
        try:
            days = (dt.date.fromisoformat(until) - dt.date.fromisoformat(today)).days
            if not 0 < days <= MAX_DEFER_DAYS:
                errors.append(f"--until must be within {MAX_DEFER_DAYS} days from today")
        except ValueError:
            errors.append("defer needs --until YYYY-MM-DD")
    if errors:
        return errors
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=st.root,
                          capture_output=True, text=True).stdout.strip()
    for sc in scs:
        now, was = st.fingerprint(sc), st.lock.get(sc)
        if decision == "fix_doc" and was and was["doc"] == now["doc"]:
            errors.append(f"{sc}: fix_doc, but the scenario text has not changed: update"
                          f" {st.map['doc']} first")
            continue
        st.lock[sc] = {**now, "commit": head, "at": today, "decision": decision}
        if decision == "defer":
            st.decisions.append({"sc": sc, "check": "drift", "claim": claim,
                                 "reason": reason, "until": until, "at": today})
    _write(st.root, LOCK, dict(sorted(st.lock.items(), key=lambda kv: _key(kv[0]))))
    if decision == "defer":
        _write(st.root, DECISIONS,
               {**harness_config.read_json(st.root / DECISIONS, {}), "open": st.decisions})
    return errors


def _write(root: Path, rel: str, data) -> None:
    (root / rel).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--diff", nargs="+", metavar="SC")
    ap.add_argument("--accept", nargs="+", metavar="SC")
    ap.add_argument("--decision", choices=sorted(DECISION_KINDS))
    ap.add_argument("--reason", default="")
    ap.add_argument("--until", default="")
    ap.add_argument("--claim", default="")
    args = ap.parse_args(argv)
    st = State(ROOT)
    if args.diff:
        print(diff(st, args.diff))
        return 0
    if args.accept:
        if not args.decision:
            print("--accept needs --decision", file=sys.stderr)
            return 2
        errors = accept(st, args.accept, args.decision, args.reason, args.until, args.claim)
        for e in errors:
            print(f"doc_coverage: {e}", file=sys.stderr)
        return 1 if errors else 0
    if args.json:
        print(json.dumps(summary(st), ensure_ascii=False))
        return 0
    problems = check(st)
    for p in problems:
        print(f"doc_coverage: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
