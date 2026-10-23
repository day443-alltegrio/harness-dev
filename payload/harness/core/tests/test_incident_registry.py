"""The failure coverage registry cannot lie: every pattern is listed with the catalog's own
title, every named test exists, "covered" never comes without a test."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "harness/core/docs/failure-patterns.md"
PROJECT = ROOT / "harness/project/incidents.md"
REGISTRY_PATH = ROOT / "harness/config/incident-coverage.json"
TEST_DIRS = [ROOT / "harness/core/tests", ROOT / "harness/project/tests"]
STATUSES = {"covered", "partial", "none"}


def table_titles(path: Path) -> dict[str, str]:
    """{id: title} from the pattern tables of a Markdown file."""
    if not path.is_file():
        return {}
    return dict(re.findall(r"^\| ((?:[AB]|P)\d+) \| ([^|]+?) \|", path.read_text(encoding="utf-8"), re.M))


def test_exists(dotted: str) -> bool:
    module, cls, name = dotted.split(".")
    for d in TEST_DIRS:
        f = d / f"{module}.py"
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            if f"class {cls}(" in text and f"def {name}(" in text:
                return True
    return False


@unittest.skipUnless(REGISTRY_PATH.is_file(), "no harness/config/incident-coverage.json yet")
class Registry(unittest.TestCase):
    def setUp(self):
        self.reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["patterns"]
        self.generic = table_titles(CATALOG)
        self.project = table_titles(PROJECT)

    def test_every_generic_pattern_is_tracked(self):
        self.assertTrue(self.generic, "the catalog has no patterns")
        self.assertEqual(set(self.generic) - set(self.reg), set())

    def test_every_entry_is_a_known_pattern(self):
        unknown = set(self.reg) - set(self.generic) - set(self.project)
        self.assertEqual(unknown, set(), "define project patterns in harness/project/incidents.md")

    def test_titles_match_the_catalogs(self):
        for pid, p in self.reg.items():
            want = self.generic.get(pid) or self.project.get(pid)
            self.assertEqual(p["title"], want, pid)

    def test_statuses_and_named_tests(self):
        for pid, p in self.reg.items():
            self.assertIn(p["status"], STATUSES, pid)
            tests = [t for c in p["checks"] for t in c["tests"]]
            for t in tests:
                self.assertTrue(test_exists(t), f"{pid}: no test {t}")
            if p["status"] == "covered":
                self.assertTrue(tests, pid)
                self.assertNotIn("missing", p, pid)
            if p["status"] == "none":
                self.assertFalse(p["checks"], pid)


if __name__ == "__main__":
    unittest.main()
