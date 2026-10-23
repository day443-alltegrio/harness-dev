"""Agent telemetry: right numbers and no text in the output."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent_metrics as am  # noqa: E402

NOW = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
TODAY = NOW.isoformat()
SECRET = "patient John Placeholder 3123456"  # scan: ignore (made-up example)


def entry(**kw) -> str:
    return json.dumps({"timestamp": TODAY, "sessionId": "s1", **kw}, ensure_ascii=False)


def bash_use(cmd: str, mid: str) -> str:
    return entry(type="assistant", message={"id": mid, "usage": {"input_tokens": 10, "output_tokens": 5},
                                            "content": [{"type": "tool_use", "name": "Bash",
                                                         "input": {"command": cmd}}]})


class Metrics(unittest.TestCase):
    def build(self) -> dict:
        proj, hooks = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        lines = [
            entry(type="user", message={"content": f"how many {SECRET}?"}),
            entry(type="user", message={"content": "<system-reminder>x</system-reminder>"}),
            bash_use("pytest a", "m1"), bash_use("pytest a", "m1"),  # the same message twice
            bash_use("pytest a", "m2"), bash_use("pytest a", "m3"),
            entry(type="user", message={"content": [{"type": "tool_result", "is_error": True,
                                                     "content": SECRET}]}),
            entry(type="user", isCompactSummary=True, message={"content": "summary"}),
        ]
        (proj / "s1.jsonl").write_text("\n".join(lines), encoding="utf-8")
        sub = proj / "s1" / "subagents"
        sub.mkdir(parents=True)
        (sub / "a.jsonl").write_text(bash_use("ls", "m9"), encoding="utf-8")
        (hooks / "x.jsonl").write_text(json.dumps({"ts": NOW.strftime("%Y-%m-%dT%H:%M:%S"),
                                                   "rule": "git-destructive",
                                                   "decision": "deny"}), encoding="utf-8")
        return am.collect(proj, hooks, 2)

    def test_counts(self):
        data = self.build()
        day = list(data["days"].values())[0]
        self.assertEqual(day["prompts"], 1)
        self.assertEqual(day["sessions"], 1)
        self.assertEqual(day["tool_calls"], 4)
        self.assertEqual(day["subagent_tool_calls"], 1)
        self.assertEqual(day["tool_errors"], 1)
        self.assertEqual(day["compactions"], 1)
        self.assertEqual(day["repeat_streaks"], 1)
        self.assertEqual(day["tokens"]["input_tokens"], 40)  # m1, m2, m3, m9, no m1 twice
        self.assertEqual(day["hook_blocks"], {"git-destructive:deny": 1})

    def test_no_text_leaks(self):
        out = json.dumps(self.build(), ensure_ascii=False)
        self.assertNotIn("Placeholder", out)
        self.assertNotIn("3123456", out)  # scan: ignore
        self.assertNotIn("pytest", out)


if __name__ == "__main__":
    unittest.main()
