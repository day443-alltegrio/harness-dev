"""Context budget: imports are counted, going over is a failure."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_budget as cb  # noqa: E402

BUDGETS = {"budgets": [
    {"name": "always_loaded", "kind": "imports", "entry": "CLAUDE.md", "max_bytes": 100},
    {"name": "rules", "kind": "files", "files": ["docs/rules.md"], "max_bytes": 100},
    {"name": "skills", "kind": "skills", "dir": ".claude/skills", "max_bytes": 100, "max_bytes_each": 30},
    {"name": "memory", "kind": "memory", "dir": "/nonexistent/{slug}", "optional": True, "max_bytes": 10},
]}


def repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


class ContextBudget(unittest.TestCase):
    def test_imports_are_counted(self):
        root = repo({"CLAUDE.md": "root\n@harness/core/rules.md\n",
                     "harness/core/rules.md": "x" * 50, "docs/rules.md": "r"})
        row = cb.measure(root, BUDGETS)[0]
        self.assertEqual(row["bytes"], len("root\n@harness/core/rules.md\n") + 50)
        self.assertEqual(len(row["files"]), 2)

    def test_import_cycle_does_not_loop(self):
        root = repo({"CLAUDE.md": "@a.md\n", "a.md": "@CLAUDE.md\n"})
        self.assertEqual(len(cb.measure(root, BUDGETS)[0]["files"]), 2)

    def test_over_budget_fails(self):
        # Failure class "excess context": a root file with a heavy import.
        root = repo({"CLAUDE.md": "@big.md\n", "big.md": "x" * 500})
        self.assertFalse(cb.measure(root, BUDGETS)[0]["ok"])

    def test_long_skill_description_fails(self):
        desc = "---\nname: s\ndescription: >-\n  " + "word " * 20 + "\n---\nbody\n"
        root = repo({"CLAUDE.md": "", ".claude/skills/s/SKILL.md": desc})
        row = [r for r in cb.measure(root, BUDGETS) if r["name"] == "skills"][0]
        self.assertFalse(row["ok"])
        self.assertTrue(row["over_each"])

    def test_optional_memory_is_skipped(self):
        root = repo({"CLAUDE.md": "short\n"})
        self.assertNotIn("memory", [r["name"] for r in cb.measure(root, BUDGETS)])

    def test_clean_repo_passes(self):
        root = repo({"CLAUDE.md": "short\n", "docs/rules.md": "r",
                     ".claude/skills/s/SKILL.md": "---\nname: s\ndescription: short one\n---\n"})
        self.assertTrue(all(r["ok"] for r in cb.measure(root, BUDGETS)))

    def test_unknown_kind_is_an_error(self):
        with self.assertRaises(ValueError):
            cb.measure(repo({}), {"budgets": [{"name": "x", "kind": "nope", "max_bytes": 1}]})

    def test_project_budgets_file_is_valid(self):
        data = json.loads((cb.ROOT / "harness" / "config" / "budgets.json").read_text(encoding="utf-8"))
        for b in data["budgets"]:
            self.assertIn(b["kind"], ("imports", "files", "skills", "memory"), b)
            self.assertIn("max_bytes", b)


if __name__ == "__main__":
    unittest.main()
