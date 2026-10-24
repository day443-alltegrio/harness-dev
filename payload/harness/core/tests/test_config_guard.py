"""ConfigChange hook: a settings change that weakens the harness is blocked mid-session."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KIT_ROOT = Path(__file__).resolve().parents[3]
HOOK = KIT_ROOT / ".claude" / "hooks" / "harness" / "config_guard.py"
spec = importlib.util.spec_from_file_location("config_guard", HOOK)
cg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cg)

FRAGMENT = KIT_ROOT / "harness" / "core" / "settings.fragment.json"


class ConfigGuard(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        (self.root / "harness" / "core").mkdir(parents=True)
        shutil.copy(FRAGMENT, self.root / "harness" / "core" / "settings.fragment.json")
        frag = json.loads(FRAGMENT.read_text())
        self.good = {"permissions": {"deny": list(frag["permissions"]["deny"])}, "hooks": frag["hooks"]}
        (self.root / ".claude").mkdir()
        self.write(self.good)
        self.p = mock.patch.object(cg, "HOOKS", Path(tempfile.mkdtemp()))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def write(self, data: dict, name: str = "settings.json") -> None:
        (self.root / ".claude" / name).write_text(json.dumps(data))

    def change(self, source: str = "project_settings", file_path: str | None = None):
        return cg.handle({"hook_event_name": "ConfigChange", "source": source, "session_id": "s",
                          "file_path": file_path}, self.root, self.home)

    def test_a_harmless_change_passes(self):
        self.write({**self.good, "permissions": {**self.good["permissions"], "allow": ["Bash(npm test)"]}})
        self.assertIsNone(self.change())

    def test_switching_hooks_off_is_blocked_at_any_level(self):
        self.write({"disableAllHooks": True}, "settings.local.json")
        out = self.change("local_settings")
        self.assertEqual(out["decision"], "block")
        self.assertIn("disableAllHooks in local_settings", out["reason"])
        (self.root / ".claude" / "settings.local.json").unlink()
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"disableAllHooks": True}))
        self.assertIn("user_settings", self.change("user_settings")["reason"])

    def test_removed_hook_narrowed_guard_and_removed_deny_rule_are_blocked(self):
        hooks = json.loads(json.dumps(self.good["hooks"]))
        del hooks["Stop"]
        self.write({**self.good, "hooks": hooks})
        self.assertIn("stop_check.py is no longer wired", self.change()["reason"])
        hooks = json.loads(json.dumps(self.good["hooks"]))
        hooks["PreToolUse"][0]["matcher"] = "Bash"
        self.write({**self.good, "hooks": hooks})
        self.assertIn("no longer sees", self.change()["reason"])
        self.write({**self.good, "permissions": {"deny": []}})
        self.assertIn("deny rules for secret files removed", self.change()["reason"])

    def test_required_sandbox_cannot_be_switched_off(self):
        (self.root / "harness" / "config").mkdir()
        (self.root / "harness" / "config" / "sandbox.json").write_text(json.dumps({"required": True}))
        self.write({**self.good, "sandbox": {"enabled": True, "allowUnsandboxedCommands": False}})
        self.assertIsNone(self.change())
        self.write({"sandbox": {"enabled": False}}, "settings.local.json")
        self.assertIn("the sandbox is off", self.change("local_settings")["reason"])
        self.write({"sandbox": {"allowUnsandboxedCommands": True}}, "settings.local.json")
        self.assertIn("outside it", self.change("local_settings")["reason"])

    def test_kit_skill_change_is_blocked_and_a_project_skill_passes(self):
        out = self.change("skills", str(self.root / ".claude/skills/harness-setup/SKILL.md"))
        self.assertIn("kit-owned skill", out["reason"])
        self.assertIsNone(self.change("skills", str(self.root / ".claude/skills/release-notes/SKILL.md")))

    def test_broken_json_is_blocked(self):
        (self.root / ".claude" / "settings.local.json").write_text("{not json")
        self.assertIn("not valid JSON", self.change("local_settings")["reason"])

    def test_managed_settings_are_logged_not_blocked(self):
        self.write({"disableAllHooks": True}, "settings.local.json")
        self.assertIsNone(self.change("policy_settings"))
        log = next((cg.HOOKS / "log").glob("*.jsonl")).read_text()
        self.assertIn('"decision": "logged"', log)

    def test_block_is_logged_with_its_id(self):
        self.write({"disableAllHooks": True})
        out = self.change()
        did = out["reason"][len("[config-change #"):][:8]
        rec = json.loads(next((cg.HOOKS / "log").glob("*.jsonl")).read_text().splitlines()[-1])
        self.assertEqual((rec["rule"], rec["decision"], rec["id"]), ("config-change", "block", did))

    def test_end_to_end_process(self):
        env = {**os.environ, "HARNESS_HOOKS_DIR": tempfile.mkdtemp()}
        r = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                           input=json.dumps({"hook_event_name": "ConfigChange", "source": "skills",
                                             "file_path": str(KIT_ROOT / ".claude/skills/x/SKILL.md")}))
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
