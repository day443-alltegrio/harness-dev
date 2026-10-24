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


WIRED = {"hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python3 .claude/hooks/harness/guard.py || exit 2"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python3 .claude/hooks/harness/stop_check.py"}]}],
    "ConfigChange": [{"hooks": [{"type": "command",
                                 "command": "python3 .claude/hooks/harness/config_guard.py || exit 2"}]}]}}


class Data(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "harness" / "config").mkdir(parents=True)
        self.state = self.root / "harness" / ".state"
        self.patches = [mock.patch.object(gates, "ROOT", self.root), mock.patch.object(gates, "STATE", self.state)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def checks(self, ids: list[str]) -> None:
        (self.root / "harness" / "config" / "data-checks.json").write_text(json.dumps({"checks": [
            {"id": i, "pattern": "B8", "cmd": "echo 1", "expect": {"min": 1}} for i in ids]}))

    def report(self, checks: list[dict]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        passed = sum(c["state"] == "pass" for c in checks)
        (self.state / "data-checks.json").write_text(json.dumps({"checks": checks, "summary": {
            "total": len(checks), "passed": passed}}))

    def test_states(self):
        self.checks([])
        self.assertEqual(gates.data({})[0], "fail")  # nothing configured is not a pass
        self.checks(["rows", "fresh"])
        self.assertEqual(gates.data({})[0], "unknown")  # never run
        self.report([{"id": "rows", "state": "pass", "detail": ""}])
        self.assertEqual(gates.data({})[0], "warn")  # fresh was never run
        self.report([{"id": "rows", "state": "pass", "detail": ""},
                     {"id": "fresh", "state": "fail", "detail": "0 < min 1"}])
        state, detail = gates.data({})
        self.assertEqual((state, "fresh 0 < min 1" in detail), ("fail", True))
        self.report([{"id": "rows", "state": "pass", "detail": ""}, {"id": "fresh", "state": "pass", "detail": ""}])
        self.assertEqual(gates.data({}), ("pass", "2/2 data checks passed"))


class HookLog(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.log_dir = Path(tempfile.mkdtemp())
        (self.root / ".claude").mkdir()
        self.settings(WIRED)
        home = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(gates, "ROOT", self.root),
                        mock.patch.object(gates.harness_config, "HOOK_LOG", self.log_dir),
                        mock.patch.object(gates.Path, "home", return_value=home)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def settings(self, data: dict, name: str = "settings.json") -> None:
        (self.root / ".claude" / name).write_text(json.dumps(data))

    def write_log(self, recs: list[dict]) -> None:
        (self.log_dir / f"{time.strftime('%Y-%m-%d')}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in recs))

    def test_counts_decisions_and_unknown_without_log(self):
        self.assertEqual(gates.hook_log({})[0], "unknown")
        self.write_log([{"decision": "deny", "rule": "secrets-read"}, {"decision": "ask", "rule": "deploy"}])
        state, detail = gates.hook_log({})
        self.assertEqual(state, "pass")
        self.assertIn("1 blocked, 1 asked", detail)
        self.assertIn("0 of 2 marked false", detail)

    def test_hooks_not_wired_or_switched_off_fail(self):
        self.write_log([{"decision": "deny", "rule": "secrets-read"}])
        self.settings({"hooks": {}})
        state, detail = gates.hook_log({})
        self.assertEqual(state, "fail")
        self.assertIn("guard.py", detail)
        self.settings(WIRED)
        self.settings({"disableAllHooks": True}, "settings.local.json")
        state, detail = gates.hook_log({})
        self.assertEqual(state, "fail")
        self.assertIn("disableAllHooks", detail)

    def test_sandbox_state_in_the_line_and_a_required_sandbox_off_fails(self):
        self.write_log([{"decision": "ask", "rule": "deploy"}])
        self.assertIn("sandbox off", gates.hook_log({})[1])
        cfg = self.root / "harness" / "config"
        cfg.mkdir(parents=True)
        (cfg / "sandbox.json").write_text(json.dumps({"enabled": True, "required": True}))
        state, detail = gates.hook_log({})
        self.assertEqual(state, "fail")
        self.assertIn("differs", detail)

    def test_rule_over_the_false_block_share_warns(self):
        self.write_log([{"decision": "deny", "rule": "secrets-read", "id": f"a{i:07d}"} for i in range(5)])
        marks = self.log_dir / "marks"
        marks.mkdir()
        (marks / "false-blocks.jsonl").write_text("".join(
            json.dumps({"id": f"a{i:07d}", "verdict": "false"}) + "\n" for i in range(2)))
        state, detail = gates.hook_log({})
        self.assertEqual(state, "warn")
        self.assertIn("secrets-read", detail)


if __name__ == "__main__":
    unittest.main()
