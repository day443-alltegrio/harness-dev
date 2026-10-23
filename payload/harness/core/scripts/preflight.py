#!/usr/bin/env python3
"""QG2: checks on the developer machine at the start of a deploy (harness/core/docs/design.md).

They close the most frequent deploy failure, "the server runs the wrong code"
(A1, A4 in harness/core/docs/failure-patterns.md):
  worktree  - deploy only from the main working copy on the deploy branch
              (deploy_branch in harness.json, env DEPLOY_BRANCH), not from an agent
              worktree;
  clean     - the working tree is clean: only committed code ships. Paths the build
              or the deploy rewrites (generated) do not count;
  build     - optional (build_stamp): the build was made from the current commit, its
              stamp starts with HEAD and has no "+" (built from a dirty tree);
  lineage   - the new commit descends from the last deployed one (deployed_ref, set by
              the deploy after a success): a deploy never overwrites other work;
  contract  - a change since the last deploy that touches risky paths or many files
              has a task contract (contract_check.py);
  docs      - optional QG8: scenarios of people match the code (doc_coverage.py);
  scan      - the added lines hold no secrets, project IDs or names; shellcheck and
              bandit when enabled (commit_scan.py);
  vulns     - no critical vulnerability in the deployed apps, the rest accepted with
              a review date (supply_chain.py).

    python3 harness/core/scripts/preflight.py            # exit 1 and the reasons
    python3 harness/core/scripts/preflight.py --report   # stdin: preflight output, stdout: JSON
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import commit_scan  # noqa: E402
import contract_check  # noqa: E402
import harness_config  # noqa: E402
import supply_chain  # noqa: E402

ROOT = harness_config.ROOT


def git(root: Path, *args: str) -> str:
    """git output without the trailing newline; leading spaces matter
    (`status --porcelain` may start with a space)."""
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, check=True).stdout.rstrip("\n")


def check_worktree(root: Path, branch: str) -> list[str]:
    problems = []
    top = git(root, "rev-parse", "--show-toplevel")
    if "/.claude/worktrees/" in top + "/":
        problems.append(f"deploy from an agent worktree ({top}): merge into the main copy first")
    current = git(root, "branch", "--show-current")
    if current != branch:
        problems.append(f"branch {current or '(detached)'}, but deploys go only from {branch}")
    return problems


def check_clean(root: Path, generated: tuple[str, ...]) -> list[str]:
    dirty = []
    for line in git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if not (generated and path.startswith(generated)):
            dirty.append(path)
    if not dirty:
        return []
    shown = ", ".join(dirty[:5]) + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
    return [f"{len(dirty)} uncommitted files ({shown}): commit first"]


def check_build(root: Path, stamp: dict | None) -> list[str]:
    if not stamp:
        return []
    f = root / stamp["file"]
    if not f.is_file():
        return [f"no build stamp {stamp['file']}: build first"]
    version = str(json.loads(f.read_text(encoding="utf-8")).get(stamp.get("key", "version"), ""))
    head = git(root, "rev-parse", "--short", "HEAD")
    built = version.split("-")[0]
    if built.endswith("+"):
        return [f"built from uncommitted code ({version}): commit, then build"]
    if len(built) < 7 or not (built.startswith(head) or head.startswith(built)):
        return [f"built from {built or '?'}, but HEAD is {head}: rebuild"]
    return []


def deploy_base(root: Path, ref: str) -> str:
    """What to count changes from: the last deployed commit, else HEAD~1."""
    r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=root,
                       capture_output=True, text=True)
    return r.stdout.strip() or "HEAD~1"


def check_lineage(root: Path, base: str) -> list[str]:
    if base == "HEAD~1":
        return []
    r = subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=root)
    return [] if r.returncode == 0 else [
        f"HEAD does not continue the deployed commit {base[:7]}: the deploy would overwrite other work"]


def check_docs(root: Path, enabled: bool) -> list[str]:
    if not enabled:
        return []
    import doc_coverage  # noqa: PLC0415
    try:
        problems = doc_coverage.check(doc_coverage.State(root))
    except (OSError, ValueError, KeyError) as err:
        return [f"QG8 documentation check failed: {err}"]
    return [f"QG8 {p}" for p in problems]


def check_vulns(root: Path, conf: dict) -> list[str]:
    sc = conf["supply_chain"]
    apps = sc["deploy_apps"] or None
    if not (sc["python"] or sc["npm"]):
        return []
    try:
        problems, _ = supply_chain.check_vulns(apps, root=root)
    except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as err:
        # Could not measure: a failure, not "no vulnerabilities" (B10).
        return [f"vulnerability scanner failed: {err}"]
    return problems


def run(root: Path = ROOT, branch: str | None = None, tools: bool = True) -> list[str]:
    conf = harness_config.load(root)
    branch = branch or os.environ.get("DEPLOY_BRANCH") or conf["deploy_branch"]
    generated = tuple(conf["generated"])
    base = deploy_base(root, conf["deployed_ref"])
    problems = (check_worktree(root, branch) + check_clean(root, generated)
                + check_build(root, conf["build_stamp"]) + check_lineage(root, base)
                + contract_check.check(root, base) + check_docs(root, conf["docs"]["enabled"]))
    if tools:
        problems += commit_scan.run(base, root) + check_vulns(root, conf)
    return problems


def report(output: str) -> dict:
    """A stop report for the deploy journal, from the preflight output, in the shape of
    the deploy check report. Scanner findings carry the place, never the value."""
    reasons = [line[len("preflight: "):] for line in output.splitlines()
               if line.startswith("preflight: ")]
    return {"agent": "preflight", "gate": "QG2", "verdict": "blocked",
            "reasons": reasons or ["preflight did not pass"]}


def main() -> int:
    if "--report" in sys.argv:
        print(json.dumps(report(sys.stdin.read()), ensure_ascii=False))
        return 0
    problems = run()
    for p in problems:
        print(f"preflight: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
