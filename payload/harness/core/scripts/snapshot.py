#!/usr/bin/env python3
"""Nightly snapshot of the harness: numbers and names only (harness/core/docs/design.md, "Measure").

Collects the harness tests, the context budget, the supply chain, the failure pattern
coverage, task contracts of recent commits, documentation coverage (when enabled), the
"before" regression cases, secrets in the git history and agent telemetry, and writes
them to
harness/.state/snapshot.json. "problems" lists what fails; the snapshot gate of
gates.py shows it and marks the snapshot stale after stale_hours.

Run it nightly (cron, launchd or a CI schedule) and, if the project has a dashboard,
push the JSON there. No text of documents, commands or prompts goes into it.

    python3 harness/core/scripts/snapshot.py [--offline]   # --offline: no vulnerability scan
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_metrics  # noqa: E402
import commit_scan  # noqa: E402
import context_budget  # noqa: E402
import contract_check  # noqa: E402
import harness_config  # noqa: E402
import supply_chain  # noqa: E402

ROOT = harness_config.ROOT


def tests() -> dict:
    run, bad = harness_config.run_tests()
    return {"run": run, "failed": bad}


def coverage() -> dict:
    reg = harness_config.read_json(ROOT / "harness" / "config" / "incident-coverage.json",
                                   {"patterns": {}})["patterns"]
    by = {s: sum(1 for p in reg.values() if p["status"] == s) for s in ("covered", "partial", "none")}
    return {"total": len(reg), **by}


def contracts(n: int = 30) -> dict:
    """Of the last n commits: how many needed a contract and how many had one."""
    log = subprocess.run(["git", "log", f"-{n}", "--format=%H"], cwd=ROOT,
                         capture_output=True, text=True).stdout.split()
    needed = had = 0
    for sha in log:
        files = subprocess.run(["git", "show", "--name-only", "--format=", sha], cwd=ROOT,
                               capture_output=True, text=True).stdout.split()
        if contract_check.reasons(files, ROOT):
            needed += 1
            cdir = harness_config.load()["contracts"]["dir"]
            had += any(f.startswith(cdir) and not f.endswith("TEMPLATE.md") for f in files)
    return {"commits": len(log), "needed": needed, "had": had}


def build(offline: bool = False) -> dict:
    problems: list[str] = []
    t = tests()
    if not t["run"] or t["failed"]:
        problems.append(f"harness tests: {t['failed']} of {t['run']} fail")
    budget = context_budget.measure()
    problems += [f"context over budget: {r['name']}" for r in budget if not r["ok"]]
    pins = supply_chain.check_pins() + supply_chain.check_plugins()
    problems += pins
    vulns: dict = {"skipped": True}
    sc = harness_config.load()["supply_chain"]
    if not offline and (sc["python"] or sc["npm"]):
        try:
            found, vulns = supply_chain.check_vulns()
            problems += found
        except Exception as err:  # noqa: BLE001 - could not measure is a failure (B10)
            problems.append(f"vulnerability scanner failed: {err}")
    import regressions  # noqa: PLC0415
    try:
        reg = regressions.run(ROOT, "before")
        reg = {k: reg[k] for k in ("cases", "passed", "failed", "errors")}
        bad = reg["failed"] + reg["errors"]
        if bad:
            problems.append(f"regression cases failed: {', '.join(bad)}")
    except ValueError as err:
        reg = {"error": str(err).splitlines()[0][:200]}
        problems.append("regression cases malformed")
    history = commit_scan.history_secrets()
    if history:
        problems.append(f"{len(history)} secrets in the git history")
    docs: dict = {"enabled": False}
    if harness_config.load()["docs"]["enabled"]:
        import doc_coverage  # noqa: PLC0415
        docs = doc_coverage.summary(doc_coverage.State(ROOT))
        problems += [f"QG8 {p}" for p in docs["problems"]]
    agent = agent_metrics.collect(Path.home() / ".claude" / "projects" / agent_metrics.slug(ROOT),
                                  harness_config.HOOK_LOG, 7)
    return {"at": dt.datetime.now().isoformat(timespec="seconds"), "problems": problems,
            "tests": t, "context": budget, "supply_chain": {"pins_and_plugins": pins,
                                                            "vulns": vulns},
            "coverage": coverage(), "contracts": contracts(), "docs": docs, "regressions": reg,
            "history_secrets": len(history), "agent": agent}


def main(argv: list[str]) -> int:
    snap = build("--offline" in argv)
    out = harness_config.STATE / "snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"snapshot: {out.relative_to(ROOT)}, problems: {len(snap['problems'])}")
    for p in snap["problems"]:
        print(f"  {p}")
    return 1 if snap["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
