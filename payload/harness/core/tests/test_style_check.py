"""Style check: banned characters are violations, uniformity is a suspicion, marked lines skip."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import style_check as sc  # noqa: E402

EM, ARROW = "—", "→"


def conf() -> dict:
    p = Path(tempfile.mkdtemp()) / "style.json"
    p.write_text(json.dumps({
        "banned": {EM: "em dash", ARROW: "arrow"},
        "cliches": {"en": ["\\bleverag(?:e|es|ing)\\b"], "uk": [["\\bз метою\\b", "з метою"]]},
        "triad_words": {"en": "\\bthree\\b"},
        "bold_lead_share": 0.45, "triads_per_kb": 1.2}))
    return sc.load(p)


class Style(unittest.TestCase):
    def setUp(self):
        self.conf = conf()

    def test_banned_character_is_a_violation(self):
        v, _ = sc.check_text(f"One line {EM} with a dash.\n", self.conf)
        self.assertEqual(len(v), 1)
        self.assertIn("first on line 1", v[0])

    def test_marked_line_and_code_block_skip(self):
        text = (f"Use -> instead of {ARROW}. <!-- style-check: ignore -->\n\n"
                f"```\nprint('{EM}')\n```\n")
        self.assertEqual(sc.check_text(text, self.conf), ([], []))

    def test_cliches_in_both_languages(self):
        _, s = sc.check_text("We leverage the cache з метою speed.\n", self.conf)
        self.assertEqual(len(s), 2)

    def test_bold_leads_and_triads_are_suspicions(self):
        para = "**Lead.** " + "word " * 40
        _, s = sc.check_text("\n\n".join([para] * 4), self.conf)
        self.assertTrue(any("bold lead" in x for x in s))
        _, s = sc.check_text("three " * 10, self.conf)
        self.assertTrue(any("triad" in x for x in s))

    def test_clean_text(self):
        self.assertEqual(sc.check_text("A plain paragraph written by a person.\n", self.conf), ([], []))

    def test_project_config_loads(self):
        loaded = sc.load()
        self.assertIn("banned", loaded)


if __name__ == "__main__":
    unittest.main()
