"""Regression cases (A8): the case format, each expect rule firing and silent, "when",
--root, and that the output of a command is never printed or stored.

The cases live in temporary roots and run short shell lines: no network, no service.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "scripts"))
import harness_config  # noqa: E402
import regressions as rg  # noqa: E402

SCRIPT = CORE / "scripts" / "regressions.py"
TEMPLATE = CORE / "templates" / "project" / "regressions"
RDIR = harness_config.DEFAULTS["regressions"]["dir"]
CONFIRMED = {"by": "QA lead", "date": "2026-10-22", "how": "re-asked on the deployed code"}
CANARY = "CANARY-7f3a-text-of-a-record"
_TMP = tempfile.TemporaryDirectory(prefix="harness-regressions-")
BASE = Path(_TMP.name)


def tearDownModule():
    _TMP.cleanup()


def case(cid: str = "R-0001", cmd: str = "echo 42", expect: dict | None = None, **extra) -> dict:
    return {"id": cid, "ticket": "T-1", "title": "a confirmed result", "confirmed": CONFIRMED,
            "cmd": cmd, "expect": {"number": 42} if expect is None else expect, **extra}


def project(*cases) -> Path:
    """A temporary root with the given cases: dicts, or the raw text of a case file."""
    root = Path(tempfile.mkdtemp(dir=BASE))
    folder = root / RDIR
    folder.mkdir(parents=True)
    for n, c in enumerate(cases, 1):
        text = c if isinstance(c, str) else json.dumps(c)
        (folder / f"R-{n:04d}-case.json").write_text(text, encoding="utf-8")
    return root


def replay(cmd: str, expect: dict, **extra) -> tuple[str, str]:
    """(state, detail) of one case, run from its file through run()."""
    r = rg.run(project(case(cmd=cmd, expect=expect, **extra)), "all")["results"][0]
    return r["state"], r["detail"]


def cli(*argv: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = rg.main(list(argv))
    return code, buf.getvalue()


class Load(unittest.TestCase):
    def problems(self, *cases) -> str:
        with self.assertRaises(ValueError) as ctx:
            rg.load_cases(project(*cases))
        return str(ctx.exception)

    def test_valid_case_with_defaults_and_comments(self):
        c = case(_note="why the case exists", expect={"number": 42, "_source": "the ticket"})
        got = rg.load_cases(project(c))
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["when"], got[0]["file"]), ("before", RDIR + "R-0001-case.json"))
        self.assertNotIn("_note", got[0])
        self.assertEqual(got[0]["expect"], {"number": 42})

    def test_malformed_json_file(self):
        self.assertIn(RDIR + "R-0001-case.json: not valid JSON", self.problems('{"id": "R-0001",'))
        self.assertIn("a case is a JSON object", self.problems("[1, 2]"))

    def test_missing_confirmed(self):
        c = case()
        del c["confirmed"]
        self.assertIn("without a human confirmation", self.problems(c))
        self.assertIn("confirmed.by missing", self.problems(case(confirmed={"date": "2026-10-22"})))
        self.assertIn("confirmed.date", self.problems(
            case(confirmed={"by": "QA lead", "date": "22.10.2026"})))

    def test_missing_required_fields(self):
        for key in ("id", "ticket", "cmd", "expect"):
            c = case()
            del c[key]
            self.assertIn(f": {key}", self.problems(c), key)

    def test_duplicate_id(self):
        msg = self.problems(case("R-0001"), case("R-0001", cmd="echo 7", expect={"number": 7}))
        self.assertIn(f"R-0002-case.json: duplicate id R-0001, also in {RDIR}R-0001-case.json", msg)

    def test_bad_when(self):
        self.assertIn('when: before or after, not "nightly"', self.problems(case(when="nightly")))

    def test_empty_expect(self):
        self.assertIn("nothing to check", self.problems(case(expect={})))
        self.assertIn("nothing to check", self.problems(case(expect={"exit": 0})))
        # A non-zero exit alone is a rule: the command must refuse.
        self.assertEqual(len(rg.load_cases(project(case(cmd="exit 2", expect={"exit": 2})))), 1)

    def test_unknown_rule_is_an_error_not_skipped(self):
        msg = self.problems(case(expect={"number": 42, "stdout_hass": ["done"]}))
        self.assertIn("unknown rules stdout_hass", msg)

    def test_every_problem_is_listed_at_once(self):
        self.assertEqual(len(self.problems(case(when="later"), "[1,").splitlines()), 2)


class Expect(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(replay("echo 42", {"exit": 0, "number": 42}), ("pass", ""))

    def test_fail_on_exit(self):
        self.assertEqual(replay("echo 42; exit 3", {"number": 42}), ("fail", "exit 3, expected 0"))
        self.assertEqual(replay("exit 2", {"exit": 2}), ("pass", ""))

    def test_number_exact(self):
        self.assertEqual(replay("echo 41", {"number": 42}), ("fail", "expected number 42, got 41"))
        # The last non-empty line counts: a header before it and blank lines after it do not.
        self.assertEqual(replay("printf 'patients\\n42\\n\\n'", {"number": 42}), ("pass", ""))
        self.assertEqual(replay("echo 0.5", {"number": 0.5}), ("pass", ""))

    def test_number_range(self):
        rule = {"number": {"min": 40, "max": 45}}
        self.assertEqual(replay("echo 47", rule), ("fail", "expected number in 40..45, got 47"))
        self.assertEqual(replay("echo 40", rule), ("pass", ""))
        self.assertEqual(replay("echo 39", {"number": {"min": 40}}),
                         ("fail", "expected number at least 40, got 39"))

    def test_number_tolerance(self):
        rule = {"number": {"value": 100, "tolerance": 2}}
        self.assertEqual(replay("echo 103", rule), ("fail", "expected number 100 +- 2, got 103"))
        self.assertEqual(replay("echo 98.5", rule), ("pass", ""))

    def test_number_key_on_json(self):
        out = """echo '{"total": {"count": 42}, "items": [{"n": 1}, {"n": 7}]}'"""
        self.assertEqual(replay(out, {"number": 42, "number_key": "total.count"}), ("pass", ""))
        self.assertEqual(replay(out, {"number": 7, "number_key": "items.1.n"}), ("pass", ""))
        self.assertEqual(replay(out, {"number": 41, "number_key": "total.count"}),
                         ("fail", "expected number 41, got 42"))
        self.assertEqual(replay(out, {"number": 1, "number_key": "total.sum"}),
                         ("fail", "no field total.sum in the JSON"))
        self.assertEqual(replay("echo 'count: 42'", {"number": 42, "number_key": "total.count"}),
                         ("fail", "stdout is not JSON"))

    def test_json_paths(self):
        out = """echo '{"status": "done", "count": 3, "flags": {"partial": false}}'"""
        self.assertEqual(replay(out, {"json": {"status": "done", "flags.partial": False}}),
                         ("pass", ""))
        self.assertEqual(replay(out, {"json": {"count": 4}}),
                         ("fail", "json count: expected 4, got 3"))
        self.assertEqual(replay(out, {"json": {"flags.partial": 0}}),
                         ("fail", "json flags.partial: expected 0, got false"))
        self.assertEqual(replay(out, {"json": {"status": "open"}}),
                         ("fail", "json status: not the expected text"))
        self.assertEqual(replay(out, {"json": {"owner": "x"}}),
                         ("fail", "json owner: no such field"))

    def test_stdout_has(self):
        out = "echo 'refused: the condition cannot be expressed'"
        self.assertEqual(replay(out, {"stdout_has": ["refused", "cannot be expressed"]}),
                         ("pass", ""))
        self.assertEqual(replay(out, {"stdout_has": ["refused", "accepted"]}),
                         ("fail", "expected text #2 missing"))
        self.assertEqual(replay(out, {"stdout_has": ["x1", "refused", "x3"]}),
                         ("fail", "expected texts #1, #3 missing"))

    def test_stdout_lacks(self):
        self.assertEqual(replay("echo 42", {"stdout_lacks": ["Traceback"]}), ("pass", ""))
        self.assertEqual(replay("echo 'Traceback (most recent call last)'",
                                {"stdout_lacks": ["warning", "Traceback"]}),
                         ("fail", "unwanted text #2 present"))

    def test_timeout_stops_the_command_and_its_children(self):
        root = project(case(cmd="echo $$ > pid.txt; sleep 5; echo 42", timeout_s=0.5))
        began = time.monotonic()
        r = rg.run(root)["results"][0]
        self.assertEqual((r["state"], r["detail"]), ("fail", "timeout after 0.5 s"))
        self.assertLess(time.monotonic() - began, 4)
        group = int((root / "pid.txt").read_text())  # the shell leads its own group
        for _ in range(40):
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the sleeping child outlived the timeout")

    def test_not_a_number(self):
        self.assertEqual(replay("echo forty-two", {"number": 42}), ("fail", "not a number"))
        self.assertEqual(replay("true", {"number": 42}), ("fail", "no output, expected a number"))
        self.assertEqual(replay("""echo '{"n": "many"}'""", {"number": 42, "number_key": "n"}),
                         ("fail", "n is not a number"))


class Run(unittest.TestCase):
    def test_when_filtering(self):
        root = project(case("R-0001"), case("R-0002", when="after"), case("R-0003", when="before"))

        def ids(when: str) -> list[str]:
            return [r["id"] for r in rg.run(root, when)["results"]]

        self.assertEqual(ids("before"), ["R-0001", "R-0003"])
        self.assertEqual(ids("after"), ["R-0002"])
        self.assertEqual(ids("all"), ["R-0001", "R-0002", "R-0003"])
        with self.assertRaises(ValueError):
            rg.run(root, "nightly")

    def test_no_cases_exit_0_with_the_message(self):
        no_folder = Path(tempfile.mkdtemp(dir=BASE))
        readme_only = project()
        (readme_only / RDIR / "README.md").write_text("# Regression cases\n", encoding="utf-8")
        only_after = project(case(when="after"))
        for root in (no_folder, readme_only, only_after):
            out = rg.run(root)
            self.assertEqual((out["cases"], out["failed"], out["errors"]), (0, [], []))
            self.assertEqual(cli("--root", str(root)), (0, "no regression cases (when=before)\n"))
        code, text = cli("--root", str(no_folder), "--json")
        self.assertEqual((code, json.loads(text)["cases"]), (0, 0))

    def test_root_sets_where_cases_are_read_and_commands_run(self):
        root = project(case("R-0001", cmd="cat answer.txt"),
                       case("R-0002", cmd="cat answer.txt", expect={"number": 7}, cwd="sub"))
        (root / "answer.txt").write_text("42\n", encoding="utf-8")
        (root / "sub").mkdir()
        (root / "sub" / "answer.txt").write_text("7\n", encoding="utf-8")
        code, text = cli("--root", str(root))
        self.assertEqual(code, 0, text)
        self.assertEqual(text.splitlines()[:2], ["pass  R-0001  T-1", "pass  R-0002  T-1"])

    def test_missing_cwd_is_an_error(self):
        out = rg.run(project(case(cwd="gone")))
        self.assertEqual(out["errors"], ["R-0001"])
        self.assertEqual(out["results"][0]["detail"], "no folder gone")

    def test_cli_lines_summary_and_exit_codes(self):
        root = project(case("R-0001"), case("R-0002", cmd="echo 41"))
        code, text = cli("--root", str(root))
        self.assertEqual(code, 1)
        self.assertEqual(text.splitlines(), [
            "pass  R-0001  T-1",
            "FAIL  R-0002  T-1: expected number 42, got 41",
            "regressions (when=before): 1 of 2 pass; failed: R-0002"])
        data = json.loads(cli("--root", str(root), "--json")[1])
        self.assertEqual((data["cases"], data["passed"], data["failed"], data["errors"]),
                         (2, 1, ["R-0002"], []))
        code, text = cli("--root", str(project("{")))
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", text)
        code, text = cli("--root", str(project("{")), "--json")
        self.assertEqual((code, len(json.loads(text)["malformed"])), (2, 1))


class Privacy(unittest.TestCase):
    def test_canary_never_printed_or_stored(self):
        say = f"echo {CANARY}; echo {CANARY} >&2"
        root = project(
            case("R-0001", f"{say}; exit 1"),
            case("R-0002", f"{say}; echo 41"),
            case("R-0003", f"""echo '{{"name": "{CANARY}"}}'; echo {CANARY} >&2""",
                 {"json": {"name": "someone else"}, "number": 1, "number_key": "name"}),
            case("R-0004", say, {"stdout_lacks": [CANARY], "stdout_has": ["absent"]}),
            case("R-0005", f"{say}; sleep 5", timeout_s=0.2),
        )
        files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        summary = rg.run(root, "all")
        self.assertEqual(len(summary["failed"]), 5)
        self.assertNotIn(CANARY, json.dumps(summary))
        for extra in ([], ["--json"]):
            # A separate process: output that leaked through an inherited stream would
            # show here, where redirect_stdout would miss it.
            done = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--when", "all", *extra],
                capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("R-0004", done.stdout)
            self.assertNotIn(CANARY, done.stdout + done.stderr)
        self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob("*")), files,
                         "a replay stores nothing")


class Template(unittest.TestCase):
    def test_readme_template_exists_and_holds_no_case(self):
        self.assertTrue((TEMPLATE / "README.md").is_file())
        self.assertEqual(sorted(TEMPLATE.rglob("*.json")), [], "every .json there runs as a case")

    def test_readme_example_is_a_valid_case(self):
        text = (TEMPLATE / "README.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json\n(.*?)```", text, re.S)
        self.assertTrue(blocks, "no JSON example in the README")
        self.assertEqual(rg.case_problems(json.loads(blocks[0])), [])


if __name__ == "__main__":
    unittest.main()
