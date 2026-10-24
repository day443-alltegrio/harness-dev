#!/usr/bin/env python3
"""Golden tasks: fixed tasks done by the real agent, to measure the harness itself.

A sensor that never fires may be blind, and a new rule may only tighten without
helping. Golden tasks answer both. Each one is a small fixed task that a real Claude
Code session (`claude -p`) carries out in a throwaway git worktree of the committed
repository, graded by a deterministic check. Run them after a change of the harness,
after a new agent model and in the periodic review, and compare with the last run.

Two kinds:
  behaviour    - the agent acts as the rules say: it does not change a test to make it
                 pass, it does not print a secret when asked for it;
  integration  - Claude Code really runs the hooks and obeys them: the task names the
                 hook decisions that must appear in the hook log of the worktree
                 (expect_hooks), and its check proves the stopped action did not happen.

Tasks live in harness/config/golden-tasks.json: setup commands, prompt, check, budget.
Setup and check run with GOLDEN_PRIVATE (a folder outside the worktree the agent is not
told about) and GOLDEN_ANSWER (the agent's final answer, written there for the check
and deleted after it). Results, numbers only (state, turns, cost, seconds, hook
decisions), go to harness/.state/golden/<time>.json; the table compares every task with
the previous run.

Every run calls the model and costs tokens, so it is never part of run.sh or a deploy.
It needs the claude CLI, logged in, and runs with Bash allowed inside the worktree: the
guard still applies, and the OS sandbox does too when the project has it on. Only the
committed state is measured: commit the harness change first.

    python3 harness/core/scripts/golden_tasks.py [--only GT-01,GT-03] [--repeat 3] [--model M]
    python3 harness/core/scripts/golden_tasks.py --list
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
KINDS = ("behaviour", "integration")
DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")


def settings(root: Path = ROOT) -> dict:
    return harness_config.load(root)["golden"]


def load_tasks(root: Path = ROOT) -> list[dict]:
    """The tasks of harness/config/golden-tasks.json; ValueError on a malformed one."""
    path = root / settings(root)["file"]
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks, seen = [], set()
    for t in data.get("tasks") or []:
        t = {k: v for k, v in t.items() if not k.startswith("_")}
        missing = [k for k in ("id", "prompt", "check") if not t.get(k)]
        if missing:
            raise ValueError(f"golden task {t.get('id', '?')}: missing {', '.join(missing)}")
        if t["id"] in seen:
            raise ValueError(f"golden task {t['id']}: the id is used twice")
        if t.setdefault("kind", "behaviour") not in KINDS:
            raise ValueError(f"golden task {t['id']}: kind must be one of {', '.join(KINDS)}")
        for h in t.get("expect_hooks") or []:
            if not (isinstance(h, dict) and h.get("rule") and h.get("decision")):
                raise ValueError(f"golden task {t['id']}: expect_hooks items need rule and decision")
        if t["kind"] == "integration" and not t.get("expect_hooks"):
            raise ValueError(f"golden task {t['id']}: an integration task names expect_hooks")
        seen.add(t["id"])
        tasks.append(t)
    return tasks


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def hook_decisions(worktree: Path) -> Counter:
    log_dir = worktree / ".claude" / "hooks" / "harness" / "log"
    seen: Counter = Counter()
    for f in sorted(log_dir.glob("*.jsonl")) if log_dir.is_dir() else []:
        if not DAY_FILE.match(f.name):
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            seen[f"{rec.get('rule')}:{rec.get('decision')}"] += 1
    return seen


def run_task(root: Path, task: dict, conf: dict, model: str | None) -> dict:
    """One run of one task in its own worktree; the worktree is removed after."""
    began = time.monotonic()
    base = Path(tempfile.mkdtemp(prefix="golden-"))
    wt, private = base / "worktree", base / "private"
    private.mkdir()
    env = {**os.environ, "GOLDEN_PRIVATE": str(private), "GOLDEN_ANSWER": str(private / "answer.txt")}
    rec = {"id": task["id"], "kind": task["kind"], "state": "error", "detail": "", "turns": None,
           "cost_usd": None, "seconds": None, "hooks": {}}
    try:
        r = git(root, "worktree", "add", "--detach", str(wt), "HEAD")
        if r.returncode != 0:
            rec["detail"] = "no worktree: is there a commit?"
            return rec
        for cmd in task.get("setup") or []:
            s = subprocess.run(cmd, shell=True, cwd=wt, env=env, capture_output=True, text=True,
                               timeout=300)
            if s.returncode != 0:
                rec["detail"] = f"setup failed: exit {s.returncode}"
                return rec
        args = [conf["claude"], "-p", task["prompt"], "--output-format", "json", "--no-session-persistence",
                "--max-turns", str(task.get("max_turns") or conf["max_turns"]),
                "--permission-mode", task.get("permission_mode") or conf["permission_mode"]]
        tools = task.get("allowed_tools") or conf["allowed_tools"]
        if tools:
            args += ["--allowedTools", tools]
        chosen = task.get("model") or model or conf["model"]
        if chosen:
            args += ["--model", chosen]
        agent_env = {k: v for k, v in os.environ.items() if not k.startswith("GOLDEN_")}
        try:
            c = subprocess.run(args, cwd=wt, env=agent_env, capture_output=True, text=True,
                               timeout=int(task.get("timeout_s") or conf["timeout_s"]))
        except subprocess.TimeoutExpired:
            rec["detail"] = f"the agent ran over {task.get('timeout_s') or conf['timeout_s']} s"
            return rec
        try:
            out = json.loads(c.stdout.strip().splitlines()[-1]) if c.stdout.strip() else {}
        except ValueError:
            out = {}
        if not isinstance(out, dict) or "result" not in out and "subtype" not in out:
            rec["detail"] = f"no JSON result from {conf['claude']} (exit {c.returncode})"
            return rec
        rec.update(turns=out.get("num_turns"), cost_usd=out.get("total_cost_usd"),
                   subtype=out.get("subtype"))
        (private / "answer.txt").write_text(str(out.get("result") or ""), encoding="utf-8")
        chk = subprocess.run(task["check"], shell=True, cwd=wt, env=env, capture_output=True,
                             text=True, timeout=300)
        hooks = hook_decisions(wt)
        rec["hooks"] = dict(hooks)
        missing = [f"{h['rule']}:{h['decision']}" for h in task.get("expect_hooks") or []
                   if not hooks.get(f"{h['rule']}:{h['decision']}")]
        problems = ([f"check exit {chk.returncode}"] if chk.returncode else []) + \
                   [f"no hook decision {m}" for m in missing]
        rec["state"] = "fail" if problems else "pass"
        rec["detail"] = "; ".join(problems)
        return rec
    finally:
        rec["seconds"] = round(time.monotonic() - began, 1)
        git(root, "worktree", "remove", "--force", str(wt))
        git(root, "worktree", "prune")
        shutil.rmtree(base, ignore_errors=True)


def previous(root: Path) -> dict | None:
    runs = sorted((root / "harness" / ".state" / "golden").glob("*.json"))
    return json.loads(runs[-1].read_text(encoding="utf-8")) if runs else None


def rates(results: list[dict]) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {}
    for r in results:
        c = out.setdefault(r["id"], [0, 0])
        c[0] += r["state"] == "pass"
        c[1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def claude_version(conf: dict) -> str | None:
    try:
        r = subprocess.run([conf["claude"], "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout.strip().splitlines() or [None])[0] if r.returncode == 0 else None


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description="Golden tasks: the real agent on fixed tasks")
    ap.add_argument("--only", help="task ids, comma separated")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--model")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    conf = settings(root)
    try:
        tasks = load_tasks(root)
    except ValueError as err:
        print(err)
        return 2
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
    if args.list:
        for t in tasks:
            print(f"{t['id']:<8} {t['kind']:<12} {t.get('title', '')}")
        return 0
    if not tasks:
        print(f"no golden tasks in {conf['file']}: nothing measured is not a pass")
        return 1
    version = claude_version(conf)
    if not version:
        print(f"{conf['claude']} --version failed: install and log in to the claude CLI")
        return 2
    if git(root, "status", "--porcelain").stdout.strip():
        print("note: uncommitted changes are not in the worktree; the run measures HEAD")
    runs = len(tasks) * args.repeat
    print(f"{runs} runs of {conf['claude']} ({version}): each one calls the model")
    results = []
    for task in tasks:
        for _ in range(args.repeat):
            rec = run_task(root, task, conf, args.model)
            results.append(rec)
            cost = f"${rec['cost_usd']:.2f}" if isinstance(rec["cost_usd"], (int, float)) else "-"
            print(f"{rec['state']:<6} {rec['id']:<8} {rec['kind']:<12} turns {rec['turns'] or '-':<3} "
                  f"{cost:>6} {rec['seconds']:>6} s  {rec['detail']}")
    now, before = rates(results), previous(root)
    old = rates(before["results"]) if before else {}
    for tid, (ok, n) in now.items():
        was = f", before {old[tid][0]}/{old[tid][1]}" if tid in old else ""
        print(f"  {tid}: {ok}/{n} passed{was}")
    total_cost = sum(r["cost_usd"] or 0 for r in results if isinstance(r["cost_usd"], (int, float)))
    report = {"at": dt.datetime.now().isoformat(timespec="seconds"), "claude": version,
              "model": args.model or conf["model"], "commit": git(root, "rev-parse", "--short", "HEAD").stdout.strip(),
              "kit_version": (root / "harness" / "core" / "VERSION").read_text().strip()
              if (root / "harness" / "core" / "VERSION").is_file() else None,
              "results": results, "passed": sum(r["state"] == "pass" for r in results),
              "runs": runs, "cost_usd": round(total_cost, 4)}
    out = root / "harness" / ".state" / "golden" / f"{dt.datetime.now():%Y-%m-%dT%H-%M-%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{report['passed']}/{runs} passed, ${report['cost_usd']:.2f}; {out.relative_to(root)}")
    return 0 if report["passed"] == runs else 1


if __name__ == "__main__":
    sys.exit(main())
