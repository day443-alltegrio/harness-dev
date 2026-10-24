"""harness.py: install, upgrade and status on temporary repositories and kit copies.

Each test copies the kit, changes the copy the way a new version would, and checks what
an install or an upgrade does to a project: kit-owned files replaced only when untouched,
project-owned files never overwritten, settings and the CLAUDE.md block merged,
migrations run once.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
GATES = "harness/core/scripts/gates.py"
# Versions after the one in the kit, so the tests hold at every release.
_MAJOR, _MINOR, _ = (int(x) for x in (KIT / "VERSION").read_text().split("."))
NEXT, AFTER = f"{_MAJOR}.{_MINOR + 1}.0", f"{_MAJOR}.{_MINOR + 2}.0"


def make_kit() -> Path:
    kit = Path(tempfile.mkdtemp()) / "kit"
    kit.mkdir()
    for name in ("harness.py", "VERSION", "CHANGELOG.md"):
        shutil.copy(KIT / name, kit / name)
    shutil.copytree(KIT / "payload", kit / "payload", ignore=shutil.ignore_patterns("__pycache__"))
    return kit


def release(kit: Path, version: str, note: str = "[*] a change") -> None:
    (kit / "VERSION").write_text(version + "\n")
    (kit / "payload/harness/core/VERSION").write_text(version + "\n")
    log = (kit / "CHANGELOG.md").read_text()
    head, _, rest = log.partition("\n## ")
    (kit / "CHANGELOG.md").write_text(f"{head}\n## {version} - 2026-11-01\n\n{note}\n\n## {rest}")


def make_repo(files: dict[str, str] | None = None) -> Path:
    repo = Path(tempfile.mkdtemp()) / "repo"
    repo.mkdir()
    for name, text in (files or {"README.md": "# demo\n"}).items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "t"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


def cli(kit: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(kit / "harness.py"), *args],
                          capture_output=True, text=True)


def lock(repo: Path) -> dict:
    return json.loads((repo / "harness/harness.lock.json").read_text())


class Install(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        kit, repo = make_kit(), make_repo()
        r = cli(kit, "install", str(repo), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((repo / "harness").exists())
        self.assertFalse((repo / ".claude").exists())

    def test_install_creates_kit_and_project_files(self):
        kit, repo = make_kit(), make_repo()
        r = cli(kit, "install", str(repo))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in (GATES, ".claude/hooks/harness/guard.py", "harness/config/harness.json",
                    "harness/project/rules.md", ".claude/harness-hooks.json", "CLAUDE.md"):
            self.assertTrue((repo / rel).is_file(), rel)
        lk = lock(repo)
        self.assertEqual(lk["version"], (KIT / "VERSION").read_text().strip())
        self.assertIn(GATES, lk["managed"])
        self.assertNotIn("harness/config/harness.json", lk["managed"])
        settings = json.loads((repo / ".claude/settings.json").read_text())
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 1)

    def test_install_keeps_existing_project_files(self):
        own_hook = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
        repo = make_repo({"CLAUDE.md": "# Mine\n\nmy map\n",
                          ".claude/settings.json": json.dumps({"permissions": {"allow": ["Bash(ls)"]},
                                                               "hooks": {"PreToolUse": [own_hook]}})})
        r = cli(make_kit(), "install", str(repo))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (repo / "CLAUDE.md").read_text()
        self.assertTrue(text.startswith("# Mine\n\nmy map\n"))
        self.assertEqual(text.count("<!-- harness:begin"), 1)
        self.assertIn("@harness/core/rules.md", text)
        settings = json.loads((repo / ".claude/settings.json").read_text())
        self.assertEqual(settings["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(settings["hooks"]["PreToolUse"][0], own_hook)
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 2)

    def test_install_twice_refuses(self):
        kit, repo = make_kit(), make_repo()
        cli(kit, "install", str(repo))
        self.assertEqual(cli(kit, "install", str(repo)).returncode, 2)

    def test_not_a_git_repository(self):
        plain = Path(tempfile.mkdtemp())
        self.assertEqual(cli(make_kit(), "install", str(plain)).returncode, 2)


class Upgrade(unittest.TestCase):
    def setUp(self):
        self.kit, self.repo = make_kit(), make_repo()
        r = cli(self.kit, "install", str(self.repo))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def kit_file(self, rel: str) -> Path:
        return self.kit / "payload" / rel

    def test_nothing_new(self):
        r = cli(self.kit, "upgrade", str(self.repo))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("update", r.stdout.replace("(update", ""))

    def test_untouched_kit_file_is_updated_and_changelog_shown(self):
        self.kit_file(GATES).write_text(self.kit_file(GATES).read_text() + "\n# v2\n")
        release(self.kit, NEXT, "[+] gates v2")
        r = cli(self.kit, "upgrade", str(self.repo))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("[+] gates v2", r.stdout)
        self.assertTrue((self.repo / GATES).read_text().endswith("# v2\n"))
        self.assertEqual(lock(self.repo)["version"], NEXT)
        self.assertEqual(cli(self.kit, "status", str(self.repo)).returncode, 0)

    def test_local_edit_is_kept_as_a_conflict(self):
        (self.repo / GATES).write_text((self.repo / GATES).read_text() + "\n# local\n")
        self.kit_file(GATES).write_text(self.kit_file(GATES).read_text() + "\n# v2\n")
        release(self.kit, NEXT)
        r = cli(self.kit, "upgrade", str(self.repo))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("conflict", r.stdout)
        self.assertTrue((self.repo / GATES).read_text().endswith("# local\n"))
        self.assertTrue((self.repo / (GATES + ".harness-new")).read_text().endswith("# v2\n"))
        st = cli(self.kit, "status", str(self.repo))
        self.assertEqual(st.returncode, 1)
        self.assertIn("unresolved conflicts: 1", st.stdout)
        # Resolved by taking the kit version: the next upgrade is clean.
        shutil.move(self.repo / (GATES + ".harness-new"), self.repo / GATES)
        self.assertEqual(cli(self.kit, "upgrade", str(self.repo)).returncode, 0)
        self.assertEqual(cli(self.kit, "status", str(self.repo)).returncode, 0)

    def test_a_conflict_never_turns_into_a_silent_overwrite(self):
        (self.repo / GATES).write_text("# local only\n")
        release(self.kit, NEXT)
        self.assertEqual(cli(self.kit, "upgrade", str(self.repo)).returncode, 1)
        (self.repo / (GATES + ".harness-new")).unlink()
        self.assertEqual(cli(self.kit, "upgrade", str(self.repo)).returncode, 1)
        self.assertEqual((self.repo / GATES).read_text(), "# local only\n")

    def test_force_replaces_and_keeps_the_local_copy(self):
        (self.repo / GATES).write_text("# local only\n")
        r = cli(self.kit, "upgrade", str(self.repo), "--force")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual((self.repo / (GATES + ".harness-old")).read_text(), "# local only\n")
        self.assertEqual((self.repo / GATES).read_text(), self.kit_file(GATES).read_text())

    def test_removed_kit_file(self):
        gone, kept = "harness/core/scripts/snapshot.py", "harness/core/scripts/agent_metrics.py"
        (self.repo / kept).write_text("# local\n")
        self.kit_file(gone).unlink()
        self.kit_file(kept).unlink()
        release(self.kit, NEXT, "[-] two scripts")
        r = cli(self.kit, "upgrade", str(self.repo))
        self.assertFalse((self.repo / gone).exists())
        self.assertTrue((self.repo / kept).exists())
        self.assertIn("orphan", r.stdout)

    def test_templates_create_new_files_and_never_overwrite(self):
        (self.repo / "harness/config/harness.json").write_text('{"project": "mine"}\n')
        tpl = self.kit_file("harness/core/templates/config/harness.json")
        tpl.write_text(tpl.read_text().replace('"my-project"', '"renamed"'))
        self.kit_file("harness/core/templates/config/extra.json").write_text("{}\n")
        release(self.kit, NEXT)
        r = cli(self.kit, "upgrade", str(self.repo))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual((self.repo / "harness/config/harness.json").read_text(), '{"project": "mine"}\n')
        self.assertIn("review   harness/config/harness.json", r.stdout)
        self.assertTrue((self.repo / "harness/config/extra.json").is_file())

    def test_migration_runs_once(self):
        mig = self.kit_file("harness/core/migrations/0001_note.py")
        mig.write_text(
            "from pathlib import Path\n"
            "def migrate(root: Path) -> list[str]:\n"
            "    p = root / 'harness/project/rules.md'\n"
            "    t = p.read_text()\n"
            "    if 'migrated' in t:\n"
            "        return []\n"
            "    p.write_text(t + '\\nmigrated\\n')\n"
            "    return ['rules.md: note added']\n")
        release(self.kit, NEXT, "[!] migration 0001")
        r = cli(self.kit, "upgrade", str(self.repo))
        self.assertIn("rules.md: note added", r.stdout)
        self.assertEqual(lock(self.repo)["schema"], 1)
        again = cli(self.kit, "upgrade", str(self.repo))
        self.assertNotIn("rules.md: note added", again.stdout)
        self.assertEqual((self.repo / "harness/project/rules.md").read_text().count("migrated"), 1)

    def test_hook_wiring_is_updated_not_duplicated(self):
        frag = self.kit_file("harness/core/settings.fragment.json")
        data = json.loads(frag.read_text())
        data["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 20
        frag.write_text(json.dumps(data))
        release(self.kit, NEXT)
        cli(self.kit, "upgrade", str(self.repo))
        settings = json.loads((self.repo / ".claude/settings.json").read_text())
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 1)
        self.assertEqual(settings["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"], 20)

    def test_hook_matcher_follows_the_kit_and_a_shared_entry_is_split(self):
        settings_path = self.repo / ".claude/settings.json"
        settings = json.loads(settings_path.read_text())
        guard_entry = settings["hooks"]["PreToolUse"][0]
        guard_entry["matcher"] = "Bash"
        settings["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": "echo mine"})
        settings["hooks"]["Stop"][0]["matcher"] = "x"
        settings_path.write_text(json.dumps(settings))
        release(self.kit, NEXT)
        r = cli(self.kit, "upgrade", str(self.repo))
        self.assertIn("matcher", r.stdout)
        settings = json.loads(settings_path.read_text())
        frag = json.loads(self.kit_file("harness/core/settings.fragment.json").read_text())
        self.assertEqual(settings["hooks"]["PreToolUse"][0]["matcher"],
                         frag["hooks"]["PreToolUse"][0]["matcher"])
        stop = settings["hooks"]["Stop"]
        # The project's own Stop hook keeps its entry; the kit hook gets its own.
        self.assertEqual(stop[0], {"matcher": "x", "hooks": [{"type": "command", "command": "echo mine"}]})
        self.assertEqual(len(stop), 2)
        self.assertNotIn("matcher", stop[1])
        self.assertIn("stop_check.py", stop[1]["hooks"][0]["command"])
        self.assertNotIn("matcher", cli(self.kit, "upgrade", str(self.repo)).stdout)

    def test_claude_md_block_is_replaced_and_the_rest_kept(self):
        text = (self.repo / "CLAUDE.md").read_text()
        (self.repo / "CLAUDE.md").write_text("# My map\n" + text)
        tpl = self.kit_file("harness/core/templates/CLAUDE.md")
        tpl.write_text(tpl.read_text().replace("@harness/project/rules.md",
                                               "@harness/project/rules.md\n@harness/project/extra.md"))
        release(self.kit, NEXT)
        cli(self.kit, "upgrade", str(self.repo))
        new = (self.repo / "CLAUDE.md").read_text()
        self.assertTrue(new.startswith("# My map\n"))
        self.assertIn("@harness/project/extra.md", new)
        self.assertEqual(new.count("<!-- harness:begin"), 1)

    def test_status_shows_versions_behind(self):
        release(self.kit, NEXT, "[+] one")
        release(self.kit, AFTER, "[+] two")
        st = cli(self.kit, "status", str(self.repo))
        self.assertIn("behind by 2 versions", st.stdout)
        self.assertIn("[+] two", st.stdout)

    def test_older_kit_refuses(self):
        old = make_kit()
        release(self.kit, NEXT)
        cli(self.kit, "upgrade", str(self.repo))
        self.assertEqual(cli(old, "upgrade", str(self.repo)).returncode, 2)


class Kit(unittest.TestCase):
    def test_versions_and_changelog_agree(self):
        version = (KIT / "VERSION").read_text().strip()
        self.assertEqual((KIT / "payload/harness/core/VERSION").read_text().strip(), version)
        self.assertIn(f"\n## {version} - ", (KIT / "CHANGELOG.md").read_text())

    def test_every_template_has_a_target(self):
        sys.path.insert(0, str(KIT))
        import harness  # noqa: PLC0415
        for p in (KIT / "payload/harness/core/templates").rglob("*"):
            if p.is_file():
                rel = p.relative_to(KIT / "payload").as_posix()
                self.assertIsNotNone(harness.template_target(rel), rel)


if __name__ == "__main__":
    unittest.main()
