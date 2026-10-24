"""The hooks speak the protocol Claude Code documents, run the way Claude Code runs them.

The tests of each hook call its functions; these run the hook processes through the very
command lines .claude/settings.json holds and check every answer against the documented
shape, so a drift between the kit and Claude Code shows here first. What Claude Code then
does with the answer is measured by the integration golden tasks (golden_tasks.py).

Reference: code.claude.com/docs/en/hooks, checked with Claude Code CLI 2.1.308 on
2026-10-24 (the periodic review rechecks it).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FRAGMENT = ROOT / "harness" / "core" / "settings.fragment.json"
# Documented names this kit relies on.
EVENTS = {"PreToolUse", "Stop", "ConfigChange"}
TOOLS = {"Bash", "Read", "Grep", "Glob", "Edit", "MultiEdit", "Write", "NotebookEdit", "WebFetch"}
CONFIG_SOURCES = {"user_settings", "project_settings", "local_settings", "policy_settings", "skills"}
DECISIONS = {"allow", "deny", "ask", "defer"}
# Claude Code ends a run of Stop blocks after 8 in a row; the kit's own bound comes first.
STOP_CAP = 8


def command_of(event: str) -> str:
    frag = json.loads(FRAGMENT.read_text(encoding="utf-8"))
    return frag["hooks"][event][0]["hooks"][0]["command"]


def run_hook(event: str, payload, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), "HARNESS_HOOKS_DIR": tempfile.mkdtemp()}
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(["sh", "-c", command_of(event)], input=text, capture_output=True,
                          text=True, env=env, cwd=cwd or ROOT, timeout=60)


def common(event: str) -> dict:
    return {"session_id": "protocol", "transcript_path": "/nonexistent.jsonl", "cwd": str(ROOT),
            "hook_event_name": event, "permission_mode": "default"}


class Wiring(unittest.TestCase):
    def test_events_tools_and_timeouts_are_documented(self):
        frag = json.loads(FRAGMENT.read_text(encoding="utf-8"))
        self.assertLessEqual(set(frag["hooks"]), EVENTS)
        for event, entries in frag["hooks"].items():
            for e in entries:
                if event == "PreToolUse":
                    self.assertLessEqual(set(e["matcher"].split("|")), TOOLS, e["matcher"])
                if event == "ConfigChange" and "matcher" in e:
                    self.assertLessEqual(set(e["matcher"].split("|")), CONFIG_SOURCES)
                for h in e["hooks"]:
                    self.assertEqual(h["type"], "command")
                    self.assertIn("$CLAUDE_PROJECT_DIR", h["command"])
                    self.assertTrue(0 < h["timeout"] <= 600)

    def test_hooks_that_guard_fail_closed(self):
        for event in ("PreToolUse", "ConfigChange"):
            self.assertTrue(command_of(event).rstrip().endswith("|| exit 2"), event)
            r = run_hook(event, "not json")
            self.assertEqual(r.returncode, 2, f"{event}: a crashing hook must block")


class Answers(unittest.TestCase):
    def check_pretooluse(self, out: dict) -> None:
        self.assertEqual(set(out), {"hookSpecificOutput"})
        h = out["hookSpecificOutput"]
        self.assertEqual(set(h), {"hookEventName", "permissionDecision", "permissionDecisionReason"})
        self.assertEqual(h["hookEventName"], "PreToolUse")
        self.assertIn(h["permissionDecision"], DECISIONS)
        self.assertTrue(isinstance(h["permissionDecisionReason"], str) and h["permissionDecisionReason"])

    def test_pretooluse_answers(self):
        events = [("Bash", {"command": "git stash"}, "deny"),
                  ("Bash", {"command": "git push origin main"}, "ask"),
                  ("Bash", {"command": "ls"}, None),
                  ("Read", {"file_path": str(ROOT / ".env")}, "deny"),
                  ("Grep", {"pattern": "KEY", "glob": "*.env"}, "deny"),
                  ("Edit", {"file_path": str(ROOT / "harness/core/rules.md"), "old_string": "a",
                            "new_string": "b", "replace_all": False}, "ask"),
                  ("Write", {"file_path": str(ROOT / "src/x.py"), "content": "x = 1\n"}, None)]
        for tool, args, want in events:
            r = run_hook("PreToolUse", {**common("PreToolUse"), "tool_name": tool, "tool_input": args,
                                        "tool_use_id": "toolu_1"})
            self.assertEqual(r.returncode, 0, r.stderr)
            if want is None:
                self.assertEqual(r.stdout.strip(), "", (tool, args))
                continue
            out = json.loads(r.stdout)
            self.check_pretooluse(out)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], want, (tool, args))

    def test_subagent_fields_are_understood(self):
        r = run_hook("PreToolUse", {**common("PreToolUse"), "tool_name": "Bash", "agent_id": "a1",
                                    "agent_type": "harness-change-reviewer",
                                    "tool_input": {"command": "rm -rf build"}, "tool_use_id": "toolu_2"})
        out = json.loads(r.stdout)
        self.check_pretooluse(out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_stop_answers(self):
        repo = Path(tempfile.mkdtemp())
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        r = run_hook("Stop", {**common("Stop"), "cwd": str(repo), "stop_hook_active": False,
                              "last_assistant_message": "done"})
        self.assertEqual(r.returncode, 0, r.stderr)
        if r.stdout.strip():
            out = json.loads(r.stdout)
            self.assertTrue(set(out) <= {"decision", "reason", "systemMessage"}, out)
            if "decision" in out:
                self.assertEqual(out["decision"], "block")
                self.assertTrue(out["reason"])

    def test_stop_bound_comes_before_the_claude_code_cap(self):
        conf = json.loads((ROOT / ".claude" / "harness-hooks.json").read_text(encoding="utf-8"))
        self.assertLess(conf["stop"]["max_blocks"], STOP_CAP)

    def test_config_change_answers(self):
        r = run_hook("ConfigChange", {**common("ConfigChange"), "source": "skills",
                                      "file_path": str(ROOT / ".claude/skills/harness-setup/SKILL.md")})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(set(out), {"decision", "reason"})
        self.assertEqual(out["decision"], "block")


if __name__ == "__main__":
    unittest.main()
