"""QG2 commit scanner: secrets, project IDs and names fail; ordinary code does not.

The values in the examples are made up (and marked scan: ignore, so this file does not
catch itself in a real commit).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import commit_scan as cs  # noqa: E402

CONF = {"scan": {"id_patterns": [{"name": "record id",
                                  "regex": r"(?<![\w.,:/#-])(?:\d{6,7}|3\d{7})(?![\w.,:/-])"}],
                 "name_detectors": ["uk_full_name"]}}

MUST_FIND = {
    "record_id = 3123456  # scan: ignore": None,  # the mark skips the line
    "record 1234567 in the logs": "record id",  # scan: ignore
    "doc 38765432 opened": "record id",  # scan: ignore
    "лікар Петренко Іван Степанович": "personal name",  # scan: ignore
    "огляд Коваленко О. Ю. та інших": "personal name",  # scan: ignore
    "-----BEGIN OPENSSH PRIVATE KEY-----": "private key",  # scan: ignore
    "token = 'ghp_" + "a" * 36 + "'": "GitHub token",
    "JIRA = 'ATATT" + "x" * 30 + "'": "Atlassian token",
    'password = "S3cretValue!"': "password",  # scan: ignore
}
MUST_PASS = [
    "corpus = '128 595 records'",
    "version = '10179cd-20261021T150728'",
    "timeout = 1800",
    "password = os.environ['DB_PASSWORD']",
    'token = "${TOKEN}"',
    "Deploy check: API contract, tests",
    "Коваленко Дмитро - ІТ-директор",  # a name without a patronymic is not a full name
    "port 8080, 10.0.0.7",
    'PASSWORD_URL = "/account/password"',
]


def root_with(conf: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "harness" / "config").mkdir(parents=True)
    (root / "harness" / "config" / "harness.json").write_text(json.dumps(conf))
    return root


class Lines(unittest.TestCase):
    def setUp(self):
        self.sc = cs.Scanner(root_with(CONF))

    def test_must_find(self):
        for text, kind in MUST_FIND.items():
            found = self.sc.scan_lines([("src/x.py", 1, text)])
            if kind is None:
                self.assertEqual(found, [], text)
            else:
                self.assertTrue(any(kind in f for f in found), (text, found))

    def test_must_pass(self):
        for text in MUST_PASS:
            self.assertEqual(self.sc.scan_lines([("src/x.py", 1, text)]), [], text)

    def test_finding_does_not_repeat_value(self):
        found = self.sc.scan_lines([("src/x.py", 7, "id 1234567")])  # scan: ignore
        self.assertEqual(found, ["src/x.py:7: record id"])

    def test_test_fixture_password_not_a_secret(self):
        self.assertEqual(self.sc.scan_lines([("app/tests/test_x.py", 1, 'password="new-pass-1"')]), [])
        # a token in a test is still a finding
        tok = "token = 'ghp_" + "b" * 36 + "'"
        self.assertTrue(self.sc.scan_lines([("app/tests/test_x.py", 1, tok)]))

    def test_generated_and_locks_skipped(self):
        sc = cs.Scanner(root_with({**CONF, "generated": ["web/dist/"]}))
        for path in ("web/dist/index.js", "api/requirements.lock.txt", "x.docx", "node_modules/a.js"):
            self.assertEqual(sc.scan_lines([(path, 1, "1234567")]), [], path)  # scan: ignore

    def test_defaults_scan_secrets_only(self):
        sc = cs.Scanner(Path(tempfile.mkdtemp()))
        self.assertEqual(sc.scan_lines([("src/x.py", 1, "id 1234567")]), [])  # scan: ignore
        self.assertTrue(sc.scan_lines([("src/x.py", 1, "-----BEGIN RSA PRIVATE KEY-----")]))  # scan: ignore


class Diff(unittest.TestCase):
    def repo(self) -> Path:
        root = root_with(CONF)
        run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731
        run("git", "init", "-q")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "t")
        return root

    def test_only_added_lines_of_commit(self):
        root = self.repo()
        run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731
        (root / "a.txt").write_text("old 1234567\n")  # scan: ignore
        run("git", "add", "-A")
        run("git", "commit", "-qm", "1")
        (root / "a.txt").write_text("old 1234567\nnew line\nid 7654321\n")  # scan: ignore
        run("git", "commit", "-qam", "2")
        self.assertEqual(cs.run("HEAD~1", root, tools=False), ["a.txt:3: record id"])

    def test_first_commit_has_no_base(self):
        self.assertEqual(cs.run("HEAD~1", self.repo(), tools=False), [])

    def test_history_finds_secret_kind_without_value(self):
        root = self.repo()
        run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731
        (root / "k.txt").write_text("key = 'AKIA" + "A" * 16 + "'\n")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "1")
        found = cs.history_secrets(root)
        self.assertEqual(len(found), 1)
        self.assertIn("AWS key", found[0])
        self.assertNotIn("AKIA", found[0])


if __name__ == "__main__":
    unittest.main()
