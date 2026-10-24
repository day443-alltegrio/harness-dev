"""QG6 data invariants: every rule fires on a bad value and stays silent on a good one;
a command that fails, hangs or prints nothing is an error, never a pass (B10); config
errors stop the run; the evidence files; nothing a command prints leaves the run.

Commands are tiny shell lines on temporary project roots: no database, no network.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

CORE = Path(__file__).resolve().parents[1]
SCRIPTS = CORE / "scripts"
TEMPLATE = CORE / "templates" / "config" / "data-checks.json"
sys.path.insert(0, str(SCRIPTS))
import data_checks as dc  # noqa: E402

CANARY = "CANARY-5f1e9c"
JSON_ROWS = """echo '{"rows": 12, "empty": 0}'"""


def cli(root: Path, *args: str) -> tuple[int, str]:
    """main() on a temporary root: (exit code, stdout and stderr)."""
    out = io.StringIO()
    with mock.patch.object(dc, "ROOT", root), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(out):
        try:
            rc = dc.main(list(args))
        except SystemExit as err:  # argparse usage errors
            rc = err.code
    return rc, out.getvalue()


class Base(unittest.TestCase):
    def project(self, checks: list | None = None, settings: dict | None = None,
                raw: str | None = None) -> Path:
        """A temporary project root with harness/config/data-checks.json."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        conf = root / "harness" / "config"
        conf.mkdir(parents=True)
        text = raw if raw is not None else json.dumps({"checks": checks or []})
        (conf / "data-checks.json").write_text(text, encoding="utf-8")
        if settings is not None:
            (conf / "harness.json").write_text(json.dumps({"data_checks": settings}),
                                               encoding="utf-8")
        return root

    def result(self, cmd: str, expect: dict, **extra) -> dict:
        """The result of one check; nothing is recorded."""
        root = self.project([{"id": "c", "cmd": cmd, "expect": expect, **extra}])
        return dc.run(root, record=False)["checks"][0]

    def state(self, cmd: str, expect: dict, **extra) -> str:
        return self.result(cmd, expect, **extra)["state"]


class Rules(Base):
    def test_eq(self):
        self.assertEqual(self.state("echo 0", {"eq": 0}), "pass")
        got = self.result("echo 3", {"eq": 0})
        self.assertEqual((got["state"], got["value"], got["detail"]), ("fail", 3, "3 != 0"))

    def test_min(self):
        self.assertEqual(self.state("echo 12", {"min": 1}), "pass")
        got = self.result("echo 0", {"min": 1})
        self.assertEqual((got["state"], got["detail"]), ("fail", "0 < min 1"))

    def test_max(self):
        self.assertEqual(self.state("echo 2", {"max": 2}), "pass")
        got = self.result("echo 3", {"max": 2})
        self.assertEqual((got["state"], got["detail"]), ("fail", "3 > max 2"))

    def test_range(self):
        for out, want in (("40", "pass"), ("44", "pass"), ("41.5", "pass"),
                          ("39", "fail"), ("45", "fail")):
            self.assertEqual(self.state(f"echo {out}", {"range": [40, 44]}), want, out)
        self.assertEqual(self.result("echo 45", {"range": [40, 44]})["detail"], "45 not in 40..44")

    def test_equal(self):
        rule = {"equal": ["derived", "source"]}
        got = self.result("""echo '{"derived": 7, "source": 7}'""", rule)
        self.assertEqual((got["state"], got["values"], got["detail"]),
                         ("pass", {"derived": 7, "source": 7}, "derived 7 = source 7"))
        got = self.result("""echo '{"derived": 6, "source": 7}'""", rule)
        self.assertEqual((got["state"], got["detail"]), ("fail", "derived 6 != source 7"))

    def test_ratio_max(self):
        rule = {"ratio_max": ["wrong", "masked", 0.01]}
        self.assertEqual(self.state("""echo '{"wrong": 1, "masked": 100}'""", rule), "pass",
                         "exactly at the limit")
        got = self.result("""echo '{"wrong": 3, "masked": 100}'""", rule)
        self.assertEqual((got["state"], got["values"]), ("fail", {"wrong": 3, "masked": 100}))
        self.assertAlmostEqual(got["value"], 0.03)
        self.assertEqual(got["detail"], "wrong 3 / masked 100 = 0.03 > 0.01")

    def test_ratio_max_zero_denominator_is_an_error(self):
        got = self.result("""echo '{"wrong": 0, "masked": 0}'""",
                          {"ratio_max": ["wrong", "masked", 0.01]})
        self.assertEqual((got["state"], got["detail"]), ("error", "masked is 0: no ratio"))


class Keys(Base):
    def test_key_picks_a_field_of_json_output(self):
        got = self.result(JSON_ROWS, {"eq": 0}, key="empty")
        self.assertEqual((got["state"], got["value"], got["values"]), ("pass", 0, None))
        self.assertEqual(self.state(JSON_ROWS, {"min": 1}, key="rows"), "pass")
        got = self.result(JSON_ROWS, {"max": 10}, key="rows")
        self.assertEqual((got["state"], got["detail"]), ("fail", "rows 12 > max 10"))

    def test_json_output_without_key_is_an_error(self):
        got = self.result(JSON_ROWS, {"min": 1})
        self.assertEqual((got["state"], got["detail"]), ("error", 'JSON output without "key"'))

    def test_missing_key_is_an_error(self):
        got = self.result(JSON_ROWS, {"min": 1}, key="facts")
        self.assertEqual((got["state"], got["detail"]), ("error", "missing key 'facts'"))
        got = self.result(JSON_ROWS, {"equal": ["rows", "facts"]})
        self.assertEqual((got["state"], got["detail"]), ("error", "missing key 'facts'"))
        got = self.result(JSON_ROWS, {"ratio_max": ["wrong", "facts", 0.1]})
        self.assertEqual((got["state"], got["detail"]), ("error", "missing keys 'wrong', 'facts'"))

    def test_plain_number_where_fields_are_expected_is_an_error(self):
        self.assertEqual(self.state("echo 5", {"min": 1}, key="rows"), "error")
        self.assertEqual(self.state("echo 5", {"equal": ["a", "b"]}), "error")


class Empty(Base):
    def test_non_zero_exit_is_an_error_even_with_a_number(self):
        got = self.result("echo 5; exit 2", {"min": 1})
        self.assertEqual((got["state"], got["value"], got["detail"]), ("error", None, "exit 2"))

    def test_timeout_is_an_error(self):
        began = time.monotonic()
        got = self.result("echo 1; sleep 5; echo 2", {"min": 1}, timeout_s=0.2)
        self.assertEqual((got["state"], got["detail"]), ("error", "timeout after 0.2 s"))
        self.assertLess(time.monotonic() - began, 3, "the timeout must not wait for the command")

    def test_timeout_stops_everything_the_command_started(self):
        # Killing only the shell would leave the subshell running to write the file.
        root = self.project([{"id": "slow", "cmd": "(sleep 0.5; touch late.txt); echo 0",
                              "expect": {"eq": 0}, "timeout_s": 0.1}])
        dc.run(root, record=False)
        time.sleep(0.8)
        self.assertFalse((root / "late.txt").exists())

    def test_default_timeout_comes_from_the_settings(self):
        root = self.project([{"id": "slow", "cmd": "sleep 5", "expect": {"eq": 0}}],
                            settings={"timeout_s": 0.2})
        got = dc.run(root, record=False)["checks"][0]
        self.assertEqual((got["state"], got["detail"]), ("error", "timeout after 0.2 s"))

    def test_no_output_is_an_error(self):
        for cmd in ("true", "printf '\\n  \\n'"):
            got = self.result(cmd, {"eq": 0})
            self.assertEqual((got["state"], got["detail"]), ("error", "no output"), cmd)

    def test_not_a_number_is_an_error(self):
        for cmd in ("echo twelve", "echo '12 rows'", "echo true", "echo NaN", "echo 1e999",
                    "echo '[1]'"):
            got = self.result(cmd, {"min": 0})
            self.assertEqual((got["state"], got["detail"]), ("error", "not a number"), cmd)
        got = self.result("""echo '{"rows": true}'""", {"min": 0}, key="rows")
        self.assertEqual((got["state"], got["detail"]), ("error", "JSON value not a number"),
                         "booleans are not numbers")
        for cmd in ("""echo '{"rows": "12"}'""", """echo '{"rows": null}'""",
                    """echo '{"rows": {"n": 1}}'""", """echo '{"rows": NaN}'""",
                    """echo '{"rows": 1'"""):
            self.assertEqual(self.state(cmd, {"min": 0}, key="rows"), "error", cmd)

    def test_last_non_empty_line_is_the_result(self):
        got = self.result("echo header; echo 5; echo", {"eq": 5})
        self.assertEqual((got["state"], got["value"]), ("pass", 5))
        got = self.result("echo 0.25", {"max": 0.5})
        self.assertEqual((got["state"], got["value"]), ("pass", 0.25))

    def test_no_checks_is_not_a_pass(self):
        rc, out = cli(self.project([]))
        self.assertEqual(rc, 1)
        self.assertIn("no data checks in harness/config/data-checks.json:"
                      " an empty check is not a pass", out)


class DropMax(Base):
    def setUp(self):
        self.root = self.project([
            {"id": "rows", "pattern": "B8", "cmd": "cat rows.txt", "expect": {"drop_max": 0.1}},
            {"id": "other", "cmd": "echo 5", "expect": {"min": 0}}])

    def step(self, value: int, record: bool = True, root: Path | None = None) -> dict:
        root = root or self.root
        (root / "rows.txt").write_text(f"{value}\n", encoding="utf-8")
        return dc.run(root, record=record)["checks"][0]

    def history(self, root: Path | None = None) -> list[dict]:
        path = (root or self.root) / dc.HISTORY
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]

    def test_first_run_records_a_baseline(self):
        got = self.step(1000)
        self.assertEqual((got["state"], got["detail"]), ("pass", "1000, baseline recorded"))

    def test_sharp_drop_fails_and_a_small_one_passes(self):
        self.step(1000)
        got = self.step(900)
        self.assertEqual((got["state"], got["detail"]), ("pass", "900 >= 1000 * (1 - 0.1)"),
                         "exactly at the limit")
        got = self.step(800)
        self.assertEqual((got["state"], got["detail"]),
                         ("fail", "800 < 900 * (1 - 0.1); if the new level is right:"
                                  " data_checks.py --accept rows --reason ..."))

    def test_sustained_drop_fails_on_every_run(self):
        # A failing value never becomes the norm (B10: a quiet wrong number).
        self.step(1000)
        for _ in range(2):
            got = self.step(700)
            self.assertEqual(got["state"], "fail")
            self.assertTrue(got["detail"].startswith("700 < 1000 * (1 - 0.1);"), got["detail"])
        self.assertEqual([h["state"] for h in self.history() if h["id"] == "rows"],
                         ["pass", "fail", "fail"])

    def test_accept_makes_the_new_level_the_baseline(self):
        self.step(1000)
        self.step(700)
        rc, out = cli(self.root, "--accept", "rows", "--reason", "old rows archived on purpose")
        self.assertEqual((rc, out.strip()), (0, "accepted B8 rows: new baseline 700 (was 1000)"))
        last = {k: v for k, v in self.history()[-1].items() if k != "at"}
        self.assertEqual(last, {"id": "rows", "value": 700, "state": "accepted",
                                "reason": "old rows archived on purpose"})
        got = self.step(700)
        self.assertEqual((got["state"], got["detail"]), ("pass", "700 >= 700 * (1 - 0.1)"))
        self.assertEqual(self.step(600)["state"], "fail", "the accepted level is the new norm")

    def test_accept_without_reason_unknown_id_or_fixed_rule_is_refused(self):
        self.step(1000)
        for args, want in ((["--accept", "rows"], "needs a reason"),
                           (["--accept", "rows", "--reason", " "], "needs a reason"),
                           (["--accept", "nope", "--reason", "x"], "no check 'nope'"),
                           (["--accept", "other", "--reason", "x"], "only drop_max")):
            rc, out = cli(self.root, *args)
            self.assertEqual(rc, 2, args)
            self.assertIn("refused: ", out, args)
            self.assertIn(want, out, args)
        with self.assertRaises(ValueError):
            dc.accept(self.root, ["rows"], "")
        self.assertNotIn("accepted", [h["state"] for h in self.history()])

    def test_accept_of_an_erroring_check_is_refused_and_records_nothing(self):
        root = self.project([{"id": "rows", "cmd": "cat rows.txt", "expect": {"drop_max": 0.1}},
                             {"id": "broken", "cmd": "exit 3", "expect": {"drop_max": 0.1}}])
        self.step(1000, root=root)
        before = (root / dc.HISTORY).read_text(encoding="utf-8")
        rc, out = cli(root, "--accept", "rows,broken", "--reason", "new level")
        self.assertEqual(rc, 1)
        self.assertIn("refused: broken: exit 3; nothing accepted", out)
        self.assertEqual((root / dc.HISTORY).read_text(encoding="utf-8"), before,
                         "nothing accepted, not even the check that ran")
        with self.assertRaises(dc.Refused):
            dc.accept(root, ["broken"], "new level")

    def test_old_history_lines_without_state_are_baselines(self):
        path = self.root / dc.HISTORY
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"at": "2026-10-01T03:00:00", "id": "rows", "value": 1000})
                        + "\n", encoding="utf-8")
        got = self.step(850)
        self.assertEqual(got["state"], "fail")
        self.assertTrue(got["detail"].startswith("850 < 1000 * (1 - 0.1);"), got["detail"])
        self.assertEqual(self.step(950)["state"], "pass", "still compared with the old line")

    def test_failing_streak_longer_than_the_history_keeps_its_baseline(self):
        root = self.project([{"id": "rows", "cmd": "cat rows.txt", "expect": {"drop_max": 0.1}}],
                            settings={"history_keep": 2})
        self.step(1000, root=root)
        for _ in range(3):
            got = self.step(500, root=root)
        self.assertTrue(got["detail"].startswith("500 < 1000 * (1 - 0.1);"), got["detail"])
        self.assertEqual([h["value"] for h in self.history(root)], [1000, 500, 500])

    def test_value_at_the_limit_passes_despite_float_rounding(self):
        # 10 * (1 - 0.7) is 3.0000000000000004 in floats.
        root = self.project([{"id": "rows", "cmd": "cat rows.txt", "expect": {"drop_max": 0.7}}])
        self.step(10, root=root)
        self.assertEqual(self.step(2, record=False, root=root)["state"], "fail")
        self.assertEqual(self.step(3, root=root)["state"], "pass")

    def test_baseline_is_the_last_value_of_the_same_check(self):
        dc.run(self.root, only=["other"])
        self.assertEqual(self.step(1000)["detail"], "1000, baseline recorded")

    def test_without_record_no_baseline_is_kept(self):
        got = self.step(1000, record=False)
        self.assertEqual((got["state"], got["detail"]), ("pass", "1000, no baseline yet"))
        self.step(1000)
        self.assertEqual(self.step(500, record=False)["state"], "fail")
        self.assertEqual(self.step(950)["state"], "pass", "the run without record kept 1000")


class Config(Base):
    OK = {"id": "a", "cmd": "echo 0", "expect": {"eq": 0}}

    def problems(self, data: dict | str, settings: dict | None = None) -> str:
        raw = data if isinstance(data, str) else json.dumps(data)
        root = self.project(raw=raw, settings=settings)
        with self.assertRaises(ValueError) as ctx:
            dc.load_checks(root)
        return str(ctx.exception)

    def test_missing_fields(self):
        for field in ("id", "cmd", "expect"):
            check = {k: v for k, v in self.OK.items() if k != field}
            self.assertIn(f'missing "{field}"', self.problems({"checks": [check]}))

    def test_duplicate_id(self):
        self.assertIn("duplicate id 'a'", self.problems({"checks": [self.OK, dict(self.OK)]}))

    def test_unknown_rule(self):
        msg = self.problems({"checks": [{**self.OK, "expect": {"atleast": 1}}]})
        self.assertIn("unknown rule 'atleast'", msg)

    def test_exactly_one_rule(self):
        msg = self.problems({"checks": [{**self.OK, "expect": {"min": 1, "max": 5}}]})
        self.assertIn("2 rules (min, max)", msg)
        self.assertIn("no rule", self.problems({"checks": [{**self.OK, "expect": {}}]}))

    def test_bad_rule_arguments(self):
        for expect in ({"eq": "0"}, {"min": True}, {"max": None}, {"range": [5, 1]},
                       {"range": [1]}, {"equal": ["a", "a"]}, {"equal": "a"},
                       {"ratio_max": ["a", "b"]}, {"ratio_max": ["a", "b", -0.1]},
                       {"drop_max": 0}, {"drop_max": 1}, {"drop_max": 20}):
            with self.subTest(expect=expect):
                self.problems({"checks": [{**self.OK, "expect": expect}]})

    def test_unknown_and_misplaced_keys(self):
        self.assertIn("unknown key 'timeout'", self.problems({"checks": [{**self.OK, "timeout": 5}]}))
        misplaced = {**self.OK, "expect": {"equal": ["a", "b"]}, "key": "a"}
        self.assertIn('"key" is not used by equal', self.problems({"checks": [misplaced]}))
        self.assertIn("unknown top-level key 'examples'",
                      self.problems({"checks": [], "examples": [self.OK]}))
        self.assertIn('"pattern"', self.problems({"checks": [{**self.OK, "pattern": "b4"}]}))
        self.assertIn('"id"', self.problems({"checks": [{**self.OK, "id": "a,b"}]}))

    def test_every_problem_is_named(self):
        msg = self.problems({"checks": [{"id": "a", "expect": {"eq": 0}},
                                        {"id": "b", "cmd": "true", "expect": {"nope": 1}}]})
        self.assertIn("check 'a': missing \"cmd\"", msg)
        self.assertIn("check 'b': unknown rule 'nope'", msg)

    def test_comments_are_ignored(self):
        root = self.project(raw=json.dumps({
            "_comment": "x", "_examples": [{"broken": True}],
            "checks": [{"_why": "y", **self.OK, "expect": {"eq": 0, "_note": "z"}}]}))
        checks = dc.load_checks(root)
        self.assertEqual([(c["id"], c["expect"]) for c in checks], [("a", {"eq": 0})])

    def test_bad_file_and_bad_settings(self):
        self.assertIn("not valid JSON", self.problems("{not json"))
        self.assertIn('"checks" list', self.problems({"_comment": "no checks key"}))
        self.assertIn("history_keep", self.problems({"checks": []}, settings={"history_keep": 0}))
        root = self.project([self.OK])
        (root / "harness" / "config" / "data-checks.json").unlink()
        with self.assertRaises(ValueError):
            dc.load_checks(root)

    def test_config_error_exits_2(self):
        rc, out = cli(self.project([{"id": "a"}]))
        self.assertEqual(rc, 2)
        self.assertIn("config error: harness/config/data-checks.json: check 'a': missing \"cmd\"",
                      out)


class Evidence(Base):
    CHECKS = [
        {"id": "a", "pattern": "B8", "cmd": "echo 3", "expect": {"min": 1}},
        {"id": "b", "cmd": """echo '{"in": 5, "out": 5, "other": 1}'""",
         "expect": {"equal": ["in", "out"]}},
        {"id": "c", "cmd": "exit 1", "expect": {"eq": 0}},
    ]

    def history(self, root: Path) -> list[dict]:
        path = root / "harness" / ".state" / "data-history.jsonl"
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]

    def test_record_writes_the_report_and_the_history(self):
        root = self.project(self.CHECKS)
        rep = dc.run(root)
        self.assertEqual(rep["summary"], {"total": 3, "passed": 2, "failed": 0, "errors": 1})
        self.assertEqual(set(rep["checks"][0]),
                         {"id", "pattern", "title", "state", "value", "values", "detail"})
        self.assertEqual(dc.last_report(root), rep)
        hist = self.history(root)
        self.assertEqual([{k: v for k, v in h.items() if k != "at"} for h in hist],
                         [{"id": "a", "value": 3, "state": "pass"},
                          {"id": "b", "values": {"in": 5, "out": 5}, "state": "pass"}],
                         "one line per check with a number, only the fields the rule names")
        self.assertTrue(all(h["at"] == rep["at"] for h in hist))

    def test_no_record_writes_nothing(self):
        root = self.project(self.CHECKS)
        dc.run(root, record=False)
        self.assertFalse((root / "harness" / ".state").exists())
        self.assertIsNone(dc.last_report(root))

    def test_history_keeps_the_newest_lines(self):
        counter = "n=$(cat n.txt 2>/dev/null || echo 0); n=$((n + 1)); echo $n > n.txt; echo $n"
        root = self.project([{"id": "n", "cmd": counter, "expect": {"min": 1}}],
                            settings={"history_keep": 2})
        for _ in range(3):
            dc.run(root)
        self.assertEqual([h["value"] for h in self.history(root)], [2, 3])


class Cli(Base):
    CHECKS = [
        {"id": "facts-version", "pattern": "B4", "cmd": """echo '{"derived": 7, "source": 7}'""",
         "expect": {"equal": ["derived", "source"]}},
        {"id": "search-nonempty", "pattern": "B8", "cmd": "echo 0", "expect": {"min": 1}},
        {"id": "rows-in-out", "pattern": "B9", "cmd": "exit 2", "expect": {"equal": ["in", "out"]}},
    ]

    def test_one_line_per_check_and_a_summary(self):
        rc, out = cli(self.project(self.CHECKS))
        self.assertEqual(rc, 1)
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), "pass B4 facts-version derived 7 = source 7".split())
        self.assertEqual(lines[1], "FAIL   B8  search-nonempty  0 < min 1")
        self.assertEqual(lines[2].split(), "error B9 rows-in-out exit 2".split())
        self.assertEqual(lines[3], "data checks: 1 of 3 pass, 1 failed, 1 error")

    def test_exit_0_only_when_every_check_passes(self):
        root = self.project(self.CHECKS)
        self.assertEqual(cli(root, "--only", "facts-version")[0], 0)
        self.assertEqual(cli(root, "--only", "facts-version,search-nonempty")[0], 1)
        self.assertEqual(cli(root, "--only", "rows-in-out")[0], 1)

    def test_json_only_and_no_record(self):
        root = self.project(self.CHECKS)
        rc, out = cli(root, "--only", "search-nonempty", "--json", "--no-record")
        rep = json.loads(out)
        self.assertEqual((rc, [c["id"] for c in rep["checks"]]), (1, ["search-nonempty"]))
        self.assertEqual(rep["summary"], {"total": 1, "passed": 0, "failed": 1, "errors": 0})
        self.assertFalse((root / "harness" / ".state").exists())

    def test_unknown_id_in_only_is_a_config_error(self):
        rc, out = cli(self.project(self.CHECKS), "--only", "nope")
        self.assertEqual(rc, 2)
        self.assertIn("no check 'nope'", out)


class Privacy(Base):
    def test_command_output_never_leaves_the_run(self):
        loud = f"echo {CANARY}; echo {CANARY} >&2"
        root = self.project([
            {"id": "pass-after-text", "cmd": f"{loud}; echo 5", "expect": {"min": 1}},
            {"id": "exit", "cmd": f"{loud}; exit 3", "expect": {"min": 1}},
            {"id": "text-result", "cmd": f"echo {CANARY} >&2; echo {CANARY}", "expect": {"min": 1}},
            {"id": "text-value", "cmd": f"echo '{{\"rows\": \"{CANARY}\"}}'",
             "expect": {"min": 1}, "key": "rows"},
            {"id": "text-key", "cmd": f"echo '{{\"in\": 2, \"out\": 2, \"{CANARY}\": 9}}'",
             "expect": {"equal": ["in", "out"]}},
            {"id": "broken-json", "cmd": f"echo '{{\"{CANARY}'", "expect": {"eq": 0}},
            {"id": "slow", "cmd": f"{loud}; sleep 5", "expect": {"eq": 0}, "timeout_s": 0.3},
            {"id": "drop-loud", "cmd": f"{loud}; echo 7", "expect": {"drop_max": 0.5}},
            {"id": "drop-broken", "cmd": f"{loud}; exit 4", "expect": {"drop_max": 0.5}},
        ])
        # The real CLI in its own process, so output written straight to the file
        # descriptors would show too.
        scripts = root / "harness" / "core" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("data_checks.py", "harness_config.py"):
            shutil.copy2(SCRIPTS / name, scripts / name)
        seen = []
        for args, want in (([], 1), (["--json"], 1),
                           (["--accept", "drop-loud", "--reason", "test"], 0),
                           (["--accept", "drop-broken", "--reason", "test"], 1)):
            done = subprocess.run([sys.executable, str(scripts / "data_checks.py"), *args],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, want, args)
            seen += [done.stdout, done.stderr]
        states = {c["id"]: c["state"] for c in json.loads(seen[2])["checks"]}
        self.assertEqual(states, {"pass-after-text": "pass", "exit": "error",
                                  "text-result": "error", "text-value": "error",
                                  "text-key": "pass", "broken-json": "error", "slow": "error",
                                  "drop-loud": "pass", "drop-broken": "error"})
        self.assertEqual(seen[4].strip(), "accepted drop-loud: new baseline 7 (was 7)")
        self.assertEqual(seen[6].strip(), "refused: drop-broken: exit 4; nothing accepted")
        state = root / "harness" / ".state"
        seen += [(state / "data-checks.json").read_text(encoding="utf-8"),
                 (state / "data-history.jsonl").read_text(encoding="utf-8")]
        for text in seen:
            self.assertNotIn(CANARY, text)

    def test_crash_in_a_check_is_an_error_without_its_message(self):
        # An exception message may quote what the command printed.
        with mock.patch.object(dc, "parse", side_effect=ValueError(f"bad line {CANARY}")):
            got = self.result("echo 5", {"min": 1})
        self.assertEqual((got["state"], got["detail"]), ("error", "check did not run: ValueError"))


class Template(Base):
    def test_kit_template_is_valid_and_has_no_active_checks(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(data["checks"], [], "the kit never ships an active check")
        self.assertEqual(dc.load_checks(self.project(raw=text)), [])
        examples = dc.load_checks(self.project(data["_examples"]))  # every example is valid
        self.assertEqual(len(examples), len(data["_examples"]))
        self.assertLessEqual({"B1", "B2", "B4", "B5", "B6", "B8", "B9", "B11"},
                             {c["pattern"] for c in examples})
        self.assertEqual({next(iter(c["expect"])) for c in examples}, set(dc.RULES),
                         "every rule has an example")
        rc, out = cli(self.project(raw=text))
        self.assertEqual(rc, 1)
        self.assertIn("an empty check is not a pass", out)


if __name__ == "__main__":
    unittest.main()
