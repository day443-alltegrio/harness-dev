"""Task contract: when it is needed and what it must contain."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import contract_check as cc  # noqa: E402
import harness_config  # noqa: E402

SECTIONS = harness_config.DEFAULTS["contracts"]["sections"]
CDIR = harness_config.DEFAULTS["contracts"]["dir"]
FULL = "# Contract: x\n" + "\n".join(f"{s}\n\ntext\n" for s in SECTIONS)


def bare_root(conf: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    if conf is not None:
        (root / "harness" / "config").mkdir(parents=True)
        (root / "harness" / "config" / "harness.json").write_text(json.dumps(conf))
    return root


class Reasons(unittest.TestCase):
    def setUp(self):
        self.root = bare_root()

    def test_small_change_needs_none(self):
        self.assertEqual(cc.reasons(["web/src/Pager.tsx", "web/src/locales/en.json"], self.root), [])

    def test_schema_change_needs_contract(self):
        self.assertIn("database schema", cc.reasons(["migrations/0007_users.sql"], self.root))

    def test_deploy_script_needs_contract(self):
        self.assertIn("deploy scripts", cc.reasons(["deploy/app-sync.sh"], self.root))

    def test_many_files_need_contract(self):
        self.assertTrue(cc.reasons([f"web/src/f{i}.tsx" for i in range(31)], self.root))

    def test_generated_files_do_not_count(self):
        root = bare_root({"generated": ["web/dist/"]})
        self.assertEqual(cc.reasons([f"web/dist/f{i}.js" for i in range(200)], root), [])

    def test_project_risky_paths(self):
        root = bare_root({"contracts": {"risky": [{"match": "^pipelines/", "label": "data pipeline"}]}})
        self.assertEqual(cc.reasons(["pipelines/etl.py"], root), ["data pipeline"])


class Contracts(unittest.TestCase):
    def root(self, text: str | None) -> Path:
        root = bare_root()
        if text is not None:
            p = root / CDIR / "2026-10-21-x.md"
            p.parent.mkdir(parents=True)
            p.write_text(text, encoding="utf-8")
        return root

    def test_missing_contract(self):
        self.assertTrue(cc.contract_problems(self.root(None), ["migrations/a.sql"]))

    def test_contract_without_sections(self):
        root = self.root("# Contract\n\n## Goal\n\nsomething\n")
        files = [CDIR + "2026-10-21-x.md"]
        self.assertTrue(any("missing sections" in p for p in cc.contract_problems(root, files)))

    def test_full_contract_passes(self):
        self.assertEqual(cc.contract_problems(self.root(FULL), [CDIR + "2026-10-21-x.md"]), [])

    def contract(self, state: str, criteria: str) -> str:
        body = {s: "text" for s in SECTIONS}
        body["## Acceptance criteria"] = criteria
        return f"# Contract: x\n\n- State: {state}\n\n" + "\n".join(f"{s}\n\n{v}\n" for s, v in body.items())

    def test_done_contract_names_a_check(self):
        files = [CDIR + "2026-10-21-x.md"]
        root = self.root(self.contract("done", "It works well."))
        self.assertTrue(any("name no check" in p for p in cc.contract_problems(root, files)))
        root = self.root(self.contract("done", "`sh harness/core/scripts/run.sh` is green."))
        self.assertEqual(cc.contract_problems(root, files), [])
        root = self.root(self.contract("plan", "It works well."))
        self.assertEqual(cc.contract_problems(root, files), [])

    def test_named_tests_and_cases_must_exist(self):
        files = [CDIR + "2026-10-21-x.md"]
        root = self.root(self.contract("done", "`test_real` and `test_ghost` pass; case `R-0042` holds."))
        (root / "tests").mkdir()
        (root / "tests" / "test_a.py").write_text("def test_real():\n    pass\n")
        problems = cc.contract_problems(root, files)
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("test_ghost" in p for p in problems))
        self.assertTrue(any("R-0042" in p for p in problems))
        cases = root / harness_config.DEFAULTS["regressions"]["dir"]
        cases.mkdir(parents=True)
        (cases / "R-0042-x.json").write_text('{"id": "R-0042"}')
        (root / "tests" / "test_b.py").write_text("def test_ghost():\n    pass\n")
        self.assertEqual(cc.contract_problems(root, files), [])

    def test_checkable_can_be_switched_off(self):
        root = self.root(self.contract("done", "`test_ghost` passes."))
        (root / "harness" / "config").mkdir(parents=True)
        (root / "harness" / "config" / "harness.json").write_text(json.dumps({"contracts": {"checkable": False}}))
        self.assertEqual(cc.contract_problems(root, [CDIR + "2026-10-21-x.md"]), [])

    def test_template_is_not_a_contract(self):
        self.assertTrue(cc.contract_problems(self.root(None), [CDIR + "TEMPLATE.md"]))

    def test_template_has_all_sections(self):
        conf = harness_config.load()
        text = (harness_config.ROOT / conf["contracts"]["dir"] / "TEMPLATE.md").read_text(encoding="utf-8")
        for s in conf["contracts"]["sections"]:
            self.assertIn(s, text)


if __name__ == "__main__":
    unittest.main()
