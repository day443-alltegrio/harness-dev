#!/usr/bin/env python3
"""Task contract for big changes (QG2; harness/core/docs/design.md, practice "contract first").

A change needs a contract in harness/project/contracts/ when it touches a risky path
(contracts.risky in harness.json: schema, deploy scripts, data pipelines) or more
than contracts.max_files files. The contract is a contracts/*.md file added or
changed in the same change, with every section of TEMPLATE.md.

    python3 harness/core/scripts/contract_check.py [base]    # default HEAD~1..HEAD
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT


def _conf(root: Path) -> tuple[dict, list[str]]:
    conf = harness_config.load(root)
    return conf["contracts"], conf["generated"]


def reasons(files: list[str], root: Path = ROOT) -> list[str]:
    """Why the change needs a contract; empty means it does not."""
    c, generated = _conf(root)
    gen = tuple(generated)
    own = [f for f in files if not (gen and f.startswith(gen)) and not f.startswith(c["dir"])]
    why = []
    for rule in c["risky"]:
        rx = re.compile(rule["match"])
        if any(rx.search(f) for f in own) and rule["label"] not in why:
            why.append(rule["label"])
    if len(own) > c["max_files"]:
        why.append(f"{len(own)} files (over {c['max_files']})")
    return why


def contract_problems(root: Path, files: list[str]) -> list[str]:
    """No contract, or a contract without the required sections."""
    c, _ = _conf(root)
    contracts = [f for f in files if f.startswith(c["dir"]) and f.endswith(".md")
                 and not f.endswith("TEMPLATE.md") and (root / f).is_file()]
    if not contracts:
        return ["no task contract in " + c["dir"]]
    problems = []
    for f in contracts:
        text = (root / f).read_text(encoding="utf-8")
        missing = [s for s in c["sections"] if s not in text]
        if missing:
            problems.append(f"{f}: missing sections {', '.join(missing)}")
    return problems


def changed(root: Path, base: str) -> list[str]:
    r = subprocess.run(["git", "diff", "--name-only", f"{base}..HEAD"], cwd=root,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []  # no base (first commit): nothing to compare with
    return [line for line in r.stdout.splitlines() if line]


def check(root: Path = ROOT, base: str = "HEAD~1") -> list[str]:
    files = changed(root, base)
    why = reasons(files, root)
    if not why:
        return []
    return [f"change needs a task contract ({'; '.join(why)}): {p}"
            for p in contract_problems(root, files)]


def main(argv: list[str]) -> int:
    problems = check(base=argv[0] if argv else "HEAD~1")
    for p in problems:
        print(f"contract: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
