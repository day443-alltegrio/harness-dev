"""QG8 documentation coverage on temporary repositories: map, anchors, orphans, drift, decisions."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import doc_coverage as dcov  # noqa: E402

DOC = """# Scenarios

## SC-01 Sign in

The user signs in with a password.

## SC-02 Nightly import

Runs at night.
"""
MAP = {
    "doc": "docs/scenarios.md",
    "scenarios": {
        "SC-01": {"actor": "user", "files": ["src/auth.py"], "tests": ["tests/test_auth.py::test_sign_in"]},
        "SC-02": {"actor": "system", "files": ["src/importer.py"], "tests": []},
    },
    "watch": ["src/*.py"],
    "service": {"src/health.py": "liveness probe"},
}


def repo(map_: dict = MAP, extra: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    files = {
        "docs/scenarios.md": DOC,
        "src/auth.py": "def sign_in():\n    return True\n",
        "src/importer.py": "def run():\n    pass\n",
        "src/health.py": "def ok():\n    return 1\n",
        "tests/test_auth.py": "def test_sign_in():\n    assert True\n",
        "harness/config/scenarios-map.json": json.dumps(map_),
        **(extra or {}),
    }
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "t")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "init")
    return root


def problems(root: Path, today: str | None = None) -> list[str]:
    return dcov.check(dcov.State(root), today)


class Coverage(unittest.TestCase):
    def test_new_scenario_is_not_reviewed_yet(self):
        self.assertTrue(any("SC-01: not reviewed yet" in p for p in problems(repo())))

    def test_accept_then_clean(self):
        root = repo()
        self.assertEqual(dcov.accept(dcov.State(root), ["SC-01"], "none"), [])
        self.assertEqual(problems(root), [])

    def test_code_change_is_drift(self):
        root = repo()
        dcov.accept(dcov.State(root), ["SC-01"], "none")
        (root / "src/auth.py").write_text("def sign_in():\n    return False\n")
        self.assertTrue(any("the code changed, the scenario text did not" in p for p in problems(root)))

    def test_comment_change_is_not_drift(self):
        root = repo()
        dcov.accept(dcov.State(root), ["SC-01"], "none")
        (root / "src/auth.py").write_text("# note\ndef sign_in():\n    return True\n")
        self.assertEqual(problems(root), [])

    def test_fix_doc_requires_a_text_change(self):
        root = repo()
        dcov.accept(dcov.State(root), ["SC-01"], "none")
        (root / "src/auth.py").write_text("def sign_in():\n    return False\n")
        errors = dcov.accept(dcov.State(root), ["SC-01"], "fix_doc")
        self.assertTrue(any("text has not changed" in e for e in errors))

    def test_map_and_document_must_agree(self):
        root = repo(extra={"docs/scenarios.md": DOC + "\n## SC-03 Export\n\nCSV.\n"})
        self.assertTrue(any("SC-03 is in docs/scenarios.md but not in the map" in p for p in problems(root)))

    def test_missing_anchor_and_test(self):
        m = json.loads(json.dumps(MAP))
        m["scenarios"]["SC-01"]["files"].append("src/gone.py")
        m["scenarios"]["SC-01"]["tests"].append("tests/test_auth.py::test_missing")
        found = problems(repo(m))
        self.assertTrue(any("no file matches src/gone.py" in p for p in found))
        self.assertTrue(any("no test tests/test_auth.py::test_missing" in p for p in found))

    def test_orphan_file_fails_and_service_does_not(self):
        root = repo(extra={"src/export.py": "def csv():\n    pass\n"})
        found = problems(root)
        self.assertTrue(any(p.startswith("src/export.py belongs to no scenario") for p in found))
        self.assertFalse(any("src/health.py" in p for p in found))

    def test_people_scenario_needs_a_test(self):
        m = json.loads(json.dumps(MAP))
        m["scenarios"]["SC-01"]["tests"] = []
        self.assertTrue(any("SC-01: scenario without a test" in p for p in problems(repo(m))))

    def test_defer_limits(self):
        root = repo()
        today = dt.date.today()
        far = (today + dt.timedelta(days=120)).isoformat()
        errors = dcov.accept(dcov.State(root), ["SC-01"], "defer", reason="r", claim="c", until=far)
        self.assertTrue(any("within 90 days" in e for e in errors))
        near = (today + dt.timedelta(days=30)).isoformat()
        self.assertEqual(dcov.accept(dcov.State(root), ["SC-01"], "defer", reason="r", claim="c",
                                     until=near), [])
        later = (today + dt.timedelta(days=31)).isoformat()
        self.assertTrue(any("has expired" in p for p in problems(root, later)))

    def test_summary_counts(self):
        root = repo()
        dcov.accept(dcov.State(root), ["SC-01"], "none")
        s = dcov.summary(dcov.State(root))
        self.assertEqual((s["people"], s["in_sync"], s["with_tests"]), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
