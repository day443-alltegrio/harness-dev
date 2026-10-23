#!/usr/bin/env python3
"""QG3 deploy check: verifies new code on the target machine before it replaces the
running code (the "Agent Deployer" of harness/core/docs/design.md).

The deploy puts the new code into a temporary folder on the machine and, before
touching the running code, runs from there:

    python3 harness/core/scripts/deploy_check.py check --staged <dir> --current <dir>

<dir> is the code root of the service (tests_glob and pythonpath are relative to it;
settings in deploy_check of harness.json). Checks:

1. API contract. The OpenAPI schema of the new code is compared with the schema of the
   running code: a removed operation, a new required parameter or request field, a
   changed type, a removed response field break whoever already calls the service
   (open browser tabs with the old UI, scripts, agents). Such a deploy stops unless the
   break is allowed explicitly (--allow-breaking with a reason). Skipped when
   openapi_cmd is not set.
2. Every test file of the new code (tests_glob), one process per file, without the
   variables that switch tests to live databases (env_drop).
3. Security tests (security_tests): the same runs, reported separately; a missing one
   is a failure too.

Result: one JSON line on stdout (the deploy journal stores it) and the exit code:
0 - may deploy, 1 - stopped, 2 - the check itself failed. Nothing is changed: no code,
no database, no service.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

AGENT = "agent:deployer"
_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
_PARAM = re.compile(r"\{[^}]+\}")


def settings() -> dict:
    return harness_config.load()["deploy_check"]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

def _env(root: Path, conf: dict) -> dict:
    """Child process environment: the code of root first on the path, no variables that
    switch tests to live systems, no colours in tracebacks (they go to the journal)."""
    env = {k: v for k, v in os.environ.items() if k not in set(conf["env_drop"])}
    rest = [str(Path(p).resolve()) for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    own = [str(root / p) for p in conf["pythonpath"]]
    env["PYTHONPATH"] = os.pathsep.join([*own, *rest])
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHON_COLORS="0", NO_COLOR="1")
    return env


def openapi_of(root: Path, conf: dict) -> dict:
    """OpenAPI schema of the code in root, in a separate process so the old and the new
    code never mix in one interpreter."""
    cmd = conf["openapi_cmd"].replace("{python}", shlex.quote(sys.executable))
    out = subprocess.run(cmd, shell=True, env=_env(root, conf), cwd=str(root),
                         capture_output=True, text=True, timeout=conf["timeout_s"], check=False)
    if out.returncode != 0:
        tail = (out.stderr or out.stdout).strip().splitlines()[-3:]
        raise RuntimeError("no OpenAPI schema: " + " | ".join(tail))
    return json.loads(out.stdout)


def _deref(spec: dict, schema: dict | None, seen: frozenset = frozenset()) -> dict:
    """The schema with $ref resolved (one level at a time; a cycle gives an empty schema)."""
    schema = schema or {}
    ref = schema.get("$ref")
    if not ref:
        return schema
    if ref in seen:
        return {}
    name = ref.rsplit("/", 1)[-1]
    return _deref(spec, spec.get("components", {}).get("schemas", {}).get(name), seen | {ref})


def _unwrap(spec: dict, schema: dict | None) -> tuple[dict, bool]:
    """(schema without the null variant, whether null is allowed). Optional[X] in
    pydantic is anyOf [X, {"type": "null"}]."""
    schema = _deref(spec, schema)
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        rest = [v for v in variants if v.get("type") != "null"]
        nullable = len(rest) < len(variants)
        if len(rest) == 1:
            inner, more = _unwrap(spec, rest[0])
            return inner, nullable or more
        return {"anyOf": rest}, nullable
    return schema, schema.get("type") == "null"


def _kind(schema: dict) -> str | None:
    if "anyOf" in schema:
        return "anyOf"
    t = schema.get("type")
    if t is None and "properties" in schema:
        return "object"
    return t


def _compatible(old: str | None, new: str | None, mode: str) -> bool:
    if old is None or new is None or old == new:
        return True
    # An integer in a request accepts a number too: wider, nothing breaks. In a
    # response the other way round: the client reads an integer where a number was.
    if mode == "request" and (old, new) == ("integer", "number"):
        return True
    return mode == "response" and (old, new) == ("number", "integer")


def compare_schema(old_spec: dict, new_spec: dict, old: dict | None, new: dict | None,
                   mode: str, where: str, out: list[dict], depth: int = 0) -> None:
    """Difference of two schemas. mode "request" is what the client sends, "response"
    what it reads. A break is kind "breaking", the rest is "change"."""
    if depth > 12:
        return
    o, o_null = _unwrap(old_spec, old)
    n, n_null = _unwrap(new_spec, new)
    if not o:
        return
    if not n:
        out.append({"kind": "change", "where": where, "what": "schema became untyped"})
        return
    ok, nk = _kind(o), _kind(n)
    if not _compatible(ok, nk, mode):
        out.append({"kind": "breaking", "where": where, "what": f"type {ok} became {nk}"})
        return
    if mode == "request" and o_null and not n_null:
        out.append({"kind": "breaking", "where": where, "what": "null no longer accepted"})
    if mode == "response" and n_null and not o_null:
        out.append({"kind": "change", "where": where, "what": "response may be null"})
    o_enum, n_enum = o.get("enum"), n.get("enum")
    if o_enum is not None and n_enum is not None:
        lost = [v for v in o_enum if v not in n_enum]
        added = [v for v in n_enum if v not in o_enum]
        if lost:
            out.append({"kind": "breaking" if mode == "request" else "change",
                        "where": where, "what": f"values removed {lost}"})
        if added:
            out.append({"kind": "change" if mode == "request" else "breaking",
                        "where": where, "what": f"new values {added}"})
    if ok == "array":
        compare_schema(old_spec, new_spec, o.get("items"), n.get("items"), mode,
                       where + "[]", out, depth + 1)
        return
    if ok != "object":
        return
    o_props, n_props = o.get("properties") or {}, n.get("properties") or {}
    o_req, n_req = set(o.get("required") or ()), set(n.get("required") or ())
    for name in sorted(set(o_props) | set(n_props)):
        here = f"{where}.{name}"
        if name not in n_props:
            if mode == "response":
                out.append({"kind": "breaking", "where": here, "what": "response field removed"})
            elif n.get("additionalProperties") is False:
                out.append({"kind": "breaking", "where": here,
                            "what": "request field removed, extra fields forbidden"})
            else:
                out.append({"kind": "change", "where": here,
                            "what": "request field removed (extra ones are ignored)"})
            continue
        if name not in o_props:
            if mode == "request" and name in n_req:
                out.append({"kind": "breaking", "where": here, "what": "new required request field"})
            else:
                out.append({"kind": "change", "where": here, "what": "new field"})
            continue
        if mode == "request" and name in n_req and name not in o_req:
            out.append({"kind": "breaking", "where": here, "what": "request field became required"})
        if mode == "response" and name in o_req and name not in n_req:
            out.append({"kind": "breaking", "where": here, "what": "response field became optional"})
        compare_schema(old_spec, new_spec, o_props[name], n_props[name], mode, here, out,
                       depth + 1)


def _operations(spec: dict) -> dict[tuple[str, str], tuple[str, dict]]:
    """{(METHOD, path with {} instead of parameter names): (path, operation)}: a renamed
    path parameter ("/x/{id}" and "/x/{item_id}") is the same operation."""
    ops = {}
    for path, item in (spec.get("paths") or {}).items():
        for method in _METHODS:
            if method in item:
                ops[(method.upper(), _PARAM.sub("{}", path))] = (path, item[method])
    return ops


def _json_schema(body: dict | None) -> dict | None:
    content = (body or {}).get("content") or {}
    for mime in ("application/json", *content):
        if mime in content:
            return content[mime].get("schema")
    return None


def _success(op: dict) -> dict[str, dict]:
    return {code: r for code, r in (op.get("responses") or {}).items()
            if str(code).startswith("2")}


def contract_diff(old_spec: dict, new_spec: dict) -> list[dict]:
    """[{"kind", "op", "where", "what"}]: "breaking" breaks those who already call the
    service, "change" is new or compatible."""
    out: list[dict] = []
    old_ops, new_ops = _operations(old_spec), _operations(new_spec)

    def add(kind: str, op: str, what: str, where: str = "") -> None:
        out.append({"kind": kind, "op": op, "where": where, "what": what})

    for key in sorted(set(old_ops) - set(new_ops)):
        add("breaking", f"{key[0]} {old_ops[key][0]}", "operation removed")
    for key in sorted(set(new_ops) - set(old_ops)):
        add("change", f"{key[0]} {new_ops[key][0]}", "new operation")
    for key in sorted(set(old_ops) & set(new_ops)):
        name = f"{key[0]} {new_ops[key][0]}"
        o, n = old_ops[key][1], new_ops[key][1]
        o_par = {(p.get("in"), p.get("name")): p
                 for p in (_deref(old_spec, p) for p in o.get("parameters") or ())}
        n_par = {(p.get("in"), p.get("name")): p
                 for p in (_deref(new_spec, p) for p in n.get("parameters") or ())}
        for pk in sorted(set(n_par) - set(o_par), key=str):
            if n_par[pk].get("required") and pk[0] != "path":
                add("breaking", name, "new required parameter", f"{pk[0]}:{pk[1]}")
            else:
                add("change", name, "new parameter", f"{pk[0]}:{pk[1]}")
        for pk in sorted(set(o_par) - set(n_par), key=str):
            if pk[0] != "path":
                add("change", name, "parameter removed (ignored)", f"{pk[0]}:{pk[1]}")
        for pk in sorted(set(o_par) & set(n_par), key=str):
            if n_par[pk].get("required") and not o_par[pk].get("required"):
                add("breaking", name, "parameter became required", f"{pk[0]}:{pk[1]}")
            found: list[dict] = []
            compare_schema(old_spec, new_spec, o_par[pk].get("schema"), n_par[pk].get("schema"),
                           "request", f"{pk[0]}:{pk[1]}", found)
            out.extend({**f, "op": name} for f in found)
        o_body, n_body = o.get("requestBody"), n.get("requestBody")
        if n_body and not o_body:
            add("breaking" if n_body.get("required") else "change", name, "new request body")
        elif o_body and n_body:
            if n_body.get("required") and not o_body.get("required"):
                add("breaking", name, "request body became required")
            found = []
            compare_schema(old_spec, new_spec, _json_schema(o_body), _json_schema(n_body),
                           "request", "body", found)
            out.extend({**f, "op": name} for f in found)
        o_ok, n_ok = _success(o), _success(n)
        for code in sorted(set(o_ok) - set(n_ok)):
            add("breaking", name, f"success code {code} removed")
        for code in sorted(set(o_ok) & set(n_ok)):
            found = []
            compare_schema(old_spec, new_spec, _json_schema(o_ok[code]), _json_schema(n_ok[code]),
                           "response", f"{code}", found)
            out.extend({**f, "op": name} for f in found)
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_test(root: Path, test: Path, conf: dict) -> dict:
    """One test file: exit code, time, the output tail on failure."""
    cmd = conf["test_cmd"].replace("{python}", shlex.quote(sys.executable)) \
                          .replace("{file}", shlex.quote(str(test)))
    began = time.monotonic()
    try:
        done = subprocess.run(cmd, shell=True, env=_env(root, conf), cwd=str(root),
                              capture_output=True, text=True, timeout=conf["timeout_s"],
                              check=False)
        rc, text = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as err:
        rc = -1
        raw = err.stdout or ""
        text = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        text += f"\nover {conf['timeout_s']} s"
    result = {"file": test.name, "rc": rc, "took_ms": int((time.monotonic() - began) * 1000)}
    if rc != 0:
        result["tail"] = text.strip().splitlines()[-5:]
    return result


def run_tests(root: Path, conf: dict) -> list[dict]:
    return [run_test(root, t, conf) for t in sorted(root.glob(conf["tests_glob"]))]


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def verdict(contract: dict, tests: list[dict], allow_breaking: str | None,
            security: tuple[str, ...]) -> dict:
    reasons = []
    if contract.get("error"):
        reasons.append(f"contract not checked: {contract['error']}")
    breaking = [c for c in contract.get("changes", []) if c["kind"] == "breaking"]
    if breaking and not allow_breaking:
        reasons.append(f"API contract broken: {len(breaking)} changes")
    if not tests:
        # No tests ran: no evidence, not a pass (B10).
        reasons.append("no test files found")
    failed = [t["file"] for t in tests if t["rc"] != 0]
    security_failed = [f for f in failed if f in security]
    if security_failed:
        reasons.append("security tests failed: " + ", ".join(security_failed))
    other = [f for f in failed if f not in security]
    if other:
        reasons.append("tests failed: " + ", ".join(other))
    missing = [s for s in security if s not in {t["file"] for t in tests}]
    if missing:
        reasons.append("security tests missing: " + ", ".join(missing))
    return {"verdict": "blocked" if reasons else "pass", "reasons": reasons}


def summary(contract: dict, tests: list[dict], allow_breaking: str | None,
            security: tuple[str, ...]) -> dict:
    """Short report for the deploy journal, without the output of passing tests."""
    changes = contract.get("changes", [])
    breaking = [c for c in changes if c["kind"] == "breaking"]
    sec = [t for t in tests if t["file"] in security]
    return {
        "agent": AGENT,
        **verdict(contract, tests, allow_breaking, security),
        "contract": {
            "baseline": contract.get("baseline"),
            "operations": contract.get("operations"),
            "breaking": breaking[:50],
            "changes": len(changes) - len(breaking),
            "added": [c["op"] for c in changes if c["what"] == "new operation"][:50],
            "allowed_breaking": allow_breaking if breaking else None,
            "error": contract.get("error"),
        },
        "tests": {"files": len(tests), "passed": sum(t["rc"] == 0 for t in tests),
                  "failed": [t for t in tests if t["rc"] != 0]},
        "security": {"files": len(sec), "passed": sum(t["rc"] == 0 for t in sec),
                     "required": list(security)},
    }


def check(staged: Path, current: Path | None, allow_breaking: str | None,
          conf: dict | None = None) -> dict:
    conf = conf or settings()
    began = time.monotonic()
    staged = staged.resolve()
    current = current.resolve() if current else None
    contract: dict = {}
    if conf["openapi_cmd"]:
        try:
            new = openapi_of(staged, conf)
            contract["operations"] = len(_operations(new))
            if current and current.is_dir():
                contract["baseline"] = "running code"
                contract["changes"] = contract_diff(openapi_of(current, conf), new)
            else:
                contract.update(baseline=None, changes=[])
        except Exception as err:  # noqa: BLE001
            contract["error"] = f"{type(err).__name__}: {err}"[:500]
    security = tuple(conf["security_tests"])
    tests = run_tests(staged, conf)
    out = summary(contract, tests, allow_breaking, security)
    out["took_s"] = round(time.monotonic() - began, 1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QG3 deploy check before the code is replaced")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--staged", required=True, type=Path)
    c.add_argument("--current", type=Path)
    c.add_argument("--allow-breaking", default=None,
                   help="the reason why breaking the API contract is allowed")
    args = ap.parse_args(argv)
    try:
        out = check(args.staged, args.current, (args.allow_breaking or "").strip() or None)
    except Exception as err:  # noqa: BLE001
        print(json.dumps({"agent": AGENT, "verdict": "error",
                          "reasons": [f"{type(err).__name__}: {err}"[:500]]}, ensure_ascii=False))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
