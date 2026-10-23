"""Preflight (QG2) on real temporary git repositories."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preflight as pf  # noqa: E402

REF = "refs/harness/deployed"
STAMP = {"build_stamp": {"file": "dist/version.json", "key": "version"}, "generated": ["dist/"]}


def sh(root: Path, *args: str) -> str:
    return subprocess.run(args, cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def make_repo(branch: str = "main", conf: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    sh(root, "git", "init", "-q", "-b", branch)
    sh(root, "git", "config", "user.email", "t@example.com")
    sh(root, "git", "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("x = 1\n")
    if conf is not None:
        (root / "harness" / "config").mkdir(parents=True)
        (root / "harness" / "config" / "harness.json").write_text(json.dumps(conf))
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "init")
    return root


def build(root: Path, suffix: str = "") -> None:
    head = sh(root, "git", "rev-parse", "--short", "HEAD")
    (root / "dist").mkdir(exist_ok=True)
    (root / "dist" / "version.json").write_text(
        json.dumps({"version": f"{head}{suffix}-20261021T120000"}))


def run(root: Path, branch: str = "main") -> list[str]:
    return pf.run(root, branch, tools=False)


class Preflight(unittest.TestCase):
    def test_clean_tree_passes(self):
        self.assertEqual(run(make_repo()), [])

    def test_dirty_tree_fails(self):
        # A1: uncommitted edits went to production.
        root = make_repo()
        (root / "src/main.py").write_text("x = 2\n")
        self.assertTrue(any("uncommitted files" in p for p in run(root)))

    def test_modified_path_is_reported_whole(self):
        # " M path": the first column is a space, the file name is not cut.
        root = make_repo()
        (root / "src/main.py").write_text("x = 2\n")
        self.assertTrue(any("src/main.py" in p for p in run(root)))

    def test_untracked_file_fails(self):
        root = make_repo()
        (root / "new.py").write_text("x")
        self.assertTrue(any("uncommitted files" in p for p in run(root)))

    def test_wrong_branch_fails(self):
        self.assertTrue(any("branch" in p for p in run(make_repo(branch="feature"))))

    def test_generated_paths_do_not_count(self):
        root = make_repo(conf={"generated": ["dist/"]})
        (root / "dist").mkdir()
        (root / "dist" / "app.js").write_text("built")
        self.assertEqual(run(root), [])


class BuildStamp(unittest.TestCase):
    def test_build_from_head_passes(self):
        root = make_repo(conf=STAMP)
        build(root)
        self.assertEqual(run(root), [])

    def test_stale_build_fails(self):
        # A4: a deploy shipped a build older than the commit.
        root = make_repo(conf=STAMP)
        build(root)
        (root / "src/main.py").write_text("x = 2\n")
        sh(root, "git", "commit", "-qam", "v2")
        self.assertTrue(any("rebuild" in p for p in run(root)))

    def test_build_from_dirty_tree_fails(self):
        root = make_repo(conf=STAMP)
        build(root, "+")
        self.assertTrue(any("uncommitted code" in p for p in run(root)))

    def test_missing_build_fails(self):
        self.assertTrue(any("build stamp" in p for p in run(make_repo(conf=STAMP))))


class Lineage(unittest.TestCase):
    def test_new_commit_must_descend_from_deployed(self):
        # A deploy never overwrites another deployed commit.
        root = make_repo()
        sh(root, "git", "update-ref", REF, "HEAD")
        sh(root, "git", "checkout", "-q", "-b", "other", "HEAD")  # a branch in the temp repo
        (root / "src/main.py").write_text("other\n")
        sh(root, "git", "commit", "-qam", "other")
        sh(root, "git", "update-ref", REF, "HEAD")
        sh(root, "git", "checkout", "-q", "main")
        (root / "src/main.py").write_text("mine\n")
        sh(root, "git", "commit", "-qam", "mine")
        self.assertTrue(any("does not continue" in p for p in run(root)))

    def test_descendant_passes(self):
        root = make_repo()
        sh(root, "git", "update-ref", REF, "HEAD")
        (root / "src/main.py").write_text("next\n")
        sh(root, "git", "commit", "-qam", "next")
        self.assertEqual(run(root), [])


class Report(unittest.TestCase):
    """A preflight stop goes to the deploy journal in the shape of the deploy check report."""

    def test_reasons_from_prefixed_lines_only(self):
        out = "preflight: no contract\nscanner noise\npreflight: tree not clean\n"
        r = pf.report(out)
        self.assertEqual(r["reasons"], ["no contract", "tree not clean"])
        self.assertEqual((r["agent"], r["gate"], r["verdict"]), ("preflight", "QG2", "blocked"))

    def test_no_prefixed_lines_still_has_reason(self):
        self.assertEqual(pf.report("Traceback ...")["reasons"], ["preflight did not pass"])


if __name__ == "__main__":
    unittest.main()
