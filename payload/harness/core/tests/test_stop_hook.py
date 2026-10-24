"""Stop hook: changed files with broken syntax send the agent back, a bounded number of times."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

STOP = Path(__file__).resolve().parents[3] / ".claude" / "hooks" / "harness" / "stop_check.py"
spec = importlib.util.spec_from_file_location("stop_check", STOP)
stop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stop)

SYNTAX = Path(__file__).resolve().parents[1] / "scripts" / "syntax_check.py"
CONF = {"enabled": True, "max_blocks": 2, "timeout_s": 30,
        "checks": [{"name": "syntax", "glob": ["*.py"],
                    "cmd": f"{sys.executable} {SYNTAX} {{files}}"}]}


def repo() -> Path:
    root = Path(tempfile.mkdtemp())
    run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "t")
    (root / "ok.py").write_text("x = 1\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "init")
    return root


class Stop(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(stop, "HOOKS", Path(tempfile.mkdtemp()))
        self.p.start()
        self.root = repo()
        self.event = {"session_id": "s1", "transcript_path": "/nonexistent"}

    def tearDown(self):
        self.p.stop()

    def test_clean_change_passes(self):
        (self.root / "new.py").write_text("y = 2\n")
        self.assertIsNone(stop.handle(self.event, self.root, CONF))

    def test_broken_file_blocks_then_warns(self):
        (self.root / "bad.py").write_text("def x(:\n")
        first = stop.handle(self.event, self.root, CONF)
        self.assertEqual(first["decision"], "block")
        self.assertIn("syntax", first["reason"])
        self.assertIn("bad.py:1", first["reason"])
        # The id lets a human mark a wrong block (hook_review.py).
        self.assertRegex(first["reason"], r"^\[stop-check #[0-9a-f]{8}\] ")
        self.assertEqual(stop.handle(self.event, self.root, CONF)["decision"], "block")
        third = stop.handle(self.event, self.root, CONF)
        self.assertNotIn("decision", third)
        self.assertIn("still fail", third["systemMessage"])

    def test_fixed_file_resets(self):
        (self.root / "bad.py").write_text("def x(:\n")
        self.assertEqual(stop.handle(self.event, self.root, CONF)["decision"], "block")
        (self.root / "bad.py").write_text("def x():\n    return 1\n")
        self.assertIsNone(stop.handle(self.event, self.root, CONF))

    def test_files_older_than_the_last_clean_check_are_skipped(self):
        bad = self.root / "old.py"
        bad.write_text("def x(:\n")
        past = time.time() - 600
        os.utime(bad, (past, past))
        sp = stop.state_path("s1")
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"since": time.time() - 60, "blocks": 0}))
        self.assertIsNone(stop.handle(self.event, self.root, CONF))

    def test_disabled(self):
        (self.root / "bad.py").write_text("def x(:\n")
        self.assertIsNone(stop.handle(self.event, self.root, {**CONF, "enabled": False}))

    def test_project_config_loads(self):
        conf = stop.load_conf()
        self.assertIn("checks", conf)
        for check in conf["checks"]:
            self.assertTrue({"name", "glob", "cmd"} <= set(check), check)


if __name__ == "__main__":
    unittest.main()
