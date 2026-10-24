"""Shared settings of the harness checks: one project file, harness/config/harness.json.

Every key is optional; a missing key keeps the default below. Nested objects merge
key by key, lists replace the default as a whole.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import unittest
from pathlib import Path

# harness/core/scripts/harness_config.py -> the project root.
ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / "harness"
CORE = HARNESS / "core"          # kit-owned: replaced on upgrade, never edited here
CONFIG_DIR = HARNESS / "config"  # project-owned settings
PROJECT = HARNESS / "project"    # project-owned docs, contracts, tests
# Local evidence (last deploy report, snapshot, caches): outside git.
STATE = HARNESS / ".state"
HOOK_LOG = ROOT / ".claude" / "hooks" / "harness" / "log"

DEFAULTS: dict = {
    "project": "project",
    # Deploys go only from this branch of the main working copy.
    "deploy_branch": "main",
    # Set by the deploy after a success; the next deploy must descend from it.
    "deployed_ref": "refs/harness/deployed",
    # Path prefixes the build or the deploy rewrites (committed by the next commit):
    # they do not make the tree dirty and do not count toward the change size.
    "generated": [],
    # Optional build provenance: a JSON file whose key starts with the short HEAD of
    # the commit it was built from, with "+" right after the hash for a dirty tree.
    # Example: {"file": "web/dist/version.json", "key": "version"}.
    "build_stamp": None,
    # Evidence older than this shows as stale ("warn"), never as a plain pass.
    "stale_hours": 36,
    # IANA zone for daily agent metrics; None means the local time of the machine.
    "timezone": None,
    "contracts": {
        "dir": "harness/project/contracts/",
        "max_files": 30,
        # A change touching any of these (regex on the repo path) needs a contract.
        "risky": [
            {"match": r"^(migrations|db/migrations|sql)/", "label": "database schema"},
            {"match": r"^(infra/)?deploy/[^/]+$", "label": "deploy scripts"},
            {"match": r"^harness/config/deploy-hooks\.sh$", "label": "deploy scripts"},
            {"match": r"^\.claude/(settings\.json|harness-hooks\.json)$", "label": "agent boundaries"},
        ],
        "sections": ["## Goal", "## Non-goals", "## Acceptance criteria", "## Boundaries",
                     "## Risks and rollback", "## Related failures"],
        # Acceptance criteria name their checks in backticks; named tests and
        # regression cases must exist, and a done contract names at least one check.
        "checkable": True,
    },
    "scan": {
        "skip_prefixes": ["node_modules/", "dist/", "build/", "vendor/", ".venv/"],
        "skip_suffixes": [".lock", ".lock.txt", "package-lock.json", "yarn.lock",
                          "pnpm-lock.yaml", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".pdf",
                          ".docx", ".xlsx", ".zip", ".drawio"],
        "ignore_mark": "scan: ignore",
        # Password literals inside these paths are test fixtures; keys and tokens are not.
        "test_dirs": ["/tests/", "/test/", "/__tests__/"],
        # Project identifiers that must never land in git, e.g. customer or record IDs:
        # [{"name": "record id", "regex": "(?<![\\w.,:/#-])\\d{7}(?![\\w.,:/-])"}].
        "id_patterns": [],
        # Built-in personal name detectors: "uk_full_name" (Cyrillic name with a
        # patronymic, or a surname with initials).
        "name_detectors": [],
        # shellcheck (error level) on changed *.sh; needs uvx (shellcheck-py).
        "shellcheck": False,
        # bandit on these paths: HIGH fails, MEDIUM may not exceed the baseline file.
        # Example: {"paths": ["src"], "baseline": "harness/config/bandit-baseline.json"}.
        "bandit": None,
    },
    "supply_chain": {
        # [{"app": "api", "requirements": "api/requirements.txt",
        #   "lock": "api/requirements.lock.txt"}]
        "python": [],
        # Folders with package.json scanned by npm audit, e.g. ["web"].
        "npm": [],
        # Apps whose vulnerabilities block a deploy in preflight; empty means all.
        "deploy_apps": [],
    },
    # QG8: scenarios of people tied to code (doc_coverage.py, scenarios-map.json).
    "docs": {"enabled": False},
    "deploy_check": {
        # A command that prints the OpenAPI JSON of the code in the current folder;
        # {python} is the interpreter running deploy_check. None skips the contract.
        "openapi_cmd": None,
        # Added to PYTHONPATH (relative to the code root) for openapi_cmd and tests.
        "pythonpath": ["src"],
        "tests_glob": "tests/test_*.py",
        "test_cmd": "{python} {file}",
        # Variables that switch tests to a live database or service: removed.
        "env_drop": [],
        # Test files that must exist and pass; reported separately.
        "security_tests": [],
        "timeout_s": 300,
        # Replay the "before" regression cases (regressions.py) on the new code.
        "regressions": True,
    },
    # QG6: data invariants (data_checks.py). Each check is a project command that
    # prints a number or a JSON object of numbers, compared with a fixed rule.
    "data_checks": {
        "file": "harness/config/data-checks.json",
        # Per command, unless the check sets its own timeout_s.
        "timeout_s": 600,
        # Lines kept in harness/.state/data-history.jsonl (baseline for drop_max).
        "history_keep": 2000,
    },
    # Hook decisions marked as false blocks by people (hook_review.py): a rule over
    # the share of its decisions in the window, with at least min decisions, is
    # reviewed (design.md, section 10).
    "hooks": {"false_block_share": 0.2, "false_block_min": 5, "window_days": 30},
    # The operating system sandbox of Claude Code (sandbox_config.py).
    "sandbox": {"file": "harness/config/sandbox.json"},
    # Golden tasks run by the real agent (golden_tasks.py): the claude CLI, its model
    # (None: the CLI default), the budget per task and what the agent may use.
    "golden": {"file": "harness/config/golden-tasks.json", "claude": "claude", "model": None,
               "max_turns": 12, "timeout_s": 900, "permission_mode": "acceptEdits",
               "allowed_tools": "Bash,Read,Edit,Write,Grep,Glob"},
    # Replay of closed tickets whose result a human confirmed (regressions.py).
    "regressions": {
        "dir": "harness/project/regressions/",
        "timeout_s": 300,
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(root: Path = ROOT) -> dict:
    """Project settings over the defaults."""
    path = root / "harness" / "config" / "harness.json"
    over = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return _merge(DEFAULTS, over)


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def test_dirs(root: Path = ROOT) -> list[Path]:
    """Kit tests and the project's own harness tests (name them test_project_*.py so
    module names never clash with the kit's)."""
    return [d for d in (root / "harness" / "core" / "tests", root / "harness" / "project" / "tests")
            if d.is_dir()]


def run_tests(root: Path = ROOT) -> tuple[int, int]:
    """Run every harness test quietly: (tests run, failures and errors)."""
    run = bad = 0
    for d in test_dirs(root):
        suite = unittest.defaultTestLoader.discover(str(d), top_level_dir=str(d))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        run += res.testsRun
        bad += len(res.failures) + len(res.errors)
    return run, bad
