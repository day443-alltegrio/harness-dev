"""The installed harness is wired: hooks in settings, imports in CLAUDE.md, versions agree."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "harness" / "harness.lock.json"


@unittest.skipUnless(LOCK.is_file(), "not installed by harness.py (no harness/harness.lock.json)")
class Integrity(unittest.TestCase):
    def test_versions_agree(self):
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertEqual((ROOT / "harness/core/VERSION").read_text().strip(), lock["version"])

    def test_settings_wire_the_hooks_and_deny_rules(self):
        settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        frag = json.loads((ROOT / "harness/core/settings.fragment.json").read_text(encoding="utf-8"))
        commands = [h.get("command", "") for entries in settings.get("hooks", {}).values()
                    for e in entries for h in e.get("hooks", [])]
        for script in ("guard.py", "stop_check.py"):
            self.assertTrue(any(f".claude/hooks/harness/{script}" in c for c in commands), script)
        guard = next(c for c in commands if "guard.py" in c)
        self.assertTrue(guard.rstrip().endswith("|| exit 2"), "a failing guard must block")
        for rule in frag["permissions"]["deny"]:
            self.assertIn(rule, settings["permissions"]["deny"])

    def test_claude_md_imports_the_rules(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        block = re.search(r"<!-- harness:begin.*?<!-- harness:end -->", text, re.S)
        self.assertIsNotNone(block, "no harness block in CLAUDE.md")
        self.assertIn("@harness/core/rules.md", block.group(0))
        self.assertIn("@harness/project/rules.md", block.group(0))
        self.assertTrue((ROOT / "harness/project/rules.md").is_file())


if __name__ == "__main__":
    unittest.main()
