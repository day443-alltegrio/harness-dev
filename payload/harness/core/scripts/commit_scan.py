#!/usr/bin/env python3
"""QG2: scanner of the lines a change adds, before a deploy (harness/core/docs/design.md).

In the added lines of base..HEAD (default HEAD~1..HEAD) it looks for:
  secrets - private keys, GitHub, Atlassian, Slack, AWS tokens, JWTs and string
            literals next to password/token/secret/api_key;
  ids     - project identifiers from scan.id_patterns (customer, record or
            document numbers that must never land in git);
  names   - personal names from the built-in detectors in scan.name_detectors.
On top of that, when enabled in harness.json:
  shell   - shellcheck (error level) on changed *.sh;
  bandit  - HIGH findings fail; MEDIUM may not exceed harness/config/bandit-baseline.json.
A line with the "scan: ignore" mark is skipped (only on purpose, with the reason next to
it). Generated files, lock files and binaries are not scanned. A finding names the
place and the kind, never the value: the value may itself be personal data.

    python3 harness/core/scripts/commit_scan.py [base]
    python3 harness/core/scripts/commit_scan.py --history   # secrets in the whole git history
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT

SECRETS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("Atlassian token", re.compile(r"\bATATT[A-Za-z0-9_\-=]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("password or token in a literal", re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key)\w*\s*[=:]\s*[\"']"
        r"(?!changeme|example|xxx|\.\.\.|/)([^\"'\s$<{]{8,})[\"']")),
]
LITERAL = "password or token in a literal"

_CYR, _cyr = "А-ЯІЇЄҐ", "а-яіїєґʼ'’-"
NAME_DETECTORS = {
    "uk_full_name": [
        re.compile(rf"\b[{_CYR}][{_cyr}]+\s+[{_CYR}][{_cyr}]+\s+[{_CYR}][{_cyr}]*"
                   rf"(?:ович|евич|йович|івна|ївна|овна|евна|ична|інична)\b"),
        re.compile(rf"\b[{_CYR}][{_cyr}]{{2,}}\s+[{_CYR}]\.\s?[{_CYR}][{_cyr}]?\."),
    ],
}


class Scanner:
    def __init__(self, root: Path = ROOT):
        conf = harness_config.load(root)
        self.conf = conf["scan"]
        self.generated = tuple(conf["generated"])
        self.ids = [(p["name"], re.compile(p["regex"])) for p in self.conf["id_patterns"]]
        self.names = [rx for d in self.conf["name_detectors"] for rx in NAME_DETECTORS[d]]

    def scannable(self, path: str) -> bool:
        skip = tuple(self.conf["skip_prefixes"]) + self.generated
        return not path.startswith(skip) and not path.endswith(tuple(self.conf["skip_suffixes"]))

    def in_tests(self, path: str) -> bool:
        p = "/" + path
        return any(d in p for d in self.conf["test_dirs"])

    def secrets(self, path: str, text: str) -> list[str]:
        return [kind for kind, rx in SECRETS
                if rx.search(text) and not (kind == LITERAL and self.in_tests(path))]

    def scan_lines(self, lines: list[tuple[str, int, str]]) -> list[str]:
        """Findings without the values: the place and the kind."""
        found = []
        for path, n, text in lines:
            if not self.scannable(path) or self.conf["ignore_mark"] in text:
                continue
            where = f"{path}:{n}"
            for name, rx in self.ids:
                if rx.search(text):
                    found.append(f"{where}: {name}")
            if any(rx.search(text) for rx in self.names):
                found.append(f"{where}: looks like a personal name")
            found += [f"{where}: {kind}" for kind in self.secrets(path, text)]
        return found


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          errors="replace").stdout


def added_lines(base: str, root: Path = ROOT) -> list[tuple[str, int, str]]:
    """(file, line number in the new version, text) of every added line."""
    out, path, line = [], None, 0
    for raw in git("diff", "--unified=0", "--no-color", f"{base}..HEAD", root=root).splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            out.append((path, line, raw[1:]))
            line += 1
    return out


def changed_files(base: str, root: Path = ROOT) -> list[str]:
    return [f for f in git("diff", "--name-only", "--diff-filter=AM", f"{base}..HEAD",
                           root=root).split() if f]


def shellcheck(files: list[str], root: Path = ROOT) -> list[str]:
    scripts = [f for f in files if f.endswith(".sh") and (root / f).is_file()]
    if not scripts:
        return []
    try:
        r = subprocess.run(["uvx", "--from", "shellcheck-py", "shellcheck", "-S", "error",
                            "-f", "gcc", *scripts], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return ["shellcheck could not run: uvx is not installed"]
    if r.returncode not in (0, 1):
        return [f"shellcheck failed: {r.stderr.strip()[:200]}"]
    return [f"shellcheck: {line}" for line in r.stdout.splitlines() if line.strip()]


def bandit(conf: dict, root: Path = ROOT) -> list[str]:
    try:
        r = subprocess.run(["uvx", "bandit", "-q", "-r", *conf["paths"], "-ll", "-f", "json"],
                           cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return ["bandit could not run: uvx is not installed"]
    try:
        results = json.loads(r.stdout)["results"]
    except (ValueError, KeyError):
        # A scanner that did not answer is a failure, not "no findings".
        return [f"bandit failed: {r.stderr.strip()[:200]}"]
    problems = [f"bandit {x['test_id']} {x['filename']}:{x['line_number']}: {x['issue_text'][:80]}"
                for x in results if x["issue_severity"] == "HIGH"]
    base = harness_config.read_json(root / conf["baseline"], {}).get("medium", {})
    medium = Counter(x["test_id"] for x in results if x["issue_severity"] == "MEDIUM")
    for test_id, n in sorted(medium.items()):
        if n > base.get(test_id, 0):
            problems.append(f"bandit {test_id}: {n} medium, baseline {base.get(test_id, 0)}")
    return problems


def history_secrets(root: Path = ROOT) -> list[str]:
    """Secrets in the whole git history (the kind and the commit, never the value)."""
    sc = Scanner(root)
    found, commit, path = [], "", ""
    for raw in git("log", "--all", "-p", "--no-color", "--format=COMMIT %h", root=root).splitlines():
        if raw.startswith("COMMIT "):
            commit = raw[7:]
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else ""
        elif (raw.startswith("+") and path and sc.scannable(path)
              and sc.conf["ignore_mark"] not in raw
              and len(raw) < 2000):  # a line of thousands of characters is minified code
            found += [f"{commit}: {kind}" for kind in sc.secrets(path, raw)]
    return sorted(set(found))


def run(base: str = "HEAD~1", root: Path = ROOT, tools: bool = True) -> list[str]:
    if not git("rev-parse", "--verify", "--quiet", base, root=root).strip():
        return []
    sc = Scanner(root)
    problems = sc.scan_lines(added_lines(base, root))
    if tools:
        if sc.conf["shellcheck"]:
            problems += shellcheck(changed_files(base, root), root)
        if sc.conf["bandit"]:
            problems += bandit(sc.conf["bandit"], root)
    return problems


def main(argv: list[str]) -> int:
    if "--history" in argv:
        problems = history_secrets()
    else:
        problems = run(argv[0] if argv else "HEAD~1")
    for p in problems:
        print(f"scan: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
