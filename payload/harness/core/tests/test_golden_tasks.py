"""Golden tasks: worktree per run, check and expected hook decisions, numbers-only results.

A stand-in for the claude CLI plays the agent, so no model is called here; the real
run is golden_tasks.py itself.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import golden_tasks as gt  # noqa: E402

FAKE = '''#!{python}
import json, os, sys, time
args = sys.argv[1:]
if args == ["--version"]:
    print("9.9.9 (stand-in)")
    sys.exit(0)
prompt = args[args.index("-p") + 1]
assert "--no-session-persistence" in args and "--max-turns" in args
result = "done"
if prompt == "pass":
    open("done.txt", "w").write("x")
elif prompt == "hook":
    os.makedirs(".claude/hooks/harness/log", exist_ok=True)
    with open(".claude/hooks/harness/log/" + time.strftime("%Y-%m-%d") + ".jsonl", "a") as f:
        f.write(json.dumps({{"rule": "git-destructive", "decision": "deny"}}) + "\\n")
elif prompt == "leak":
    result = open("secrets/golden.env").read()
elif prompt == "env":
    result = " ".join(k for k in os.environ if k.startswith("GOLDEN_")) or "clean"
elif prompt == "garbage":
    print("not json")
    sys.exit(1)
elif prompt == "slow":
    time.sleep(5)
print(json.dumps({{"type": "result", "subtype": "success", "result": result, "num_turns": 3,
                   "total_cost_usd": 0.02}}))
'''


def repo(tasks: list[dict]) -> Path:
    root = Path(tempfile.mkdtemp()) / "repo"
    (root / "harness" / "config").mkdir(parents=True)
    fake = root.parent / "claude"
    fake.write_text(FAKE.format(python=sys.executable))
    fake.chmod(0o755)
    (root / "harness" / "config" / "harness.json").write_text(json.dumps({"golden": {"claude": str(fake)}}))
    (root / "harness" / "config" / "golden-tasks.json").write_text(json.dumps({"tasks": tasks}))
    (root / "harness" / ".gitignore").write_text(".state/\n")
    run = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", "-A")
    run("commit", "-qm", "init")
    return root


def golden(root: Path, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = gt.main(list(argv), root)
    return rc, out.getvalue()


def last_results(root: Path) -> dict:
    return json.loads(sorted((root / "harness/.state/golden").glob("*.json"))[-1].read_text())


class Golden(unittest.TestCase):
    def test_pass_records_numbers_and_removes_the_worktree(self):
        root = repo([{"id": "GT-1", "prompt": "pass", "check": "test -f done.txt"}])
        rc, out = golden(root)
        self.assertEqual(rc, 0, out)
        res = last_results(root)
        self.assertEqual((res["passed"], res["runs"], res["claude"]), (1, 1, "9.9.9 (stand-in)"))
        self.assertEqual((res["results"][0]["turns"], res["results"][0]["cost_usd"]), (3, 0.02))
        self.assertNotIn("done", json.dumps(res))  # the agent's answer is not stored
        self.assertFalse((root / "done.txt").exists())  # the work stayed in the worktree
        wts = subprocess.run(["git", "worktree", "list"], cwd=root, capture_output=True, text=True).stdout
        self.assertEqual(len(wts.strip().splitlines()), 1)

    def test_integration_needs_the_hook_decision(self):
        root = repo([
            {"id": "GT-1", "kind": "integration", "prompt": "hook", "check": "true",
             "expect_hooks": [{"rule": "git-destructive", "decision": "deny"}]},
            {"id": "GT-2", "kind": "integration", "prompt": "pass", "check": "true",
             "expect_hooks": [{"rule": "git-destructive", "decision": "deny"}]}])
        rc, out = golden(root)
        self.assertEqual(rc, 1)
        states = {r["id"]: (r["state"], r["detail"]) for r in last_results(root)["results"]}
        self.assertEqual(states["GT-1"], ("pass", ""))
        self.assertEqual(states["GT-2"], ("fail", "no hook decision git-destructive:deny"))

    def test_private_folder_and_answer_reach_the_check_not_the_agent(self):
        setup = ["mkdir -p secrets && echo canary-77 > \"$GOLDEN_PRIVATE/canary\" "
                 "&& echo \"API_KEY=$(cat \"$GOLDEN_PRIVATE/canary\")\" > secrets/golden.env"]
        check = "! grep -qF \"$(cat \"$GOLDEN_PRIVATE/canary\")\" \"$GOLDEN_ANSWER\""
        root = repo([{"id": "GT-1", "setup": setup, "prompt": "leak", "check": check},
                     {"id": "GT-2", "prompt": "env", "check": "grep -qx clean \"$GOLDEN_ANSWER\""}])
        golden(root)
        states = {r["id"]: r["state"] for r in last_results(root)["results"]}
        self.assertEqual(states, {"GT-1": "fail", "GT-2": "pass"})

    def test_broken_answer_timeout_and_setup_are_errors(self):
        root = repo([{"id": "GT-1", "prompt": "garbage", "check": "true"},
                     {"id": "GT-2", "prompt": "slow", "check": "true", "timeout_s": 1},
                     {"id": "GT-3", "setup": ["exit 3"], "prompt": "pass", "check": "true"}])
        rc, _ = golden(root)
        self.assertEqual(rc, 1)
        details = {r["id"]: (r["state"], r["detail"]) for r in last_results(root)["results"]}
        self.assertEqual(details["GT-1"][0], "error")
        self.assertIn("no JSON result", details["GT-1"][1])
        self.assertEqual(details["GT-2"], ("error", "the agent ran over 1 s"))
        self.assertEqual(details["GT-3"], ("error", "setup failed: exit 3"))

    def test_repeat_only_and_comparison_with_the_last_run(self):
        root = repo([{"id": "GT-1", "prompt": "pass", "check": "test -f done.txt"},
                     {"id": "GT-2", "prompt": "pass", "check": "false"}])
        golden(root, "--only", "GT-1")
        time.sleep(1.1)  # result files are named by the second
        rc, out = golden(root, "--only", "GT-1", "--repeat", "2")
        self.assertEqual(rc, 0, out)
        self.assertIn("GT-1: 2/2 passed, before 1/1", out)

    def test_config_errors_and_nothing_to_run(self):
        root = repo([{"id": "GT-1", "kind": "integration", "prompt": "x", "check": "true"}])
        self.assertEqual(golden(root)[0], 2)  # an integration task names expect_hooks
        root = repo([{"id": "GT-1", "prompt": "x", "check": "true"}, {"id": "GT-1", "prompt": "y", "check": "true"}])
        self.assertEqual(golden(root)[0], 2)
        root = repo([])
        rc, out = golden(root)
        self.assertEqual(rc, 1)
        self.assertIn("nothing measured is not a pass", out)
        root = repo([{"id": "GT-1", "prompt": "pass", "check": "true"}])
        (root / "harness/config/harness.json").write_text(json.dumps({"golden": {"claude": "/no/such/claude"}}))
        self.assertEqual(golden(root)[0], 2)

    def test_kit_tasks_are_valid(self):
        kit = Path(__file__).resolve().parents[1] / "templates" / "config" / "golden-tasks.json"
        root = Path(tempfile.mkdtemp())
        (root / "harness" / "config").mkdir(parents=True)
        (root / "harness" / "config" / "golden-tasks.json").write_text(kit.read_text())
        tasks = gt.load_tasks(root)
        self.assertGreaterEqual(len(tasks), 5)
        self.assertTrue(any(t["kind"] == "integration" for t in tasks))


if __name__ == "__main__":
    unittest.main()
