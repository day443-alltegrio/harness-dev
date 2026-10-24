"""False blocks: people mark wrong hook decisions by id, a rule over the share is flagged."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hook_review as hr  # noqa: E402


def log_dir_with(decisions: list[tuple[str, str, str]]) -> Path:
    """A hook log of today: (id, rule, decision) per line."""
    d = Path(tempfile.mkdtemp())
    lines = [json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": "Bash", "agent": "main",
                         "rule": rule, "decision": dec, "session": "s", "id": did})
             for did, rule, dec in decisions]
    (d / f"{time.strftime('%Y-%m-%d')}.jsonl").write_text("\n".join(lines) + "\n")
    return d


def cli(log_dir: Path, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with mock.patch.object(hr.harness_config, "HOOK_LOG", log_dir), redirect_stdout(out):
        rc = hr.main(list(argv))
    return rc, out.getvalue()


class Review(unittest.TestCase):
    def test_mark_by_id_and_report(self):
        d = log_dir_with([(f"a{i:07d}", "secrets-read", "deny") for i in range(5)]
                         + [("b0000001", "deploy", "ask")])
        rep = hr.report(d, 30, 0.2, 5)
        self.assertEqual((rep["decisions"], rep["false"], rep["over"]), (6, 0, []))
        hr.mark(d, ["a0000000", "a0000001"], "echo of a file name, not its content")
        rep = hr.report(d, 30, 0.2, 5)
        self.assertEqual(rep["rules"]["secrets-read"], {"decisions": 5, "false": 2, "share": 0.4,
                                                        "over": True})
        self.assertEqual(rep["over"], ["secrets-read"])
        self.assertFalse(rep["rules"]["deploy"]["over"])

    def test_few_decisions_are_not_judged(self):
        d = log_dir_with([("c0000001", "outbound", "ask"), ("c0000002", "outbound", "ask")])
        hr.mark(d, ["c0000001"], "internal mirror")
        self.assertEqual(hr.report(d, 30, 0.2, 5)["over"], [])

    def test_unknown_id_and_empty_reason_are_refused(self):
        d = log_dir_with([("d0000001", "git-push", "ask")])
        with self.assertRaises(ValueError):
            hr.mark(d, ["ffffffff"], "x")
        with self.assertRaises(ValueError):
            hr.mark(d, ["d0000001"], "  ")
        self.assertFalse(hr.marks_file(d).exists())

    def test_cli_last_list_and_exit_code(self):
        d = log_dir_with([(f"e{i:07d}", "obfuscated", "ask") for i in range(5)])
        rc, out = cli(d, "mark", "--last", "--reason", "a vendor installer we trust")
        self.assertEqual(rc, 0)
        self.assertIn("e0000004", out)
        rc, out = cli(d, "list")
        self.assertIn("false block", out)
        self.assertIn("5 decisions", out)
        self.assertEqual(cli(d, "report")[0], 0)  # 1 of 5 is 20%, not over
        cli(d, "mark", "e0000000", "--reason", "same installer")
        rc, out = cli(d, "report")
        self.assertEqual(rc, 1)
        self.assertIn("OVER", out)
        self.assertEqual(json.loads(cli(d, "report", "--json")[1])["over"], ["obfuscated"])

    def test_marks_stay_out_of_the_day_logs(self):
        d = log_dir_with([("f0000001", "deploy", "ask")])
        hr.mark(d, ["f0000001"], "test deploy to a local folder")
        self.assertEqual(sorted(p.name for p in d.glob("*.jsonl")), [f"{time.strftime('%Y-%m-%d')}.jsonl"])
        self.assertEqual(len(hr.decisions(d)), 1)

    def test_nothing_logged(self):
        d = Path(tempfile.mkdtemp())
        self.assertEqual(hr.report(d, 30, 0.2, 5)["decisions"], 0)
        self.assertEqual(cli(d, "mark", "--last", "--reason", "x")[0], 2)


if __name__ == "__main__":
    unittest.main()
