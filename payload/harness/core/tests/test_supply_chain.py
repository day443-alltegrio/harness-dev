"""Supply chain: unpinned, no lock, an unknown plugin fail; scanners that fail are failures."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import supply_chain as sc  # noqa: E402

APP = {"app": "api", "requirements": "api/requirements.txt", "lock": "api/requirements.lock.txt"}
CONF = {"supply_chain": {"python": [APP]}}


def repo(files: dict[str, str], conf: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    if conf is not None:
        files = {**files, "harness/config/harness.json": json.dumps(conf)}
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


PINNED = {"api/requirements.txt": "# comment\nfastapi==0.1\npsycopg[binary]==3.3.5\n",
          "api/requirements.lock.txt": "fastapi==0.1\n"}


class Pins(unittest.TestCase):
    def test_pinned_with_lock_passes(self):
        self.assertEqual(sc.check_pins(repo(PINNED, CONF)), [])

    def test_unpinned_fails(self):
        # Unpinned versions drifted between two machines (A3).
        root = repo({**PINNED, "api/requirements.txt": "fastapi\n"}, CONF)
        self.assertEqual(len(sc.check_pins(root)), 1)

    def test_missing_lock_fails(self):
        root = repo({"api/requirements.txt": "fastapi==0.1\n"}, CONF)
        self.assertTrue(any("lock" in p for p in sc.check_pins(root)))

    def test_nothing_configured_passes(self):
        self.assertEqual(sc.check_pins(repo({})), [])


class Plugins(unittest.TestCase):
    def settings(self, plugins: dict, allow: str = "") -> Path:
        return repo({".claude/settings.json": json.dumps({"enabledPlugins": plugins}),
                     "harness/config/plugins-allowlist.txt": allow})

    def test_unlisted_plugin_fails(self):
        self.assertEqual(len(sc.check_plugins(self.settings({"evil@x": True}))), 1)

    def test_listed_plugin_passes(self):
        root = self.settings({"good@x": True}, "plugin:good@x  reviewed 2026-10-21\n")
        self.assertEqual(sc.check_plugins(root), [])

    def test_disabled_plugin_ignored(self):
        self.assertEqual(sc.check_plugins(self.settings({"off@x": False})), [])

    def test_unlisted_mcp_fails(self):
        root = repo({".mcp.json": json.dumps({"mcpServers": {"s": {}}})})
        self.assertEqual(len(sc.check_plugins(root)), 1)


class Vulns(unittest.TestCase):
    def test_scanner_failure_is_a_failure(self):
        # B10: could not measure is not "zero vulnerabilities".
        with mock.patch.object(sc, "check_vulns", side_effect=RuntimeError("offline")), \
             mock.patch.object(sc, "check_pins", return_value=[]), \
             mock.patch.object(sc, "check_plugins", return_value=[]), \
             mock.patch.object(sc.harness_config, "load",
                               return_value={"supply_chain": {"python": [APP], "npm": []}}), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sc.main([]), 1)

    def vulns(self, severity: str, accepted: dict, apps=None):
        found = [{"package": "p", "version": "1", "id": "PYSEC-1", "aliases": ["GHSA-x"], "fix": []}]
        root = repo(PINNED, CONF)
        with mock.patch.object(sc, "pip_audit", return_value=found), \
             mock.patch.object(sc, "npm_audit", return_value=[]), \
             mock.patch.object(sc, "osv_severity", return_value=severity), \
             mock.patch.object(sc, "read_accepted", return_value=accepted):
            return sc.check_vulns(apps, today=date(2026, 10, 21), root=root)

    def test_accepted_with_future_review_passes(self):
        problems, summary = self.vulns("HIGH", {"PYSEC-1": ("2026-11-15", "reason")})
        self.assertEqual(problems, [])
        self.assertEqual(summary["accepted"], 1)

    def test_accepted_by_alias_passes(self):
        problems, _ = self.vulns("HIGH", {"GHSA-x": ("2026-11-15", "reason")})
        self.assertEqual(problems, [])

    def test_expired_review_fails(self):
        problems, _ = self.vulns("HIGH", {"PYSEC-1": ("2026-10-01", "reason")})
        self.assertTrue(any("has passed" in p for p in problems))

    def test_not_accepted_fails(self):
        problems, _ = self.vulns("MODERATE", {})
        self.assertTrue(any("not accepted" in p for p in problems))

    def test_critical_always_fails(self):
        # CRITICAL cannot be accepted: it blocks the deploy of its app.
        problems, summary = self.vulns("CRITICAL", {"PYSEC-1": ("2027-01-01", "x")})
        self.assertTrue(any("critical, blocks" in p for p in problems))
        self.assertEqual(summary["critical"], 1)

    def test_apps_filter_limits_scope(self):
        problems, summary = self.vulns("CRITICAL", {}, ["web"])
        self.assertEqual(summary["python"], 0)
        self.assertEqual(problems, [])


class Cvss(unittest.TestCase):
    def test_reference_scores(self):
        for vector, score in [("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
                              ("CVSS:3.0/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H", 7.8),
                              ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:H/I:H/A:H", 9.6),
                              ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:L/A:N", 3.7)]:
            self.assertEqual(sc.cvss3_score(vector), score, vector)

    def test_label_beats_vector(self):
        cache = {"A": {"label": "HIGH", "vectors": []},
                 "B": {"label": None, "vectors": ["CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:H/I:H/A:H"]}}
        tmp = Path(tempfile.mkdtemp()) / "c.json"
        tmp.write_text(json.dumps(cache))
        self.assertEqual(sc.osv_severity(["A", "B"], tmp), "HIGH")
        self.assertEqual(sc.osv_severity(["B"], tmp), "CRITICAL")


if __name__ == "__main__":
    unittest.main()
