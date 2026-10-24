#!/usr/bin/env python3
"""QG6 data invariants: project counters compared with fixed rules.

Data failures do not crash. They are quiet wrong numbers found late by people (B1..B11
in harness/core/docs/failure-patterns.md): a masking rule that mostly masks the wrong
words, derived data built from an old source, a search that silently returns nothing,
a load that lost rows. A project declares counters as shell commands in
harness/config/data-checks.json (data_checks.file in harness.json); this script runs
each one and compares its number with a fixed rule, so damaged data is caught by a
check, not by a person.

A check (keys starting with "_" are comments; any other unknown key is an error):

    {"id": "facts-version", "pattern": "B4", "title": "facts follow the source",
     "cmd": "psql -tAc \"select json_build_object('derived', ..., 'source', ...)\"",
     "expect": {"equal": ["derived", "source"]}}

id, cmd and expect are required and ids are unique; pattern is a failure pattern id
(B4, or a project pattern such as P2). "key" names the field of a JSON output that a
scalar rule reads; "timeout_s" overrides data_checks.timeout_s.

The command runs with sh in the project root, with empty stdin and in its own process
group (a timeout stops everything it started). The last non-empty line of its stdout
is the result: a plain number, or a JSON object of numbers on one line (booleans are
not numbers). stderr is captured and dropped.

Rules, exactly one per check in "expect":
  eq: N                         the value equals N (known values in the output: 0);
  min: N, max: N                at least N, at most N;
  range: [lo, hi]               lo <= value <= hi (the control number of a golden set);
  equal: [a, b]                 fields a and b of the JSON output are equal (derived
                                version and source version, rows in and rows out);
  ratio_max: [num, den, share]  num / den <= share; den 0 is an error;
  drop_max: share               0 < share < 1: fails below baseline * (1 - share).
                                The baseline is the newest value of the check that
                                passed or that a person accepted, never a failing
                                one: a sustained drop keeps failing until someone
                                accepts the new level with --accept and a reason.
                                With no baseline yet the check passes and records one.
eq, min, max, range and drop_max read the field "key" of a JSON output. Shares are
compared exactly as written: 0.7 is seven tenths, not the float next to it.

Empty is a failure (B10): a non-zero exit, a timeout, no output, a result that is not
a number and a missing key are state "error", never "pass"; a file without checks is
not a pass either.

Privacy: results hold numbers and names from the config only. What a command prints
may hold personal data, so none of it reaches the screen, the report or the history:
an error says "exit 2", "timeout after 5 s", "no output", "not a number" or
"missing key 'rows'", never what was printed. Of a JSON output only the fields the
rule names are kept.

Evidence, relative to the project root (harness/.state/ is outside git):
  harness/.state/data-checks.json     the report of the last recorded run;
  harness/.state/data-history.jsonl   one line per check that produced a number:
                                      {"at", "id", "value" or "values", "state"};
                                      state "accepted" comes with the "reason" of a
                                      person. Lines without a state (written by an
                                      older version) count as passing. The newest
                                      data_checks.history_keep lines are kept, and the
                                      newest baseline of each check is never trimmed.

    python3 harness/core/scripts/data_checks.py                # all checks, recorded
    python3 harness/core/scripts/data_checks.py --only a,b     # these checks only
    python3 harness/core/scripts/data_checks.py --json         # the report as JSON
    python3 harness/core/scripts/data_checks.py --no-record    # write nothing
    python3 harness/core/scripts/data_checks.py --accept a,b --reason "..."
        # a person takes the current values of drop_max checks a, b as new baselines

Exit code: 0 every check passes; 1 a check failed or could not run, or there are no
checks; 2 a config error or an unknown id. With --accept: 0 accepted; 1 a check
errors, so nothing is accepted; 2 no reason, an unknown id or a check without
drop_max.
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
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
# Evidence paths, relative to the root a function is given (tests use temporary roots).
REPORT = "harness/.state/data-checks.json"
HISTORY = "harness/.state/data-history.jsonl"
RULES = ("eq", "min", "max", "range", "equal", "ratio_max", "drop_max")
PAIRED = ("equal", "ratio_max")  # rules that name their own fields of a JSON output
FIELDS = {"id", "pattern", "title", "cmd", "expect", "key", "timeout_s"}
ID = re.compile(r"[\w.-]+")
PATTERN = re.compile(r"(?:[AB]|P)\d+")
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
INTEGER = re.compile(r"[-+]?\d+")
LABEL = {"pass": "pass", "fail": "FAIL", "error": "error"}
# History states a drop_max baseline may come from; None: a line from before states.
BASELINE = (None, "pass", "accepted")


class Refused(Exception):
    """accept() records nothing: a check errors, so it has no number to keep."""


def is_number(v: object) -> bool:
    """An int or a finite float; booleans are not numbers."""
    if isinstance(v, bool):
        return False
    return isinstance(v, int) or (isinstance(v, float) and math.isfinite(v))


def fmt(n: int | float) -> str:
    """A number for a detail line: 7, 0.03, 1.5e+16."""
    if isinstance(n, float):
        return str(int(n)) if n.is_integer() and abs(n) < 1e15 else f"{n:.6g}"
    return str(n)


def exact(n: int | float) -> Fraction:
    """The number as written: 0.7 is 7/10, so a value exactly at a limit never fails
    on float rounding."""
    return Fraction(repr(n)) if isinstance(n, float) else Fraction(n)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def settings(root: Path = ROOT) -> dict:
    """data_checks of harness.json over the defaults; ValueError when unusable."""
    conf = harness_config.load(root)["data_checks"]
    where = "harness/config/harness.json"
    if not isinstance(conf, dict):
        raise ValueError(f"{where}: data_checks must be an object")
    problems = []
    if not isinstance(conf.get("file"), str) or not conf["file"].strip():
        problems.append("data_checks.file must be a path")
    if not is_number(conf.get("timeout_s")) or conf["timeout_s"] <= 0:
        problems.append("data_checks.timeout_s must be a positive number")
    keep = conf.get("history_keep")
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
        problems.append("data_checks.history_keep must be a whole number of at least 1")
    if problems:
        raise ValueError(f"{where}: " + "; ".join(problems))
    return conf


def _rule_problem(rule: str, arg: object) -> str | None:
    """Why the argument of a rule is unusable, or None."""
    def names(items: list) -> bool:
        return all(isinstance(x, str) and x for x in items) and items[0] != items[1]

    if rule in ("eq", "min", "max"):
        return None if is_number(arg) else f"{rule} needs a number"
    if rule == "range":
        if isinstance(arg, list) and len(arg) == 2 and all(map(is_number, arg)) \
                and arg[0] <= arg[1]:
            return None
        return "range needs [lo, hi] with lo <= hi"
    if rule == "equal":
        if isinstance(arg, list) and len(arg) == 2 and names(arg):
            return None
        return "equal needs two different field names [a, b]"
    if rule == "ratio_max":
        if isinstance(arg, list) and len(arg) == 3 and names(arg[:2]) \
                and is_number(arg[2]) and arg[2] >= 0:
            return None
        return "ratio_max needs [num_key, den_key, share] with two different fields, share >= 0"
    if is_number(arg) and 0 < arg < 1:
        return None
    return "drop_max needs a share between 0 and 1, e.g. 0.2"


def _check_problems(c: dict) -> list[str]:
    """Problems of one check, comments already removed."""
    out = [f"unknown key {k!r} (comments start with \"_\")" for k in sorted(set(c) - FIELDS)]
    if "id" not in c:
        out.append('missing "id"')
    elif not isinstance(c["id"], str) or not ID.fullmatch(c["id"]):
        out.append('"id" must be letters, digits, "_", "." or "-"')
    if "pattern" in c and not (isinstance(c["pattern"], str) and PATTERN.fullmatch(c["pattern"])):
        out.append('"pattern" must be a failure pattern id such as "B4" or "P2"')
    if "title" in c and not isinstance(c["title"], str):
        out.append('"title" must be a string')
    if "cmd" not in c:
        out.append('missing "cmd"')
    elif not isinstance(c["cmd"], str) or not c["cmd"].strip():
        out.append('"cmd" must be a shell command')
    if "timeout_s" in c and (not is_number(c["timeout_s"]) or c["timeout_s"] <= 0):
        out.append('"timeout_s" must be a positive number')
    rule = None
    if "expect" not in c:
        out.append('missing "expect"')
    elif not isinstance(c["expect"], dict):
        out.append('"expect" must be an object with one rule')
    else:
        expect = {k: v for k, v in c["expect"].items() if not k.startswith("_")}
        unknown = [k for k in expect if k not in RULES]
        if unknown:
            out.append(f"unknown rule {unknown[0]!r} (known: {', '.join(RULES)})")
        elif len(expect) != 1:
            found = f"{len(expect)} rules ({', '.join(expect)})" if expect else "no rule"
            out.append(f"expect has {found}: use exactly one")
        else:
            rule, arg = next(iter(expect.items()))
            problem = _rule_problem(rule, arg)
            if problem:
                out.append(problem)
    if "key" in c:
        if not isinstance(c["key"], str) or not c["key"]:
            out.append('"key" must be a field name')
        elif rule in PAIRED:
            out.append(f'"key" is not used by {rule}: the rule names its own fields')
    return out


def load_checks(root: Path = ROOT) -> list[dict]:
    """The checks of the project file with comments removed and defaults filled in:
    {"id", "pattern", "title", "cmd", "expect": {rule: argument}, "key", "timeout_s"}.
    A config error raises ValueError naming every problem found."""
    rel = settings(root)["file"]
    path = root / rel
    if not path.is_file():
        raise ValueError(f"{rel} not found (harness.py creates it from"
                         " harness/core/templates/config/data-checks.json)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        raise ValueError(f"{rel}: not valid JSON ({err})") from None
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise ValueError(f'{rel}: expected an object with a "checks" list')
    problems = [f'unknown top-level key {k!r}: checks go into "checks", comments start with "_"'
                for k in data if not k.startswith("_") and k != "checks"]
    checks, seen = [], set()
    for n, raw in enumerate(data["checks"], 1):
        if not isinstance(raw, dict):
            problems.append(f"check {n}: not an object")
            continue
        c = {k: v for k, v in raw.items() if not k.startswith("_")}
        cid = c.get("id")
        name = f"check {cid!r}" if isinstance(cid, str) and cid else f"check {n}"
        if isinstance(cid, str):
            if cid in seen:
                problems.append(f"duplicate id {cid!r}")
            seen.add(cid)
        found = _check_problems(c)
        if found:
            problems += [f"{name}: {p}" for p in found]
            continue
        expect = {k: v for k, v in c["expect"].items() if not k.startswith("_")}
        checks.append({"id": cid, "pattern": c.get("pattern", ""), "title": c.get("title", ""),
                       "cmd": c["cmd"], "expect": expect, "key": c.get("key"),
                       "timeout_s": c.get("timeout_s")})
    if problems:
        raise ValueError(f"{rel}: " + "; ".join(problems))
    return checks


# ---------------------------------------------------------------------------
# One check
# ---------------------------------------------------------------------------

def execute(cmd: str, root: Path, timeout: float) -> tuple[str, str]:
    """(stdout, "") or ("", error). The command gets its own process group, so a timeout
    stops everything it started; stderr is read and dropped, never shown."""
    proc = subprocess.Popen(cmd, shell=True, cwd=str(root), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            proc.kill()
        # A process that left the group may still hold the pipes: never read to the end.
        for pipe in (proc.stdout, proc.stderr):
            pipe.close()
        proc.wait()
        return "", f"timeout after {fmt(timeout)} s"
    if proc.returncode < 0:
        return "", f"killed by signal {-proc.returncode}"
    if proc.returncode:
        return "", f"exit {proc.returncode}"
    return out.decode("utf-8", "replace"), ""


def _no_constant(name: str) -> None:
    raise ValueError("NaN and Infinity are not numbers")


def parse(stdout: str) -> tuple[int | float | dict | None, str]:
    """The last non-empty line as a number or a JSON object of numbers, or (None, error).
    The error never quotes the line: it may hold personal data."""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        return None, "no output"
    last = lines[-1]
    if NUMBER.fullmatch(last):
        try:
            value = int(last) if INTEGER.fullmatch(last) else float(last)
        except ValueError:  # more digits than int() converts
            return None, "not a number"
        return (value, "") if is_number(value) else (None, "not a number")
    if last.startswith("{"):
        try:
            obj = json.loads(last, parse_constant=_no_constant)
        except ValueError:
            return None, "not valid JSON"
        if all(is_number(v) for v in obj.values()):
            return obj, ""
        return None, "JSON value not a number"
    return None, "not a number"


def _state(ok: bool) -> str:
    return "pass" if ok else "fail"


def _judge_paired(rule: str, arg: list, output: int | float | dict) -> tuple:
    a_key, b_key = arg[0], arg[1]
    if not isinstance(output, dict):
        return "error", None, None, "not a JSON object"
    missing = [k for k in (a_key, b_key) if k not in output]
    if missing:
        word = "key" if len(missing) == 1 else "keys"
        return "error", None, None, f"missing {word} " + ", ".join(map(repr, missing))
    a, b = output[a_key], output[b_key]
    values = {a_key: a, b_key: b}
    if rule == "equal":
        ok = a == b
        return _state(ok), None, values, f"{a_key} {fmt(a)} {'=' if ok else '!='} {b_key} {fmt(b)}"
    share = arg[2]
    if b == 0:
        return "error", None, values, f"{b_key} is 0: no ratio"
    ratio = exact(a) / exact(b)
    ok = ratio <= exact(share)
    return (_state(ok), float(ratio), values,
            f"{a_key} {fmt(a)} / {b_key} {fmt(b)} = {fmt(float(ratio))}"
            f" {'<=' if ok else '>'} {fmt(share)}")


def judge(check: dict, output: int | float | dict, previous: int | float | None = None,
          record: bool = True) -> tuple[str, int | float | None, dict | None, str]:
    """(state, value, values, detail) of a check for its parsed output. previous is the
    baseline of drop_max (the newest passing or accepted value); record says whether
    this run is recorded, so a first value becomes the baseline. Only the fields the
    rule names reach "values"."""
    rule, arg = next(iter(check["expect"].items()))
    if rule in PAIRED:
        return _judge_paired(rule, arg, output)
    key = check.get("key")
    if isinstance(output, dict):
        if key is None:
            return "error", None, None, 'JSON output without "key"'
        if key not in output:
            return "error", None, None, f"missing key {key!r}"
        value = output[key]
    elif key is not None:
        return "error", None, None, f"not a JSON object (key {key!r})"
    else:
        value = output
    v = (f"{key} " if key else "") + fmt(value)
    if rule == "eq":
        ok = value == arg
        return _state(ok), value, None, f"{v} {'=' if ok else '!='} {fmt(arg)}"
    if rule == "min":
        ok = value >= arg
        return _state(ok), value, None, f"{v} {'>=' if ok else '<'} min {fmt(arg)}"
    if rule == "max":
        ok = value <= arg
        return _state(ok), value, None, f"{v} {'<=' if ok else '>'} max {fmt(arg)}"
    if rule == "range":
        lo, hi = arg
        ok = lo <= value <= hi
        return _state(ok), value, None, f"{v} {'in' if ok else 'not in'} {fmt(lo)}..{fmt(hi)}"
    # drop_max: previous is the baseline, the newest passing or accepted value
    if previous is None:
        return "pass", value, None, f"{v}, " + ("baseline recorded" if record else "no baseline yet")
    norm = f"{fmt(previous)} * (1 - {fmt(arg)})"
    if exact(value) >= exact(previous) * (1 - exact(arg)):
        return "pass", value, None, f"{v} >= {norm}"
    return ("fail", value, None, f"{v} < {norm}; if the new level is right:"
            f" data_checks.py --accept {check['id']} --reason ...")


def _evaluate(check: dict, root: Path, timeout: float, previous: int | float | None,
              record: bool) -> dict:
    out = {"id": check["id"], "pattern": check["pattern"], "title": check["title"],
           "state": "error", "value": None, "values": None, "detail": ""}
    try:
        stdout, problem = execute(check["cmd"], root, check["timeout_s"] or timeout)
        output = None
        if not problem:
            output, problem = parse(stdout)
        if problem:
            out["detail"] = problem
        else:
            state, value, values, detail = judge(check, output, previous, record)
            out.update(state=state, value=value, values=values, detail=detail)
    except Exception as err:  # noqa: BLE001 - a check that cannot run is a result (B10)
        # The type only: an exception message may quote what the command printed.
        out["detail"] = f"check did not run: {type(err).__name__}"
    return out


# ---------------------------------------------------------------------------
# Runs and evidence
# ---------------------------------------------------------------------------

def _history(root: Path) -> list[dict]:
    path = root / HISTORY
    out = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError):
                item = json.loads(line)
                if isinstance(item, dict):
                    out.append(item)
    return out


def _is_baseline(item: dict) -> bool:
    """A history line drop_max may compare with: a number that passed or that a person
    accepted. A failing value never becomes the norm."""
    return (isinstance(item.get("id"), str) and is_number(item.get("value"))
            and item.get("state") in BASELINE)


def _previous(history: list[dict], cid: str) -> int | float | None:
    """The baseline of drop_max: the newest passing or accepted value of the check."""
    for item in reversed(history):
        if item.get("id") == cid and _is_baseline(item):
            return item["value"]
    return None


def _write(path: Path, text: str) -> None:
    """Through a temporary file, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _append(root: Path, items: list[dict], keep: int, ids: set[str]) -> None:
    """Add history lines; keep the newest `keep` lines and the newest baseline of each
    check in ids, so a failing streak longer than the history never erases the norm
    it is compared with."""
    path = root / HISTORY
    lines = [ln for ln in (path.read_text(encoding="utf-8").splitlines()
                           if path.is_file() else []) if ln.strip()]
    lines += [json.dumps(i, ensure_ascii=False) for i in items]
    kept = set(range(max(len(lines) - keep, 0), len(lines)))
    newest: dict[str, int] = {}
    for n, line in enumerate(lines):
        with contextlib.suppress(ValueError):
            item = json.loads(line)
            if isinstance(item, dict) and _is_baseline(item) and item["id"] in ids:
                newest[item["id"]] = n
    kept.update(newest.values())
    _write(path, "".join(lines[n] + "\n" for n in sorted(kept)))


def _record(root: Path, report: dict, keep: int, ids: set[str]) -> None:
    _write(root / REPORT, json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    items = []
    for c in report["checks"]:
        field = "values" if c["values"] is not None else "value"
        if c[field] is not None:
            items.append({"at": report["at"], "id": c["id"], field: c[field],
                          "state": c["state"]})
    _append(root, items, keep, ids)


def run(root: Path = ROOT, only: list[str] | None = None, record: bool = True) -> dict:
    """Run the checks (all, or the ids in only) and return the report:
    {"at", "checks": [{"id", "pattern", "title", "state", "value", "values", "detail"}],
     "summary": {"total", "passed", "failed", "errors"}}.
    With record, the report goes to harness/.state/data-checks.json and the numbers to
    the history; without it nothing is written. A config error raises ValueError."""
    conf = settings(root)
    checks = load_checks(root)
    ids = {c["id"] for c in checks}
    if only is not None:
        wanted = set(only)
        unknown = [i for i in only if i not in ids]
        if unknown:
            raise ValueError(f"no check {', '.join(map(repr, unknown))} in {conf['file']}")
        checks = [c for c in checks if c["id"] in wanted]
    at = dt.datetime.now().isoformat(timespec="seconds")
    history = _history(root)
    results = [_evaluate(c, root, conf["timeout_s"], _previous(history, c["id"]), record)
               for c in checks]
    states = [r["state"] for r in results]
    report = {"at": at, "checks": results,
              "summary": {"total": len(results), "passed": states.count("pass"),
                          "failed": states.count("fail"), "errors": states.count("error")}}
    if record:
        _record(root, report, int(conf["history_keep"]), ids)
    return report


def last_report(root: Path = ROOT) -> dict | None:
    """The report of the last recorded run; None before the first one."""
    path = root / REPORT
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def accept(root: Path, ids: list[str], reason: str) -> list[dict]:
    """Take the current values of drop_max checks as their new baselines: a decision of
    a person, with a reason. Runs only those checks and records their values with
    state "accepted" and the reason, or nothing at all when one of them errors. The
    report file is left as it is: the next run shows the result.
    Returns [{"id", "pattern", "value", "was", "reason", "at"}], "was" being the
    baseline before (None when there was none).
    ValueError: no reason, no or an unknown id, a check without drop_max, a config
    error. Refused: a check errors, so it has no number to compare."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("--accept needs a reason: why is the new level right?")
    conf = settings(root)
    checks = {c["id"]: c for c in load_checks(root)}
    if not ids:
        raise ValueError("name the checks to accept")
    unknown = [i for i in ids if i not in checks]
    if unknown:
        raise ValueError(f"no check {', '.join(map(repr, unknown))} in {conf['file']}")
    chosen = [checks[i] for i in dict.fromkeys(ids)]
    fixed = [c["id"] for c in chosen if "drop_max" not in c["expect"]]
    if fixed:
        raise ValueError(f"only drop_max checks keep a baseline, not {', '.join(map(repr, fixed))}:"
                         f" change a fixed rule in {conf['file']} instead")
    at = dt.datetime.now().isoformat(timespec="seconds")
    history = _history(root)
    done = []
    for c in chosen:
        was = _previous(history, c["id"])
        done.append((c, was, _evaluate(c, root, conf["timeout_s"], was, True)))
    broken = [f"{c['id']}: {r['detail']}" for c, _, r in done if not is_number(r["value"])]
    if broken:
        raise Refused("; ".join(broken) + "; nothing accepted")
    out = [{"id": c["id"], "pattern": c["pattern"], "value": r["value"], "was": was,
            "reason": reason, "at": at} for c, was, r in done]
    _append(root, [{"at": at, "id": a["id"], "value": a["value"], "state": "accepted",
                    "reason": reason} for a in out], int(conf["history_keep"]), set(checks))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def table(report: dict) -> list[str]:
    """One line per check: state, pattern, id, detail."""
    checks = report["checks"]
    wp = max([len(c["pattern"] or "-") for c in checks] or [1])
    wi = max([len(c["id"]) for c in checks] or [1])
    return [f"{LABEL[c['state']]:<7}{c['pattern'] or '-':<{wp}}  {c['id']:<{wi}}  {c['detail']}"
            for c in checks]


def summary_line(report: dict) -> str:
    s = report["summary"]
    errors = f"{s['errors']} error" + ("" if s["errors"] == 1 else "s")
    return f"data checks: {s['passed']} of {s['total']} pass, {s['failed']} failed, {errors}"


def accepted_line(a: dict) -> str:
    """accepted B8 search-rows: new baseline 812 (was 1040)"""
    who = f"{a['pattern']} {a['id']}" if a["pattern"] else a["id"]
    was = f"was {fmt(a['was'])}" if a["was"] is not None else "no baseline before"
    return f"accepted {who}: new baseline {fmt(a['value'])} ({was})"


def _ids(text: str) -> list[str]:
    return [i.strip() for i in text.split(",") if i.strip()]


def _main_accept(args: argparse.Namespace) -> int:
    try:
        accepted = accept(ROOT, _ids(args.accept), args.reason or "")
    except (ValueError, Refused) as err:
        msg = f"refused: {err}"
        print(json.dumps({"error": msg}, ensure_ascii=False) if args.json else msg)
        return 1 if isinstance(err, Refused) else 2
    if args.json:
        print(json.dumps(accepted, ensure_ascii=False))
    else:
        for a in accepted:
            print(accepted_line(a))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QG6 data invariants: project counters"
                                             " compared with fixed rules")
    ap.add_argument("--only", metavar="ID,ID", help="run only these checks")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--no-record", action="store_true",
                    help="write neither the report nor the history")
    ap.add_argument("--accept", metavar="ID,ID",
                    help="take the current values of these drop_max checks as new baselines")
    ap.add_argument("--reason", help="why the new level is right (required with --accept)")
    args = ap.parse_args(argv)
    if args.accept is not None:
        if args.only is not None or args.no_record:
            ap.error("--accept runs and records only its own checks: drop --only and --no-record")
        return _main_accept(args)
    if args.reason is not None:
        ap.error("--reason goes with --accept")
    only = None
    if args.only is not None:
        only = _ids(args.only)
        if not only:
            ap.error("--only needs check ids, e.g. --only facts-version,search-smoke")
    try:
        rel = settings(ROOT)["file"]
        report = run(ROOT, only, record=not args.no_record)
    except ValueError as err:
        msg = f"config error: {err}"
        print(json.dumps({"error": msg}, ensure_ascii=False) if args.json else msg)
        return 2
    s = report["summary"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for line in table(report):
            print(line)
    if not s["total"]:
        print(f"no data checks in {rel}: an empty check is not a pass",
              file=sys.stderr if args.json else sys.stdout)
        return 1
    if not args.json:
        print(summary_line(report) + (" (not recorded)" if args.no_record else ""))
    return 0 if s["passed"] == s["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
