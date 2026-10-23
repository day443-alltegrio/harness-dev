"""Syntax check: broken files fail with a line number, nothing is written next to them."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import syntax_check as sx  # noqa: E402


class Syntax(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name: str, text: str) -> Path:
        p = self.dir / name
        p.write_text(text)
        return p

    def test_broken_files(self):
        self.assertIn(":1:", sx.check(self.write("a.py", "def x(:\n")))
        self.assertIn(":1:", sx.check(self.write("a.json", "{nope}")))
        self.assertIsNotNone(sx.check(self.write("a.sh", "if then fi\n")))

    def test_good_files_and_unknown_types(self):
        for name, text in (("b.py", "x = 1\n"), ("b.json", "{}"), ("b.sh", "echo ok\n"),
                           ("b.yaml", "a: [")):
            self.assertIsNone(sx.check(self.write(name, text)), name)

    def test_writes_nothing(self):
        sx.main([str(self.write("c.py", "x = 1\n"))])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["c.py"])


if __name__ == "__main__":
    unittest.main()
