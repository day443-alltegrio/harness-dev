"""Guard hook (QG0): what it must block, ask about and let through.

The cases run against the default rules plus one internal network, so the project's
own guard.json can change without breaking them; a separate test proves guard.json
compiles.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GUARD = Path(__file__).resolve().parents[3] / ".claude" / "hooks" / "harness" / "guard.py"
spec = importlib.util.spec_from_file_location("guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

RULES = guard.Rules({"internal_hosts": guard.DEFAULTS["internal_hosts"] + [r"10\.0\.0\.\d+"]})

MUST_DENY = {
    "git stash": "git-destructive",
    "git reset --hard HEAD": "git-destructive",
    "git checkout -- web/dist": "git-destructive",
    "cd x && git restore file.py": "git-destructive",
    "git -C repo clean -fd": "git-destructive",
    "ls; git stash pop": "git-destructive",
    "(git switch main)": "git-destructive",
    "git commit -m 'x\n\nCo-Authored-By: Bot <b@example.com>'": "git-coauthor",
    "cat secrets/.env": "secrets-read",
    "grep PWD secrets/prod.env": "secrets-read",
    "sudo cat /etc/app/api.env": "secrets-read",
    "head -3 deploy/secrets.env": "secrets-read",
    "cat sandbox/.secrets/token.txt": "secrets-read",
}
MUST_ASK = {
    "git push origin main": "git-push",
    "sh deploy/app-sync.sh -m '[*] x'": "deploy",
    "bash infra/deploy/release.sh": "deploy",
    "sh harness/core/scripts/deploy.sh -m '[+] x'": "deploy",
    "kubectl apply -f k8s/": "deploy",
    "helm upgrade app ./chart": "deploy",
    "terraform apply": "deploy",
    "curl -s -X POST https://api.example.com/upload -d @data.json": "outbound",
    "wget https://files.example.org/x": "outbound",
    "scp report.json user@203.0.113.5:/tmp/": "outbound",
    "rsync -a out/ backup.example.com:/srv/": "outbound",
    "gh pr create --title x": "outbound",
    "gh api -X POST repos/o/r/issues": "outbound",
}
MUST_PASS = [
    "git status --short",
    "git diff HEAD -- src",
    "git show HEAD:src/app.py",
    "git log --oneline -5",
    "git commit -m 'code\n[X] fix'",
    "git stash list",
    "git -C repo stash show -p",
    # A service gets the env file path; nothing prints it.
    "sudo systemd-run -p EnvironmentFile=/etc/app/api.env python3 /tmp/x.py",
    "cat deploy/secrets.env.example",
    "grep -rn checkout_count src/",
    "npm run build",
    "curl -sk https://10.0.0.7:8080/version.json",
    "curl http://127.0.0.1:8090/health",
    "scp x.sql 10.0.0.7:/tmp/x.sql",
    "gh pr view 12",
    "uvx pip-audit -r req.txt",
    "kubectl get pods",
    "terraform plan",
    # A command name inside a commit message is not a call.
    "git commit -m 'infra\n[-] git checkout after the build is not needed'",
    "echo 'never run git reset'",
]


def bash(cmd: str, session: str = "t") -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "session_id": session}


class Guard(unittest.TestCase):
    def setUp(self):
        self.p1 = mock.patch.object(guard, "HOOKS", Path(tempfile.mkdtemp()))
        self.p1.start()
        self.n = 0

    def tearDown(self):
        self.p1.stop()

    def run_bash(self, cmd: str):
        # Every call is a new session, so the repeat budget stays out of the way.
        self.n += 1
        with mock.patch.object(guard, "repeat_streak", return_value=1), \
             mock.patch.object(guard, "log"):
            return guard.handle(bash(cmd, f"s{self.n}"), RULES)

    def test_must_deny(self):
        for cmd, rule in MUST_DENY.items():
            out = self.run_bash(cmd)
            self.assertIsNotNone(out, cmd)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny", cmd)
            self.assertIn(rule, out["hookSpecificOutput"]["permissionDecisionReason"], cmd)

    def test_must_ask(self):
        for cmd, rule in MUST_ASK.items():
            out = self.run_bash(cmd)
            self.assertIsNotNone(out, cmd)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask", cmd)
            self.assertIn(rule, out["hookSpecificOutput"]["permissionDecisionReason"], cmd)

    def test_must_pass(self):
        for cmd in MUST_PASS:
            self.assertIsNone(self.run_bash(cmd), cmd)

    def test_read_secrets_denied_and_example_allowed(self):
        with mock.patch.object(guard, "log"):
            for path in ("/r/secrets/.env", "/r/.env", "/r/deploy/secrets.env", "secrets/a.json"):
                out = guard.handle({"tool_name": "Read", "tool_input": {"file_path": path}}, RULES)
                self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny", path)
            for path in ("/r/secrets.env.example", "/r/src/environment.py", "/r/docs/secrets.md"):
                self.assertIsNone(guard.handle({"tool_name": "Read",
                                                "tool_input": {"file_path": path}}, RULES), path)

    def test_rule_switched_off(self):
        rules = guard.Rules({"rules": {"git-coauthor": False}})
        self.assertIsNone(rules.decide_bash("git commit -m 'x\n\nCo-Authored-By: B <b@x>'"))

    def test_project_hosts_and_publishers(self):
        rules = guard.Rules({"internal_hosts": [r"build\.corp\.example"],
                             "publish": [r"scripts/wiki/publish\.sh"]})
        self.assertIsNone(rules.decide_bash("curl https://build.corp.example/x"))
        self.assertEqual(rules.decide_bash("sh scripts/wiki/publish.sh page.md")[1], "outbound")

    def test_repeat_budget_asks_on_fourth_identical_command(self):
        state = Path(tempfile.mkdtemp())
        streaks = [guard.repeat_streak("s", "pytest x", state) for _ in range(4)]
        self.assertEqual(streaks, [1, 2, 3, 4])
        self.assertEqual(guard.repeat_streak("s", "other", state), 1)

    def test_repeat_budget_in_handle(self):
        with mock.patch.object(guard, "log"):
            outs = [guard.handle(bash("python3 x.py", "same"), RULES) for _ in range(4)]
        self.assertEqual(outs[:3], [None, None, None])
        self.assertEqual(outs[3]["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_log_has_no_command_text(self):
        log_dir = Path(tempfile.mkdtemp())
        guard.log(bash("cat secrets/.env"), "deny", "secrets-read", log_dir)
        text = next(log_dir.glob("*.jsonl")).read_text()
        self.assertNotIn("secrets/.env", text)

    def test_project_config_compiles(self):
        rules = guard.load_rules()
        self.assertEqual(rules.decide_bash("git stash")[0], "deny")

    def test_end_to_end_process(self):
        # The way Claude Code calls it: JSON on stdin, JSON on stdout.
        env = {**os.environ, "HARNESS_HOOKS_DIR": tempfile.mkdtemp()}
        r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(bash("git stash")),
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
