"""Sandbox settings: rendered from sandbox.json, written without touching the rest, checked."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import harness_config  # noqa: E402
import sandbox_config as sc  # noqa: E402

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "config" / "sandbox.json"


def project(sandbox: dict | None, settings: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "harness" / "config").mkdir(parents=True)
    if sandbox is not None:
        (root / "harness" / "config" / "sandbox.json").write_text(json.dumps(sandbox))
    (root / ".claude").mkdir()
    if settings is not None:
        (root / ".claude" / "settings.json").write_text(json.dumps(settings))
    return root


class Sandbox(unittest.TestCase):
    def test_render_closes_the_escape_hatch(self):
        block = sc.render({**sc.DEFAULTS, "enabled": True, "required": True,
                           "allowed_domains": ["github.com"], "deny_read": ["~/.ssh"]})
        self.assertEqual(block["allowUnsandboxedCommands"], False)
        self.assertEqual(block["failIfUnavailable"], True)
        self.assertEqual(block["network"]["allowedDomains"], ["github.com"])
        self.assertEqual(block["filesystem"], {"denyRead": ["~/.ssh"]})
        self.assertNotIn("excludedCommands", block)

    def test_apply_keeps_the_rest_of_the_settings_and_check_follows(self):
        root = project({"enabled": True, "allowed_domains": ["pypi.org"]},
                       {"hooks": {"Stop": []}, "permissions": {"deny": ["Read(**/.env)"]}})
        self.assertFalse(sc.check(root)[0])
        sc.apply(root)
        data = json.loads((root / ".claude" / "settings.json").read_text())
        self.assertEqual(data["permissions"], {"deny": ["Read(**/.env)"]})
        self.assertEqual(data["sandbox"]["network"]["allowedDomains"], ["pypi.org"])
        ok, line = sc.check(root)
        self.assertTrue(ok)
        self.assertIn("1 allowed domains", line)
        data["sandbox"]["network"]["allowedDomains"].append("evil.example")
        (root / ".claude" / "settings.json").write_text(json.dumps(data))
        self.assertFalse(sc.check(root)[0])

    def test_off_is_in_order_unless_settings_still_have_it_on(self):
        self.assertTrue(sc.check(project(None, {}))[0])
        self.assertFalse(sc.check(project({"enabled": False}, {"sandbox": {"enabled": True}}))[0])

    def test_unknown_key_is_an_error(self):
        root = project({"enable": True})
        with self.assertRaises(ValueError):
            sc.load(root)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(sc.main(["--check"], root), 2)

    def test_suggest_counts_hosts_only(self):
        proj = Path(tempfile.mkdtemp())
        now = datetime.now().isoformat()

        def use(name: str, args: dict) -> str:
            return json.dumps({"type": "assistant", "timestamp": now, "message": {"content": [
                {"type": "tool_use", "name": name, "input": args}]}})
        (proj / "s.jsonl").write_text("\n".join([
            use("Bash", {"command": "curl -s https://api.github.com/repos/o/r?token=SECRET123"}),
            use("Bash", {"command": "git clone git@github.com:o/r.git && pip install -i https://pypi.org/simple x"}),
            use("Bash", {"command": "echo https://not-a-network-command.example"}),
            use("WebFetch", {"url": "https://docs.example.org/page", "prompt": "summarize"}),
        ]))
        seen = sc.suggest(proj, 30)
        self.assertEqual(seen, {"api.github.com": 1, "github.com": 1, "pypi.org": 1, "docs.example.org": 1})
        self.assertNotIn("SECRET123", json.dumps(seen))

    def test_template_renders(self):
        conf = {**sc.DEFAULTS, **{k: v for k, v in json.loads(TEMPLATE.read_text()).items()
                                  if not k.startswith("_")}}
        block = sc.render(conf)
        self.assertFalse(block["enabled"])
        self.assertIn("github.com", block["network"]["allowedDomains"])
        self.assertEqual(harness_config.DEFAULTS["sandbox"]["file"], "harness/config/sandbox.json")


if __name__ == "__main__":
    unittest.main()
