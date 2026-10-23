#!/usr/bin/env python3
"""Style check of human-facing Markdown: traces of machine writing and project rules.

Over a few thousand lines of documentation the eye gets used to machine phrasing and
stops noticing it. This check takes a second and catches what reading misses.

Two kinds of findings, treated differently (rules in harness/config/style.json):

VIOLATIONS are unambiguous and always fixed: characters the project never uses (by
default the em and en dash, the one-character ellipsis, the arrow, angle quotes and
the middle dot). They come from machine output, not from the author.

SUSPICIONS are not errors but signs of uniformity a person rarely produces on purpose:
two thirds of the paragraphs opening with a bold lead, "three" eight times on a page,
stock phrases. Each case alone is fine; the density is not. They need an eye, not an
automatic fix.

    python3 harness/core/scripts/style_check.py                # the scope from style.json
    python3 harness/core/scripts/style_check.py path.md ...    # given files or folders
    python3 harness/core/scripts/style_check.py --strict       # suspicions fail too
    python3 harness/core/scripts/style_check.py --scope-only a.md b.md   # only files in scope

Exit code 1 on a violation (or on a suspicion with --strict). A line with the
"style-check: ignore" mark is skipped: a document that describes the rules has to show
the forbidden characters. Code blocks are not checked.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
CONFIG = ROOT / "harness" / "config" / "style.json"

BOLD_LEAD = re.compile(r"^\*\*[^*\n]{3,70}\*\*[.,:]?\s", re.M)
CODE_BLOCK = re.compile(r"```.*?```", re.S)


def load(path: pathlib.Path = CONFIG) -> dict:
    conf = json.loads(path.read_text(encoding="utf-8"))
    conf["_cliches"] = []
    for items in conf.get("cliches", {}).values():
        for item in items:
            rx, label = (item, re.sub(r"\\b", "", item)) if isinstance(item, str) else item
            conf["_cliches"].append((re.compile(rx, re.I), label))
    conf["_triads"] = [re.compile(rx, re.I) for rx in conf.get("triad_words", {}).values()]
    return conf


def prose_of(text: str, mark: str) -> str:
    """The text without code blocks and without lines marked to skip."""
    kept = [line for line in text.splitlines() if mark not in line]
    return CODE_BLOCK.sub("", "\n".join(kept))


def check_text(text: str, conf: dict) -> tuple[list[str], list[str]]:
    prose = prose_of(text, conf.get("ignore_mark", "style-check: ignore"))
    violations: list[str] = []
    suspicions: list[str] = []
    for char, why in conf.get("banned", {}).items():
        n = prose.count(char)
        if n:
            line = next((i for i, ln in enumerate(prose.splitlines(), 1) if char in ln), 0)
            violations.append(f"{n}x {char!r} ({why}), first on line {line}")
    for rx, label in conf["_cliches"]:
        n = len(rx.findall(prose))
        if n:
            suspicions.append(f"{n}x stock phrase: {label}")
    paragraphs = [p for p in prose.split("\n\n") if len(p) > 120]
    bold = len(BOLD_LEAD.findall(prose))
    share = conf.get("bold_lead_share", 0.45)
    if paragraphs and bold / len(paragraphs) > share:
        suspicions.append(f"bold lead in {bold} of {len(paragraphs)} paragraphs "
                          f"({100 * bold / len(paragraphs):.0f}%): too uniform")
    kb = max(len(prose) / 1024, 1)
    triads = sum(len(rx.findall(prose)) for rx in conf["_triads"])
    if triads / kb > conf.get("triads_per_kb", 1.2):
        suspicions.append(f'{triads}x "three" in {kb:.0f} KB: an obsessive triad')
    return violations, suspicions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Style check of Markdown texts")
    ap.add_argument("paths", nargs="*", help="files or folders; default: scope from style.json")
    ap.add_argument("--strict", action="store_true", help="suspicions fail too")
    ap.add_argument("--scope-only", action="store_true",
                    help="check only the given files that fall in the scope from style.json"
                         " (the Stop hook passes every changed Markdown file)")
    ap.add_argument("--config", type=pathlib.Path, default=CONFIG)
    args = ap.parse_args(argv)
    conf = load(args.config)

    # The scope in style.json is relative to the project root, given paths to the cwd.
    raws = [pathlib.Path(a) for a in args.paths] or [ROOT / s for s in conf.get("scope", [])]
    targets: list[pathlib.Path] = []
    for p in raws:
        if p.is_dir():
            targets.extend(sorted(p.rglob("*.md")))
        elif p.suffix == ".md":
            targets.append(p)
        else:
            print(f"skipping a non-Markdown path: {p}")

    def rel_of(path: pathlib.Path) -> str:
        try:
            return path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    totals: Counter = Counter()
    reported = checked = skipped = 0
    exclude = tuple(conf.get("exclude", []))
    named_files = {rel_of(pathlib.Path(a)) for a in args.paths}
    if args.scope_only:
        scope = tuple(s.rstrip("/") + "/" for s in conf.get("scope", []))
        targets = [t for t in targets if rel_of(t).startswith(scope)]
        named_files = set()
    for path in targets:
        rel = rel_of(path)
        # An exclusion holds when a folder is named too; a file named explicitly is checked.
        named = rel in named_files
        if not named and exclude and rel.startswith(exclude):
            skipped += 1
            continue
        if not path.exists():
            print(f"no such file: {rel}")
            continue
        checked += 1
        violations, suspicions = check_text(path.read_text(encoding="utf-8"), conf)
        totals["violations"] += len(violations)
        totals["suspicions"] += len(suspicions)
        if violations or suspicions:
            reported += 1
            print(f"\n{rel}")
            for v in violations:
                print(f"  VIOLATION  {v}")
            for s in suspicions:
                print(f"  suspicion  {s}")

    tail = f", skipped outside the rule: {skipped}" if skipped else ""
    print(f"\nfiles checked: {checked}, with findings: {reported}{tail}")
    print(f"violations: {totals['violations']}, suspicions: {totals['suspicions']}")
    if not totals["violations"] and not totals["suspicions"]:
        print("clean")
    if totals["violations"] or (args.strict and totals["suspicions"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
