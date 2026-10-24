#!/usr/bin/env python3
"""Mutation check: can the tests of the kit fail? A sensor that never fires may be blind.

For each mutant one protection is removed from a copy of the kit (harness.py in a copy
of this repository, the payload in a fresh install), the tests that guard it run and
must fail (red), then the file is restored and the same tests must pass again (green).
A mutant that survives is a protection no test watches: a gap to close with a test.
The copies live in a temporary folder; this repository is only read.

    python3 research/evidence/mutation_check.py [--only M1,M7]
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
WORK = Path(tempfile.mkdtemp(prefix="harness-mutation-"))
COPY = WORK / "kit"
REPO = WORK / "repo"
GUARD = ".claude/hooks/harness/guard.py"
S = "harness/core/scripts/"

# (id, the protection removed, where: kit|repo, file, old text, new text, test file)
MUTANTS = [
    ("M1", "guard: git reset is no longer denied", "repo", GUARD, "\\b)|reset|checkout", "\\b)|checkout",
     "test_hooks.py"),
    ("M2", "guard: the Read tool may open secret files", "repo", GUARD,
     '        if self.on["secrets-read"] and self.is_secret_path(path):\n            return self.verdict("secrets-read", "deny")\n        return None\n\n    def decide_grep',
     '        return None\n\n    def decide_grep', "test_hooks.py"),
    ("M3", "a crashing guard no longer blocks (|| exit 2 removed)", "repo", ".claude/settings.json",
     '/harness/guard.py\\" || exit 2"', '/harness/guard.py\\""', "test_install_integrity.py"),
    ("M4", "Stop hook never sends the agent back", "repo", ".claude/hooks/harness/stop_check.py",
     "    if not failures:\n", "    if True:\n", "test_stop_hook.py"),
    ("M5", "Stop hook blocks without a bound", "repo", ".claude/hooks/harness/stop_check.py",
     'if blocks >= conf["max_blocks"]:', "if False:", "test_stop_hook.py"),
    ("M6", "gate table: no hook log counts as pass", "repo", S + "gates.py",
     'return "unknown", "no hook log today"', 'return "pass", "no hook log today"', "test_gates.py"),
    ("M7", "gate table: a crashing check counts as pass", "repo", S + "gates.py",
     'state, detail = "error", f"check did not run: {err}"', 'state, detail = "pass", f"check did not run: {err}"',
     "test_gates.py"),
    ("M8", "preflight: uncommitted files are ignored", "repo", S + "preflight.py",
     "            dirty.append(path)", "            pass", "test_preflight.py"),
    ("M9", "preflight: lineage from the deployed commit is not checked", "repo", S + "preflight.py",
     "    return [] if r.returncode == 0 else [", "    return [] if True else [", "test_preflight.py"),
    ("M10", "deploy check: no tests counts as a pass", "repo", S + "deploy_check.py",
     'reasons.append("no test files found")', "pass", "test_deploy_check.py"),
    ("M11", "deploy.sh: a blocked verdict still replaces the code", "repo", S + "deploy.sh",
     'if [ "$VERDICT" != pass ]; then', "if false; then", "test_deploy_sh.py"),
    ("M12", "commit scanner prints the secret value", "repo", S + "commit_scan.py",
     'found += [f"{where}: {kind}" for kind', 'found += [f"{where}: {kind}: {text}" for kind',
     "test_commit_scan.py"),
    ("M13", "supply chain: a critical vulnerability can be accepted", "repo", S + "supply_chain.py",
     '        if sev == "CRITICAL":\n', '        if sev == "CRITICAL" and acc is None:\n', "test_supply_chain.py"),
    ("M14", "contract check: sections are not checked", "repo", S + "contract_check.py",
     'missing = [s for s in c["sections"] if s not in text]', "missing = []", "test_contract_check.py"),
    ("M15", "context budget: over the limit passes", "repo", S + "context_budget.py",
     'row["ok"] = row["bytes"] <= row["max"] and not row.get("over_each")', 'row["ok"] = True',
     "test_context_budget.py"),
    ("M16", "doc coverage: a code change is not drift", "repo", S + "doc_coverage.py",
     '        elif was["code"] != now["code"]:\n', "        elif False:\n", "test_doc_coverage.py"),
    ("M17", "failure registry names a test that does not exist", "repo", "harness/config/incident-coverage.json",
     '"test_preflight.Preflight.test_dirty_tree_fails"', '"test_preflight.Preflight.test_that_does_not_exist"',
     "test_incident_registry.py"),
    ("M18", "upgrade overwrites a locally edited kit file", "kit", "harness.py",
     "        elif local == base:\n", "        elif True:\n", "test_cli.py"),
    ("M19", "install replaces the project's settings instead of merging", "kit", "harness.py",
     "    out = json.loads(json.dumps(current))\n", "    out = {}\n", "test_cli.py"),
    ("M20", "upgrade leaves a narrowed guard matcher as it is", "kit", "harness.py",
     'if found_in.get("matcher") != entry.get("matcher"):', "if False:", "test_cli.py"),
    ("M21", "guard: Grep may search secret files", "repo", GUARD,
     '        if self.on["secrets-read"] and (self.is_secret_path(args.get("path") or "")',
     '        if False and (self.is_secret_path(args.get("path") or "")', "test_hooks.py"),
    ("M22", "guard: kit files may be edited without asking", "repo", GUARD,
     '        if self.on["kit-files"] and any(rx.search(rel) for rx in self.kit):',
     '        if False:', "test_hooks.py"),
    ("M23", "guard: shell writes to the agent's settings are not seen", "repo", GUARD,
     "    out = [seg[i + 1] for i, tok in enumerate(seg[:-1]) if tok in REDIRECTS]",
     "    return []\n    out = []", "test_hooks.py"),
    ("M24", "guard: scripts the agent wrote are not read", "repo", GUARD,
     '        """Scripts this command runs that the agent wrote or changed: their content."""',
     '        """Scripts this command runs that the agent wrote or changed: their content."""\n        return None',
     "test_hooks.py"),
    ("M25", "guard: decoded or downloaded code runs without asking", "repo", GUARD,
     "OBFUSCATED = [", "OBFUSCATED = [] and [", "test_hooks.py"),
    ("M26", "guard: a reviewer subagent may run anything", "repo", GUARD,
     '        """Every simple command is on the read-only list and nothing is written."""',
     '        """Every simple command is on the read-only list and nothing is written."""\n        return True',
     "test_hooks.py"),
    ("M27", "guard: a command on its second line is not seen", "repo", GUARD,
     "        lines = split_lines(command)[0]", "        lines = [command]", "test_hooks.py"),
    ("M28", "ConfigChange: switching the hooks off is allowed", "repo", ".claude/hooks/harness/config_guard.py",
     '        elif data.get("disableAllHooks"):', "        elif False:", "test_config_guard.py"),
    ("M29", "hook review: a rule over the false-block share is never flagged", "repo", S + "hook_review.py",
     '"over": c["decisions"] >= minimum and rate > share}', '"over": False}', "test_hook_review.py"),
    ("M30", "data checks: no output counts as a number", "repo", S + "data_checks.py",
     'return None, "no output"', "return 0, \"\"", "test_data_checks.py"),
    ("M31", "data checks: a failing value becomes the new baseline", "repo", S + "data_checks.py",
     '            and item.get("state") in BASELINE)', "            )", "test_data_checks.py"),
    ("M32", "regression cases: a case without a human confirmation is accepted", "repo", S + "regressions.py",
     "    if confirmed is None:\n", "    if confirmed is None:\n        return []\n", "test_regressions.py"),
    ("M33", "deploy check: failing regression cases do not block", "repo", S + "deploy_check.py",
     '    bad = list(reg.get("failed") or []) + list(reg.get("errors") or [])', "    bad = []",
     "test_deploy_check.py"),
    ("M34", "contract check: named tests need not exist", "repo", S + "contract_check.py",
     "        if not word_exists(root, name, conf[\"contracts\"][\"dir\"]):", "        if False:",
     "test_contract_check.py"),
    ("M35", "golden tasks: the expected hook decisions are not checked", "repo", S + "golden_tasks.py",
     "        missing = [f\"{h['rule']}:{h['decision']}\" for h in task.get(\"expect_hooks\") or []",
     "        missing = [] and [f\"{h['rule']}:{h['decision']}\" for h in task.get(\"expect_hooks\") or []",
     "test_golden_tasks.py"),
    ("M36", "sandbox: the retry outside the sandbox stays open", "repo", S + "sandbox_config.py",
     '"allowUnsandboxedCommands": False,', '"allowUnsandboxedCommands": True,', "test_sandbox_config.py"),
    ("M37", "gate table: hooks switched off or unwired still pass", "repo", S + "gates.py",
     "    broken = hook_wiring()", "    broken = None", "test_gates.py"),
    ("M38", "guard: a path through a symlink is not seen as a repository file", "repo", GUARD,
     "        p = Path(os.path.realpath(p))", "        p = Path(os.path.normpath(p))", "test_hooks.py"),
    # The anti-goal: false blocks so frequent that people switch the hooks off.
    ("M39", "guard: copying an example to a secret file is denied as a read", "repo", GUARD,
     "                writes = True\n                continue\n", "                pass\n", "test_hooks.py"),
    ("M40", "guard: an edited project file gets every rule (a service that calls the network asks)", "repo",
     GUARD, 'if hit and (state == "new" or hit[0] == "deny"):', "if hit:", "test_hooks.py"),
]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def tests(where: str, test_file: str) -> tuple[int, list[str], str]:
    if where == "kit":
        r = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "tests", "-p", test_file], COPY)
    else:
        r = run([sys.executable, "-m", "unittest", "discover", "-s", "harness/core/tests",
                 "-t", "harness/core/tests", "-p", test_file], REPO)
    failed = sorted(set(re.findall(r"^(?:FAIL|ERROR): (test_\w+)", r.stderr, re.M)))
    ran = re.search(r"^Ran (\d+) tests?", r.stderr, re.M)
    return r.returncode, failed, ran.group(1) if ran else "?"


def main() -> int:
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    began = time.monotonic()
    shutil.copytree(KIT, COPY, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    REPO.mkdir()
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@example.com"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=REPO, check=True)
    (REPO / "README.md").write_text("# demo\n")
    subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=REPO, check=True)
    r = run([sys.executable, str(COPY / "harness.py"), "install", str(REPO)], WORK)
    assert r.returncode == 0, r.stdout + r.stderr

    misses, picked = [], [m for m in MUTANTS if not only or m[0] in only]
    for mid, what, where, rel, old, new, test_file in picked:
        path = (COPY if where == "kit" else REPO) / rel
        original = path.read_text(encoding="utf-8")
        count = original.count(old)
        if count != 1:
            print(f"{mid:<4} NOT APPLIED ({count} matches): {what}")
            misses.append(mid)
            continue
        rc0, _, _ = tests(where, test_file)
        path.write_text(original.replace(old, new), encoding="utf-8")
        try:
            rc1, failed1, ran1 = tests(where, test_file)
        finally:
            path.write_text(original, encoding="utf-8")
        rc2, _, _ = tests(where, test_file)
        killed = rc0 == 0 and rc1 != 0 and rc2 == 0
        if not killed:
            misses.append(mid)
        print(f"{mid:<4} {'killed' if killed else 'SURVIVED':<8} before {'green' if rc0 == 0 else 'RED'}, "
              f"mutant {'red' if rc1 else 'GREEN'} ({len(failed1)} of {ran1} fail), restored "
              f"{'green' if rc2 == 0 else 'RED'} | {what} | {test_file}: {', '.join(failed1[:3])}")
    print(f"\nmutants: {len(picked)}, killed: {len(picked) - len(misses)}, survived or not applied: "
          f"{len(misses)}{' (' + ', '.join(misses) + ')' if misses else ''}; {time.monotonic() - began:.0f} s")
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
