#!/usr/bin/env python3
"""Task contract for big changes (QG2; harness/core/docs/design.md, practice "contract first").

A change needs a contract in harness/project/contracts/ when it touches a risky path
(contracts.risky in harness.json: schema, deploy scripts, data pipelines) or more
than contracts.max_files files. The contract is a contracts/*.md file added or
changed in the same change, with every section of TEMPLATE.md.

The acceptance criteria are where the agent and the human agree on what "done" means,
so they are checked too (contracts.checkable): every test name (test_...) and every
regression case (R-NNNN) they name in backticks must exist, and a contract in state
"done" names at least one check in backticks: a test, a command or a case.

    python3 harness/core/scripts/contract_check.py [base]    # default HEAD~1..HEAD
"""
from __future__ import annotations

import os
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


TEST_NAME = re.compile(r"\btest_\w+")
CASE_ID = re.compile(r"\bR-\d{3,}\b")
STATE_DONE = re.compile(r"^-\s*State:\s*done\b", re.M | re.I)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


def section(text: str, title: str) -> str:
    m = re.search(rf"^{re.escape(title)}[ \t]*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def word_exists(root: Path, word: str, exclude: str) -> bool:
    """The word appears in a file of the repository outside the contracts folder."""
    r = subprocess.run(["git", "grep", "-q", "-w", "--untracked", "-e", word, "--", ".",
                        f":(exclude){exclude}"], cwd=root, capture_output=True)
    if r.returncode in (0, 1):
        return r.returncode == 0
    for dirpath, dirnames, filenames in os.walk(root):  # not a git repository
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = Path(dirpath).relative_to(root).as_posix() + "/"
        if rel.startswith(exclude):
            continue
        for name in filenames:
            p = Path(dirpath) / name
            try:
                if p.stat().st_size < 2_000_000 and re.search(
                        rf"\b{re.escape(word)}\b", p.read_text(encoding="utf-8", errors="ignore")):
                    return True
            except OSError:
                continue
    return False


def criteria_problems(root: Path, rel: str, text: str, conf: dict) -> list[str]:
    """Checks the acceptance criteria name: they exist; a done contract names one."""
    crit = section(text, "## Acceptance criteria")
    quoted = re.findall(r"`([^`\n]+)`", crit)
    problems = []
    short = Path(rel).name
    for name in sorted({t for q in quoted for t in TEST_NAME.findall(q)}):
        if not word_exists(root, name, conf["contracts"]["dir"]):
            problems.append(f"contract {short}: {name} named in the acceptance criteria is nowhere in "
                            "the repository: write the test or fix the name")
    cases = root / conf["regressions"]["dir"]
    texts = [p.read_text(encoding="utf-8", errors="ignore") for p in cases.glob("*.json")]
    for cid in sorted({c for q in quoted for c in CASE_ID.findall(q)}):
        if not any(f'"{cid}"' in t for t in texts):
            problems.append(f"contract {short}: regression case {cid} named in the acceptance criteria "
                            f"is not in {conf['regressions']['dir']}")
    if STATE_DONE.search(text) and not quoted:
        problems.append(f"contract {short}: the change is done, but its acceptance criteria name no "
                        "check in backticks (a test, a command or a regression case)")
    return problems


def contract_problems(root: Path, files: list[str]) -> list[str]:
    """No contract, or a contract without the required sections."""
    c, _ = _conf(root)
    contracts = [f for f in files if f.startswith(c["dir"]) and f.endswith(".md")
                 and not f.endswith("TEMPLATE.md") and (root / f).is_file()]
    if not contracts:
        return ["no task contract in " + c["dir"]]
    problems = []
    conf = harness_config.load(root)
    for f in contracts:
        text = (root / f).read_text(encoding="utf-8")
        missing = [s for s in c["sections"] if s not in text]
        if missing:
            problems.append(f"{f}: missing sections {', '.join(missing)}")
        if c.get("checkable", True):
            problems += criteria_problems(root, f, text, conf)
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
    # A problem of the contract itself is named as such; the rest is a missing contract.
    return [p if p.startswith("contract ") else f"change needs a task contract ({'; '.join(why)}): {p}"
            for p in contract_problems(root, files)]


def main(argv: list[str]) -> int:
    problems = check(base=argv[0] if argv else "HEAD~1")
    for p in problems:
        print(f"contract: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
