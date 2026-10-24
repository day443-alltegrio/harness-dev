#!/usr/bin/env python3
"""Regression cases: closed tickets replayed on every deploy and nightly (pattern A8 in
harness/core/docs/failure-patterns.md).

A ticket closed with a result a human confirmed becomes a case: a command and the
result it must give. Replayed on every deploy and nightly, the cases keep a fixed
behaviour from breaking again unnoticed: they are the durable record of behaviour a
person checked.

One JSON file per case, directly in regressions.dir of harness.json (default
harness/project/regressions/), named after its id: R-0001-age-in-months.json. Keys
starting with "_" are comments.

    {"id": "R-0001", "ticket": "TICKET-123",
     "title": "age under one year counts as 0 full years",
     "confirmed": {"by": "QA lead", "date": "2026-10-22",
                   "how": "re-asked on the deployed code"},
     "when": "before", "cmd": "python3 -m app.cli count --age-max 0",
     "cwd": "services/api", "timeout_s": 60,
     "expect": {"exit": 0, "number": 42}}

Required: id (unique), ticket, confirmed.by, confirmed.date (YYYY-MM-DD), cmd, expect.
A case without a human confirmation is not a regression case. cwd is relative to the
root; timeout_s defaults to regressions.timeout_s.

expect, every rule must hold (and there is at least one besides a plain exit 0):
  exit          the exit code, default 0;
  number        N, {"min": a, "max": b} or {"value": N, "tolerance": t}: the last
                non-empty stdout line, or the JSON stdout field number_key (a dotted
                path, list items by index: "items.0.count");
  json          {"dotted.path": expected value} on JSON stdout;
  stdout_has    texts that must all appear in stdout;
  stdout_lacks  texts that must not appear in stdout.

when:
  before  needs only the code (default): the deploy check replays it on the new code
          before it replaces the running code, and run.sh replays it on every run;
  after   needs the running service: replayed right after the swap and nightly.

Privacy: the output of a command may hold personal data, so it is never printed or
stored. stdout is only compared, stderr is discarded. A detail names exit codes,
numbers, JSON paths and the position of a text in the case ("expected text #2
missing"), never the text.

    python3 harness/core/scripts/regressions.py [--when before|after|all] [--root DIR] [--json]

--root is where the cases are read and the commands run (the deploy check passes the
staged code). Exit code: 0 - every case passed, or there is none for this "when" (a new
project has none yet; the gate table shows that as unknown, not as a pass); 1 - a case
failed or could not run; 2 - a malformed case file, nothing ran.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import math
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
WHEN = ("before", "after")
KEYS = {"id", "ticket", "title", "confirmed", "when", "cmd", "cwd", "timeout_s", "expect"}
RULES = {"exit", "number", "number_key", "json", "stdout_has", "stdout_lacks"}
CHECKS = ("number", "json", "stdout_has", "stdout_lacks")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
INTEGER = re.compile(r"[+-]?[0-9]+")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
LABEL = {"pass": "pass", "fail": "FAIL", "error": "ERROR"}
_MISSING = object()


class CaseError(ValueError):
    """Malformed case files; the message lists every problem, one per line."""


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def _num(v) -> bool:
    """A finite JSON number; true and false are not numbers here."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return isinstance(v, int) or math.isfinite(v)


def _text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _date(v) -> bool:
    if not (isinstance(v, str) and DATE.fullmatch(v)):
        return False
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _no_comments(d: dict) -> dict:
    return {k: v for k, v in d.items() if not str(k).startswith("_")}


def _clean(raw: dict) -> dict:
    """The case without comment keys, also inside confirmed, expect and the number rule.
    The paths of expect.json point into the output of the command and stay as they are."""
    case = _no_comments(raw)
    for key in ("confirmed", "expect"):
        if isinstance(case.get(key), dict):
            case[key] = _no_comments(case[key])
    expect = case.get("expect")
    if isinstance(expect, dict) and isinstance(expect.get("number"), dict):
        expect["number"] = _no_comments(expect["number"])
    return case


def _number_rule(rule) -> bool:
    if _num(rule):
        return True
    if not isinstance(rule, dict) or not rule or not all(_num(v) for v in rule.values()):
        return False
    if set(rule) <= {"min", "max"}:
        return rule.get("min", -math.inf) <= rule.get("max", math.inf)
    return "value" in rule and set(rule) <= {"value", "tolerance"} and rule.get("tolerance", 0) >= 0


def expect_problems(expect) -> list[str]:
    """What is wrong with the expect object of a case. An unknown rule is an error, not
    skipped: a typo would silently drop a check."""
    if not isinstance(expect, dict):
        return ["expect: an object of rules"]
    out = []
    unknown = sorted(set(expect) - RULES)
    if unknown:
        out.append("expect: unknown rules " + ", ".join(unknown))
    code = expect.get("exit", 0)
    if isinstance(code, bool) or not isinstance(code, int):
        out.append("expect.exit: an integer exit code")
    if "number" in expect and not _number_rule(expect["number"]):
        out.append('expect.number: N, {"min": a, "max": b} or {"value": N, "tolerance": t}')
    if "number_key" in expect and not ("number" in expect and _text(expect["number_key"])):
        out.append("expect.number_key: a dotted path of a JSON field, next to expect.number")
    if "json" in expect:
        paths = expect["json"]
        if not (isinstance(paths, dict) and paths and all(_text(k) for k in paths)):
            out.append('expect.json: {"dotted.path": expected value}, at least one')
    for key in ("stdout_has", "stdout_lacks"):
        if key in expect:
            texts = expect[key]
            if not (isinstance(texts, list) and texts and all(_text(t) for t in texts)):
                out.append(f"expect.{key}: a list of non-empty texts")
    # A command that merely exits 0 proves nothing about the confirmed result (B10).
    if not any(k in expect for k in CHECKS) and code == 0:
        out.append("expect: nothing to check: add number, json, stdout_has or stdout_lacks"
                   " (an exit code alone counts only when it is not 0)")
    return out


def _confirmed_problems(confirmed) -> list[str]:
    if confirmed is None:
        return ["confirmed missing: a case without a human confirmation is not a"
                " regression case"]
    if not isinstance(confirmed, dict):
        return ['confirmed: {"by": "a role or a team member", "date": "YYYY-MM-DD",'
                ' "how": "how the result was checked"}']
    out = []
    if not _text(confirmed.get("by")):
        out.append("confirmed.by missing: who confirmed the result, a role or a team member"
                   " (a case without a human confirmation is not a regression case)")
    if not _date(confirmed.get("date")):
        out.append("confirmed.date: the day the result was confirmed, YYYY-MM-DD")
    return out


def case_problems(raw) -> list[str]:
    """What is wrong with one case; empty for a valid case."""
    if not isinstance(raw, dict):
        return ["a case is a JSON object"]
    case = _clean(raw)
    out = []
    unknown = sorted(set(case) - KEYS)
    if unknown:
        out.append("unknown keys " + ", ".join(unknown) + ' (comments start with "_")')
    cid = case.get("id")
    if not _text(cid) or any(ch.isspace() for ch in cid):
        out.append("id: a non-empty text without spaces, e.g. R-0001")
    ticket = case.get("ticket")
    if not (_text(ticket) or (isinstance(ticket, int) and not isinstance(ticket, bool))):
        out.append("ticket: the closed ticket the case comes from")
    out += _confirmed_problems(case.get("confirmed"))
    if not isinstance(case.get("title", ""), str):
        out.append("title: a text")
    if case.get("when", "before") not in WHEN:
        out.append(f"when: before or after, not {json.dumps(case['when'])}")
    if not _text(case.get("cmd")):
        out.append("cmd: the command to run")
    if "cwd" in case:
        cwd = case["cwd"]
        if not _text(cwd) or Path(cwd).is_absolute() or ".." in Path(cwd).parts:
            out.append("cwd: a folder relative to the root, without ..")
    if "timeout_s" in case and not (_num(case["timeout_s"]) and case["timeout_s"] > 0):
        out.append("timeout_s: a positive number of seconds")
    if "expect" in case:
        out += expect_problems(case["expect"])
    else:
        out.append("expect missing: the result the command must give")
    return out


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def load_cases(root: Path = ROOT) -> list[dict]:
    """The cases of the project in file name order: checked, without comment keys, with
    "when" filled in and "file" (the path from the root) added. Raises CaseError (a
    ValueError) that lists every problem of every malformed file."""
    folder = root / harness_config.load(root)["regressions"]["dir"]
    cases: list[dict] = []
    problems: list[str] = []
    seen: dict[str, str] = {}
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        if not path.is_file():
            continue
        rel = _rel(path, root)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            problems.append(f"{rel}: not valid JSON ({err.msg}, line {err.lineno})")
            continue
        except (OSError, UnicodeDecodeError) as err:
            problems.append(f"{rel}: cannot be read ({type(err).__name__})")
            continue
        found = case_problems(raw)
        if found:
            problems += [f"{rel}: {p}" for p in found]
            continue
        case = _clean(raw)
        if case["id"] in seen:
            problems.append(f"{rel}: duplicate id {case['id']}, also in {seen[case['id']]}")
            continue
        seen[case["id"]] = rel
        cases.append({**case, "ticket": str(case["ticket"]),
                      "when": case.get("when", "before"), "file": rel})
    if problems:
        raise CaseError("\n".join(problems))
    return cases


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def _stop(proc: subprocess.Popen) -> None:
    """Kill the command together with its children: it leads its own process group."""
    if hasattr(os, "killpg"):
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()
    proc.wait()


def execute(cmd: str, cwd: Path, timeout: float,
            env: dict | None = None) -> tuple[int | None, str]:
    """(exit code, stdout) of a shell command, or (None, "") after a timeout. stdin is
    empty, so nothing waits for input; stderr goes nowhere: nothing checks it and it
    may hold personal data."""
    with subprocess.Popen(cmd, shell=True, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          start_new_session=True) as proc:
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop(proc)  # the output read so far is dropped with the exception
            return None, ""
    return proc.returncode, out.decode("utf-8", "replace")


def _parse(text: str):
    """A number written as text ("42", "-3.5", "1e3"), or None."""
    if not NUMBER.fullmatch(text):
        return None
    try:
        value = int(text) if INTEGER.fullmatch(text) else float(text)
    except ValueError:  # beyond the digit limit of int()
        return None
    return value if _num(value) else None


def _get(doc, path: str):
    """The value at a dotted path ("total.count", list items by index "items.0.n"),
    or _MISSING."""
    for part in path.split("."):
        if isinstance(doc, dict) and part in doc:
            doc = doc[part]
        elif (isinstance(doc, list) and INTEGER.fullmatch(part)
              and -len(doc) <= int(part) < len(doc)):
            doc = doc[int(part)]
        else:
            return _MISSING
    return doc


def _same(a, b) -> bool:
    """JSON equality: 1 equals 1.0, but true is not 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _show(value) -> str:
    """A value safe to print: numbers, true, false and null as they are; a text, a list
    or an object only by its kind, since it may come from the output."""
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return "a text"
    if isinstance(value, list):
        return f"a list of {len(value)}"
    return "an object"


def _kind(value) -> str:
    if isinstance(value, str):
        return "text"
    return "list" if isinstance(value, list) else "object"


def _texts(positions: list[int]) -> str:
    """Texts of the case named by their position: "text #2", "texts #1, #3"."""
    marks = ", ".join(f"#{i}" for i in positions)
    return f"text {marks}" if len(positions) == 1 else f"texts {marks}"


def read_number(stdout: str, doc, key: str | None) -> tuple[float | None, str]:
    """(the number, "") or (None, why there is none)."""
    if key:
        value = _get(doc, key)
        if value is _MISSING:
            return None, f"no field {key} in the JSON"
        if isinstance(value, str):
            value = _parse(value.strip())
        if not _num(value):
            return None, f"{key} is not a number"
        return value, ""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        return None, "no output, expected a number"
    value = _parse(lines[-1])
    if value is None:
        return None, "not a number"
    return value, ""


def number_mismatch(rule, got) -> list[str]:
    if _num(rule):
        return [] if got == rule else [f"expected number {_show(rule)}, got {_show(got)}"]
    if "value" in rule:
        tolerance = rule.get("tolerance", 0)
        if abs(got - rule["value"]) <= tolerance:
            return []
        return [f"expected number {_show(rule['value'])} +- {_show(tolerance)},"
                f" got {_show(got)}"]
    lo, hi = rule.get("min"), rule.get("max")
    if (lo is None or got >= lo) and (hi is None or got <= hi):
        return []
    if lo is not None and hi is not None:
        want = f"in {_show(lo)}..{_show(hi)}"
    else:
        want = f"at least {_show(lo)}" if lo is not None else f"at most {_show(hi)}"
    return [f"expected number {want}, got {_show(got)}"]


def json_mismatch(paths: dict, doc) -> list[str]:
    out = []
    for path, want in paths.items():
        got = _get(doc, path)
        if got is _MISSING:
            out.append(f"json {path}: no such field")
        elif not _same(got, want):
            a, b = _show(want), _show(got)
            out.append(f"json {path}: not the expected {_kind(want)}" if a == b
                       else f"json {path}: expected {a}, got {b}")
    return out


def judge(expect: dict, code: int, stdout: str) -> list[str]:
    """The rules of expect that do not hold, as details safe to print: exit codes,
    numbers, JSON paths and positions of texts, never the output itself."""
    out = []
    want = expect.get("exit", 0)
    if code != want:
        out.append(f"exit {code}, expected {want}")
    doc = _MISSING
    if "number_key" in expect or "json" in expect:
        try:
            doc = json.loads(stdout)
        except ValueError:
            out.append("stdout is not JSON" if stdout.strip() else "no output, expected JSON")
    if "number" in expect and ("number_key" not in expect or doc is not _MISSING):
        got, problem = read_number(stdout, doc, expect.get("number_key"))
        if problem:
            out.append(problem)
        else:
            out += number_mismatch(expect["number"], got)
    if "json" in expect and doc is not _MISSING:
        out += json_mismatch(expect["json"], doc)
    missing = [i for i, t in enumerate(expect.get("stdout_has", ()), 1) if t not in stdout]
    if missing:
        out.append(f"expected {_texts(missing)} missing")
    present = [i for i, t in enumerate(expect.get("stdout_lacks", ()), 1) if t in stdout]
    if present:
        out.append(f"unwanted {_texts(present)} present")
    return out


def run_case(root: Path, case: dict, timeout_s: float, env: dict | None = None) -> dict:
    """Replay one checked case: {"id", "ticket", "state", "detail"}. "fail": the result
    differs or did not come in time; "error": the case could not start."""
    head = {"id": case["id"], "ticket": str(case["ticket"])}
    cwd = root / case["cwd"] if case.get("cwd") else root
    if not cwd.is_dir():
        return {**head, "state": "error", "detail": f"no folder {case.get('cwd') or root}"}
    timeout = float(case.get("timeout_s") or timeout_s)
    try:
        code, stdout = execute(case["cmd"], cwd, timeout, env)
    except OSError as err:
        return {**head, "state": "error",
                "detail": f"could not start: {err.strerror or type(err).__name__}"}
    if code is None:
        return {**head, "state": "fail", "detail": f"timeout after {timeout:g} s"}
    problems = judge(case["expect"], code, stdout)
    return {**head, "state": "fail" if problems else "pass", "detail": "; ".join(problems)}


def run(root: Path = ROOT, when: str = "before", *, env: dict | None = None) -> dict:
    """Replay the cases of one "when" ("before", "after" or "all") in root. env is the
    environment of the commands (default: the one of this process; the deploy check
    passes its own, without the variables of live systems). Raises CaseError (a
    ValueError) on a malformed case file: then nothing runs."""
    if when not in (*WHEN, "all"):
        raise ValueError(f"when: before, after or all, not {when!r}")
    picked = [c for c in load_cases(root) if when in ("all", c["when"])]
    timeout = float(harness_config.load(root)["regressions"]["timeout_s"])
    results = [run_case(root, c, timeout, env) for c in picked]
    return {"when": when, "cases": len(results),
            "passed": sum(r["state"] == "pass" for r in results),
            "failed": [r["id"] for r in results if r["state"] == "fail"],
            "errors": [r["id"] for r in results if r["state"] == "error"],
            "results": results}


def summary_line(out: dict) -> str:
    line = f"regressions (when={out['when']}): {out['passed']} of {out['cases']} pass"
    if out["failed"]:
        line += "; failed: " + ", ".join(out["failed"])
    if out["errors"]:
        line += "; errors: " + ", ".join(out["errors"])
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay the regression cases of closed tickets")
    ap.add_argument("--when", choices=("before", "after", "all"), default="before")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="where the cases are read and the commands run (default: this project)")
    ap.add_argument("--json", action="store_true", help="one JSON line instead of the table")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        ap.error(f"no folder {root}")
    try:
        out = run(root, args.when)
    except CaseError as err:
        problems = str(err).splitlines()
        if args.json:
            print(json.dumps({"when": args.when, "cases": 0, "passed": 0, "failed": [],
                              "errors": [], "results": [], "malformed": problems},
                             ensure_ascii=False))
        else:
            for p in problems:
                print(f"malformed  {p}")
            print(f"nothing ran: {len(problems)} problems in the case files")
        return 2
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    elif not out["cases"]:
        print(f"no regression cases (when={args.when})")
    else:
        for r in out["results"]:
            tail = f": {r['detail']}" if r["detail"] else ""
            print(f"{LABEL[r['state']]:<5} {r['id']}  {r['ticket']}{tail}")
        print(summary_line(out))
    return 1 if out["failed"] or out["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
