"""deploy.sh end to end on a temporary repository with stand-in project steps."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

HOOKS = """
deploy_package() { git archive --format=tar.gz -o "$1" HEAD; }
deploy_ship() { cp "$1" "$OUT/shipped.tar.gz"; }
deploy_verify() { printf '%s\\n' "$VERDICT_JSON"; }
deploy_swap() { touch "$OUT/swapped"; }
deploy_health() { [ "${HEALTH:-ok}" = ok ]; }
"""
PASS = json.dumps({"agent": "agent:deployer", "verdict": "pass", "reasons": [],
                   "tests": {"files": 1, "passed": 1, "failed": []}})
BLOCKED = json.dumps({"agent": "agent:deployer", "verdict": "blocked",
                      "reasons": ["tests failed: test_a.py"]})


class Deploy(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.out = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "harness" / "core", self.repo / "harness" / "core",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "harness" / ".gitignore", self.repo / "harness" / ".gitignore")
        (self.repo / "app.py").write_text("print('hi')\n")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        (self.out / "hooks.sh").write_text(HOOKS)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True,
                              check=True).stdout.strip()

    def deploy(self, *args: str, verdict: str = PASS, health: str = "ok") -> subprocess.CompletedProcess:
        env = {**os.environ, "DEPLOY_HOOKS": str(self.out / "hooks.sh"), "OUT": str(self.out),
               "VERDICT_JSON": verdict, "HEALTH": health}
        env.pop("DEPLOY_NOTES", None)
        env.pop("DEPLOY_NOTES_FILE", None)
        return subprocess.run(["sh", str(self.repo / "harness/core/scripts/deploy.sh"), *args],
                              cwd=self.repo, env=env, capture_output=True, text=True)

    def journal(self) -> list[dict]:
        p = self.repo / "harness/.state/deploys.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.is_file() else []

    def test_notes_are_required(self):
        r = self.deploy()
        self.assertEqual(r.returncode, 2)
        self.assertIn("No deploy without notes", r.stderr)

    def test_notes_need_markers(self):
        r = self.deploy("-m", "fixed the search")
        self.assertEqual(r.returncode, 2)
        self.assertIn("without a marker", r.stderr)

    def test_success_records_and_moves_the_deployed_ref(self):
        r = self.deploy("-m", "[+] first release")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.out / "swapped").exists())
        rep = json.loads((self.repo / "harness/.state/deploy-last.json").read_text())
        self.assertEqual(rep["verdict"], "pass")
        self.assertEqual(self.git("rev-parse", "refs/harness/deployed"), self.git("rev-parse", "HEAD"))
        self.assertEqual([j["status"] for j in self.journal()], ["DONE"])
        self.assertEqual(self.journal()[0]["notes"], "[+] first release")

    def test_blocked_check_changes_nothing(self):
        r = self.deploy("-m", "[*] change", verdict=BLOCKED)
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.out / "swapped").exists())
        self.assertIn("test_a.py", r.stderr)
        self.assertEqual([j["status"] for j in self.journal()], ["BLOCKED"])

    def test_check_without_answer_blocks(self):
        r = self.deploy("-m", "[*] change", verdict="")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.out / "swapped").exists())

    def test_unhealthy_service_is_a_failed_deploy(self):
        r = self.deploy("-m", "[X] fix", health="down")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED", r.stderr)
        rep = json.loads((self.repo / "harness/.state/deploy-last.json").read_text())
        self.assertEqual(rep["verdict"], "fail")
        self.assertNotEqual(subprocess.run(["git", "rev-parse", "--verify", "--quiet",
                                            "refs/harness/deployed"], cwd=self.repo).returncode, 0)

    def test_dirty_tree_stops_before_anything_ships(self):
        (self.repo / "app.py").write_text("print('changed')\n")
        r = self.deploy("-m", "[*] change")
        self.assertEqual(r.returncode, 1)
        self.assertIn("preflight stopped the deploy", r.stderr)
        self.assertFalse((self.out / "shipped.tar.gz").exists())
        self.assertEqual([j["status"] for j in self.journal()], ["BLOCKED"])


if __name__ == "__main__":
    unittest.main()
