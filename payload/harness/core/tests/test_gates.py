"""Gate table: states from gates.json, stale evidence is a warning, a broken check is an error."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gates  # noqa: E402


def conf_file(gates_conf: dict) -> Path:
    p = Path(tempfile.mkdtemp()) / "gates.json"
    p.write_text(json.dumps({"gates": gates_conf}))
    return p


class Rows(unittest.TestCase):
    def test_inactive_gates_show_their_reason(self):
        rows = gates.rows(conf_file({
            "QG4": {"name": "candidate", "state": "disabled", "reason": "trade-off: one service"},
            "QG6": {"name": "data", "state": "in_progress", "reason": "in progress: counters"}}))
        self.assertEqual(rows[0][2:], ("off", "trade-off: one service"))
        self.assertEqual(rows[1][2:], ("in progress", "in progress: counters"))

    def test_command_gate(self):
        rows = gates.rows(conf_file({
            "QG9": {"name": "lint", "state": "active", "command": "echo checking; echo 3 files ok"},
            "QG10": {"name": "types", "state": "active", "command": "echo 2 errors; exit 1"}}))
        self.assertEqual(rows[0][2:], ("pass", "3 files ok"))
        self.assertEqual(rows[1][2:], ("fail", "2 errors"))

    def test_active_gate_without_a_check_is_an_error(self):
        rows = gates.rows(conf_file({"QGX": {"name": "x", "state": "active"}}))
        self.assertEqual(rows[0][2], "error")

    def test_crashing_check_is_an_error_not_a_pass(self):
        with mock.patch.dict(gates.CHECKS, {"hook_log": mock.Mock(side_effect=OSError("disk"))}):
            rows = gates.rows(conf_file({"QG0": {"name": "guard", "state": "active", "check": "hook_log"}}))
        self.assertEqual(rows[0][2], "error")
        self.assertIn("disk", rows[0][3])


class Evidence(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(gates, "STATE", self.state)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def write(self, name: str, data: dict, age_h: float = 0) -> None:
        f = self.state / name
        f.write_text(json.dumps(data))
        t = time.time() - age_h * 3600
        os.utime(f, (t, t))

    def test_no_report_is_unknown(self):
        self.assertEqual(gates.deploy_report({})[0], "unknown")

    def test_fresh_pass_and_stale_warn(self):
        rep = {"verdict": "pass", "deploy_id": 7, "at": "2026-10-23 10:00",
               "tests": {"files": 5, "passed": 5}}
        self.write("deploy-last.json", rep)
        self.assertEqual(gates.deploy_report({})[0], "pass")
        self.write("deploy-last.json", rep, age_h=100)
        self.assertEqual(gates.deploy_report({})[0], "warn")

    def test_blocked_report_fails_with_reason(self):
        self.write("deploy-last.json", {"verdict": "blocked", "reasons": ["tests failed: test_a.py"]})
        state, detail = gates.deploy_report({})
        self.assertEqual(state, "fail")
        self.assertIn("test_a.py", detail)

    def test_snapshot_problems_fail(self):
        self.write("snapshot.json", {"problems": ["2 secrets in the git history"]})
        self.assertEqual(gates.snapshot({})[0], "fail")
        self.write("snapshot.json", {"problems": []}, age_h=100)
        self.assertEqual(gates.snapshot({})[0], "warn")


class HookLog(unittest.TestCase):
    def test_counts_decisions_and_unknown_without_log(self):
        log_dir = Path(tempfile.mkdtemp())
        with mock.patch.object(gates.harness_config, "HOOK_LOG", log_dir):
            self.assertEqual(gates.hook_log({})[0], "unknown")
            day = time.strftime("%Y-%m-%d")
            (log_dir / f"{day}.jsonl").write_text(
                json.dumps({"decision": "deny", "rule": "secrets-read"}) + "\n"
                + json.dumps({"decision": "ask", "rule": "deploy"}) + "\n")
            state, detail = gates.hook_log({})
        self.assertEqual(state, "pass")
        self.assertIn("1 blocked, 1 asked", detail)


if __name__ == "__main__":
    unittest.main()
