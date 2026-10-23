#!/usr/bin/env python3
"""Quality gate results as a short fixed table, for the chat with the agent.

The agent pastes this output as is instead of retelling it (harness/core/rules.md,
"Quality gate report"). Active gates show their result; gates being built or switched
off show only the reason. States and checks live in harness/config/gates.json.

Checks a gate can use ("check" in gates.json):
  hook_log       - today's guard hook log (.claude/hooks/harness/log/<date>.jsonl);
  quality        - harness tests, context budget, pinned dependencies and plugins
                   (no network);
  preflight      - preflight without the slow scanners (the deploy runs them in full);
  deploy_report  - the last deploy check report (harness/.state/deploy-last.json),
                   written by harness/core/scripts/deploy.sh;
  snapshot       - the last nightly snapshot (harness/.state/snapshot.json), its
                   "problems" list;
  docs           - scenarios of people against the code (doc_coverage.py);
  command        - any shell command ("command" key): exit 0 passes, the last output
                   line is the detail.

    python3 harness/core/scripts/gates.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
STATE = harness_config.STATE
LABEL = {"in_progress": "in progress", "disabled": "off"}


def _short(items: list[str], n: int = 2) -> str:
    shown = "; ".join(i[:110] for i in items[:n])
    return shown + (f"; +{len(items) - n} more" if len(items) > n else "")


def _age_hours(path: Path) -> float:
    return (dt.datetime.now().timestamp() - path.stat().st_mtime) / 3600


def _stale_hours() -> int:
    return int(harness_config.load()["stale_hours"])


def hook_log(gate: dict) -> tuple[str, str]:
    log = harness_config.HOOK_LOG / f"{dt.date.today().isoformat()}.jsonl"
    if not log.is_file():
        # No log is no evidence: the hook may not have run at all (B10).
        return "unknown", "no hook log today"
    seen = Counter()
    for line in log.read_text(encoding="utf-8").splitlines():
        with contextlib.suppress(ValueError):
            d = json.loads(line)
            seen[(d.get("decision"), d.get("rule"))] += 1
    deny = sum(n for (dec, _), n in seen.items() if dec in ("deny", "block"))
    ask = sum(n for (dec, _), n in seen.items() if dec == "ask")
    top = ", ".join(f"{r} {n}" for (_, r), n in seen.most_common(3))
    return "pass", f"today: {deny} blocked, {ask} asked ({top})"


def quality(gate: dict) -> tuple[str, str]:
    import context_budget  # noqa: PLC0415
    import supply_chain  # noqa: PLC0415
    run, bad = harness_config.run_tests()
    if run == 0:
        return "fail", "no harness tests found (B10: an empty check is a failure)"
    over = [r["name"] for r in context_budget.measure() if not r["ok"]]
    pins = supply_chain.check_pins() + supply_chain.check_plugins()
    found = ([f"{bad} of {run} tests fail"] if bad else []) \
        + [f"context over budget: {n}" for n in over] + pins
    if found:
        return "fail", _short(found)
    drift = core_drift()
    if drift:
        return "warn", (f"tests {run}/{run}, but {len(drift)} kit files changed locally"
                        f" ({_short(drift, 1)}): move the change to the kit, or the next"
                        " upgrade keeps it as a conflict")
    return "pass", f"tests {run}/{run}, context in budget, pins and plugins ok"


def core_drift() -> list[str]:
    """Kit-owned files that differ from what the last install or upgrade wrote
    (harness/harness.lock.json): local edits the kit does not know about."""
    lock = harness_config.read_json(ROOT / "harness" / "harness.lock.json", {})
    out = []
    for rel, digest in sorted((lock.get("managed") or {}).items()):
        p = ROOT / rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            out.append(rel)
    return out


def preflight(gate: dict) -> tuple[str, str]:
    import preflight as pf  # noqa: PLC0415
    problems = [p for p in pf.run(tools=False) if not p.startswith("QG8")]
    if problems:
        return "fail", _short(problems)
    return "pass", "commit, branch, lineage, contract ok (scanners run at deploy)"


def deploy_report(gate: dict) -> tuple[str, str]:
    path = STATE / "deploy-last.json"
    if not path.is_file():
        return "unknown", "no local report yet (written by harness/core/scripts/deploy.sh)"
    rep = json.loads(path.read_text(encoding="utf-8"))
    tests = rep.get("tests") or {}
    sec = rep.get("security") or {}
    parts = [f"deploy {rep.get('deploy_id') or '-'} at {rep.get('at', '?')}"]
    if tests:
        parts.append(f"tests {tests.get('passed')}/{tests.get('files')}")
    if sec.get("required"):
        parts.append(f"security {sec.get('passed')}/{len(sec['required'])}")
    state = "pass" if rep.get("verdict") == "pass" else "fail"
    if state == "fail" and rep.get("reasons"):
        parts.append(_short(list(rep["reasons"]), 1))
    if state == "pass" and _age_hours(path) > _stale_hours():
        state = "warn"
        parts.append(f"stale: older than {_stale_hours()} h")
    return state, ", ".join(parts)


def snapshot(gate: dict) -> tuple[str, str]:
    path = STATE / "snapshot.json"
    if not path.is_file():
        return "unknown", "no local snapshot (harness/core/scripts/snapshot.py, nightly)"
    snap = json.loads(path.read_text(encoding="utf-8"))
    at = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    problems = list(snap.get("problems") or [])
    if problems:
        return "fail", f"snapshot {at}: " + _short(problems)
    if _age_hours(path) > _stale_hours():
        return "warn", f"snapshot {at} is stale (older than {_stale_hours()} h): no findings then"
    return "pass", f"snapshot {at}: no findings"


def docs(gate: dict) -> tuple[str, str]:
    import doc_coverage  # noqa: PLC0415
    s = doc_coverage.summary(doc_coverage.State(ROOT))
    head = f"scenarios {s['in_sync']}/{s['people']} in sync, {s['with_tests']} with tests"
    if s["problems"]:
        return "fail", head + ": " + _short(s["problems"], 1)
    if s["decisions_open"]:
        return "warn", head + f", {s['decisions_open']} deferred"
    return "pass", head


def command(gate: dict) -> tuple[str, str]:
    r = subprocess.run(gate["command"], shell=True, cwd=ROOT, capture_output=True,
                       text=True, timeout=int(gate.get("timeout_s", 300)))
    lines = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
    detail = lines[-1][:160] if lines else "no output"
    return ("pass" if r.returncode == 0 else "fail"), detail


CHECKS = {"hook_log": hook_log, "quality": quality, "preflight": preflight,
          "deploy_report": deploy_report, "snapshot": snapshot, "docs": docs,
          "command": command}


def rows(conf_path: Path | None = None) -> list[tuple[str, str, str, str]]:
    conf_path = conf_path or ROOT / "harness" / "config" / "gates.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))["gates"]
    out = []
    for gid, g in conf.items():
        if g["state"] != "active":
            out.append((gid, g["name"], LABEL[g["state"]], g.get("reason", "")))
            continue
        kind = g.get("check") or ("command" if g.get("command") else None)
        try:
            if kind not in CHECKS:
                raise ValueError(f"no check for an active gate (check={kind!r})")
            state, detail = CHECKS[kind](g)
        except Exception as err:  # noqa: BLE001 - a check that cannot run is a result too (B10)
            state, detail = "error", f"check did not run: {err}"
        out.append((gid, g["name"], state, detail))
    return out


def main() -> int:
    table = rows()
    w = max(len(r[1]) for r in table)
    for gid, name, state, detail in table:
        print(f"{gid}  {name:<{w}}  {state:<11}  {detail}")
    return 1 if any(r[2] in ("fail", "error") for r in table) else 0


if __name__ == "__main__":
    sys.exit(main())
