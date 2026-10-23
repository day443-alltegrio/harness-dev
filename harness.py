#!/usr/bin/env python3
"""Install, upgrade and inspect the generic harness in a project repository.

    python3 harness.py install <repo> [--dry-run] [--verbose]
    python3 harness.py upgrade <repo> [--dry-run] [--verbose] [--force]
    python3 harness.py status  <repo>
    python3 harness.py version

Ownership decides what an upgrade may touch:
  kit-owned      everything under payload/ (harness/core/, .claude/hooks/harness/,
                 .claude/skills/harness-*, .claude/agents/harness-*, harness/.gitignore):
                 copied to the same path, replaced on upgrade, never edited in the project;
  project-owned  files created once from harness/core/templates/ (harness/config/,
                 harness/project/, .claude/harness-hooks.json, CLAUDE.md): never
                 overwritten; an upgrade only reports that their template changed;
  merged         .claude/settings.json (hook wiring and deny rules are added) and the
                 marked harness block in CLAUDE.md (two @imports).

The project lock harness/harness.lock.json keeps the kit version and a sha256 per
kit-owned file as written by the last install or upgrade. An upgrade replaces a file only
when the project copy still has that hash; a file changed locally is kept and the new
version lands next to it as <file>.harness-new (--force replaces it and keeps the local
copy as <file>.harness-old). Config format changes ship as numbered migrations in
harness/core/migrations/, run once each, in order. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
PAYLOAD = KIT / "payload"
TEMPLATES = "harness/core/templates/"
MIGRATIONS = "harness/core/migrations/"
LOCK = "harness/harness.lock.json"
SETTINGS = ".claude/settings.json"
FRAGMENT = "harness/core/settings.fragment.json"
BEGIN, END = "<!-- harness:begin", "<!-- harness:end -->"
HOOK_SCRIPT = re.compile(r"\.claude/hooks/harness/[\w.-]+\.py")
SKIP = {"__pycache__", ".DS_Store"}


def kit_version() -> str:
    return (KIT / "VERSION").read_text(encoding="utf-8").strip()


def kit_commit() -> str | None:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=KIT, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=KIT, capture_output=True, text=True).stdout
    return r.stdout.strip() + ("+" if dirty.strip() else "")


def semver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_files() -> dict[str, Path]:
    """Kit-owned files: repo path -> source in payload/."""
    out = {}
    for p in sorted(PAYLOAD.rglob("*")):
        if p.is_file() and not (set(p.relative_to(PAYLOAD).parts) & SKIP):
            out[p.relative_to(PAYLOAD).as_posix()] = p
    return out


def template_target(rel: str) -> str | None:
    """Where a template creates its project-owned file (None: not a template)."""
    if not rel.startswith(TEMPLATES):
        return None
    sub = rel[len(TEMPLATES):]
    if sub.startswith("config/"):
        return "harness/" + sub
    if sub.startswith("project/"):
        return "harness/" + sub
    if sub == "claude-harness-hooks.json":
        return ".claude/harness-hooks.json"
    if sub == "CLAUDE.md":
        return "CLAUDE.md"
    return None


def claude_block() -> str:
    text = (PAYLOAD / TEMPLATES / "CLAUDE.md").read_text(encoding="utf-8")
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[start:end]


class Plan:
    def __init__(self) -> None:
        self.actions: list[tuple[str, str, str]] = []   # (kind, path, note)
        self.writes: list = []                          # callables applied in order

    def add(self, kind: str, path: str, note: str = "", write=None) -> None:
        self.actions.append((kind, path, note))
        if write:
            self.writes.append(write)

    def show(self, verbose: bool) -> None:
        quiet = {"add", "update", "same"}
        counts: dict[str, int] = {}
        for kind, path, note in self.actions:
            counts[kind] = counts.get(kind, 0) + 1
            if verbose or kind not in quiet:
                print(f"  {kind:<9}{path}{': ' + note if note else ''}")
        summary = ", ".join(f"{k} {n}" for k, n in sorted(counts.items()))
        print(f"  ({summary})")

    def apply(self) -> None:
        for w in self.writes:
            w()


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if dst.suffix in (".sh", ".py") and (dst.parts[-2] in ("hooks", "harness", "scripts")):
        dst.chmod(dst.stat().st_mode | 0o111)


def merged_settings(current: dict) -> tuple[dict, list[str]]:
    """The project settings with the harness entries added; what was added."""
    frag = json.loads((PAYLOAD / FRAGMENT).read_text(encoding="utf-8"))
    out = json.loads(json.dumps(current))
    notes = []
    deny = out.setdefault("permissions", {}).setdefault("deny", [])
    for rule in frag["permissions"]["deny"]:
        if rule not in deny:
            deny.append(rule)
            notes.append(f"+deny {rule}")
    hooks = out.setdefault("hooks", {})
    for event, entries in frag["hooks"].items():
        have = hooks.setdefault(event, [])
        for entry in entries:
            for hook in entry["hooks"]:
                script = HOOK_SCRIPT.search(hook["command"]).group(0)
                found = None
                for e in have:
                    for h in e.get("hooks", []):
                        if script in h.get("command", ""):
                            found = h
                if found is None:
                    have.append(json.loads(json.dumps({**entry, "hooks": [hook]})))
                    notes.append(f"+{event} {script.rsplit('/', 1)[-1]}")
                elif found != hook:
                    found.clear()
                    found.update(hook)
                    notes.append(f"~{event} {script.rsplit('/', 1)[-1]}")
    return out, notes


def plan_settings(repo: Path, plan: Plan) -> None:
    path = repo / SETTINGS
    current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    new, notes = merged_settings(current)
    if notes:
        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        plan.add("merge", SETTINGS, ", ".join(notes), write)


def plan_claude_md(repo: Path, plan: Plan) -> None:
    path = repo / "CLAUDE.md"
    if not path.is_file():
        return  # created from its template
    text = path.read_text(encoding="utf-8")
    block = claude_block()
    if BEGIN in text and END in text:
        start, end = text.index(BEGIN), text.index(END) + len(END)
        if text[start:end] == block:
            return
        new = text[:start] + block + text[end:]
        note = "harness block updated"
    else:
        new = text.rstrip("\n") + "\n\n" + block + "\n"
        note = "harness block added (imports harness/core/rules.md and harness/project/rules.md)"
    plan.add("block", "CLAUDE.md", note, lambda: path.write_text(new, encoding="utf-8"))


def migrations() -> list[tuple[int, str, Path]]:
    out = []
    for p in sorted((PAYLOAD / MIGRATIONS).glob("[0-9][0-9][0-9][0-9]_*.py")):
        out.append((int(p.name[:4]), p.stem, p))
    return out


def run_migration(path: Path, repo: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.migrate(repo) or [])


def changelog_between(old: str, new: str) -> list[str]:
    """CHANGELOG.md sections of the versions after old, up to and including new."""
    text = (KIT / "CHANGELOG.md").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)[1:]
    out = []
    for part in parts:
        head = part.splitlines()[0]
        v = head.split()[0]
        if semver(old) < semver(v) <= semver(new):
            out.append("## " + part.rstrip())
    return out


def read_lock(repo: Path) -> dict | None:
    p = repo / LOCK
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def write_lock(repo: Path, lock: dict) -> None:
    (repo / LOCK).write_text(json.dumps(lock, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def plan_templates(repo: Path, plan: Plan, lock: dict, files: dict[str, Path], upgrade: bool) -> None:
    for rel, src in files.items():
        target = template_target(rel)
        if target is None:
            continue
        dst = repo / target
        digest = sha(src.read_bytes())
        if not dst.exists():
            plan.add("create", target, "from template",
                     lambda s=src, d=dst: copy_file(s, d))
        elif target == "CLAUDE.md":
            pass  # only its harness block belongs to the kit (plan_claude_md)
        elif upgrade and lock["templates"].get(target) not in (None, digest):
            plan.add("review", target, f"its template changed: compare with {rel}")
        lock["templates"][target] = digest


def plan_managed(repo: Path, plan: Plan, lock: dict, files: dict[str, Path], force: bool) -> None:
    old = dict(lock.get("managed") or {})
    new_hashes: dict[str, str] = {}
    for rel, src in files.items():
        dst = repo / rel
        digest = sha(src.read_bytes())
        if not dst.exists():
            plan.add("add", rel, "", lambda s=src, d=dst: copy_file(s, d))
            new_hashes[rel] = digest
            continue
        local = sha(dst.read_bytes())
        base = old.get(rel)
        if local == digest:
            plan.add("same", rel)
            new_hashes[rel] = digest
        elif local == base:
            plan.add("update", rel, "", lambda s=src, d=dst: copy_file(s, d))
            new_hashes[rel] = digest
        elif force:
            def write(s=src, d=dst) -> None:
                shutil.copy2(d, d.with_name(d.name + ".harness-old"))
                copy_file(s, d)
            plan.add("replace", rel, "changed locally; local copy kept as .harness-old", write)
            new_hashes[rel] = digest
        else:
            plan.add("conflict", rel, "changed locally; the kit version is written next to it as"
                     " .harness-new", lambda s=src, d=dst: copy_file(s, d.with_name(d.name + ".harness-new")))
            # Keep a base the local copy does not match: status keeps showing the drift
            # and the next upgrade conflicts again until the file is resolved.
            new_hashes[rel] = base or digest
    for rel, base in old.items():
        if rel in files:
            continue
        dst = repo / rel
        if not dst.exists():
            continue
        if sha(dst.read_bytes()) == base:
            plan.add("remove", rel, "no longer in the kit", lambda d=dst: d.unlink())
        else:
            plan.add("orphan", rel, "no longer in the kit, changed locally: kept")
    lock["managed"] = new_hashes


def plan_migrations(repo: Path, plan: Plan, lock: dict) -> None:
    for num, name, path in migrations():
        if num > lock.get("schema", 0):
            def write(p=path, n=num) -> None:
                for msg in run_migration(p, repo):
                    print(f"  migrate  {msg}")
                lock["schema"] = n
            plan.add("migrate", name, "", write)


def cmd_install(repo: Path, dry: bool, verbose: bool) -> int:
    if not (repo / ".git").exists():
        print(f"{repo} is not a git repository: the harness works on git history")
        return 2
    if read_lock(repo):
        print(f"already installed ({LOCK}): use upgrade")
        return 2
    version = kit_version()
    print(f"harness {version} -> {repo} (install{', dry run' if dry else ''})")
    lock = {"kit": "harness-dev", "source": str(KIT), "version": version, "commit": kit_commit(),
            "schema": max([n for n, _, _ in migrations()] or [0]),
            "installed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "upgraded_at": None, "managed": {}, "templates": {}}
    files = payload_files()
    plan = Plan()
    plan_managed(repo, plan, lock, files, force=False)
    plan_templates(repo, plan, lock, files, upgrade=False)
    plan_settings(repo, plan)
    plan_claude_md(repo, plan)
    plan.show(verbose)
    if dry:
        return 0
    plan.apply()
    write_lock(repo, lock)
    print(f"  lock     {LOCK}")
    print("next: fill harness/config/*.json and .claude/harness-hooks.json for this project"
          f" ({KIT / 'ADOPT.md'}, step 4), then run sh harness/core/scripts/run.sh and"
          " python3 harness/core/scripts/gates.py")
    return 0


def cmd_upgrade(repo: Path, dry: bool, verbose: bool, force: bool) -> int:
    lock = read_lock(repo)
    if not lock:
        print(f"no {LOCK}: use install")
        return 2
    old, new = lock["version"], kit_version()
    if semver(new) < semver(old):
        print(f"the project has {old}, newer than this kit ({new}): update the kit first")
        return 2
    print(f"harness {old} -> {new} in {repo} (upgrade{', dry run' if dry else ''})")
    for section in changelog_between(old, new):
        print("\n".join("  | " + line for line in section.splitlines()))
    files = payload_files()
    plan = Plan()
    plan_managed(repo, plan, lock, files, force)
    plan_templates(repo, plan, lock, files, upgrade=True)
    plan_migrations(repo, plan, lock)
    plan_settings(repo, plan)
    plan_claude_md(repo, plan)
    plan.show(verbose)
    if dry:
        return 0
    plan.apply()
    lock.update(version=new, commit=kit_commit(), source=str(KIT),
                upgraded_at=dt.datetime.now().isoformat(timespec="seconds"))
    write_lock(repo, lock)
    conflicts = [p for k, p, _ in plan.actions if k == "conflict"]
    print(f"  lock     {LOCK}")
    if conflicts:
        print(f"resolve {len(conflicts)} conflicts: merge each <file>.harness-new into the file,"
              " delete the .harness-new, then run upgrade again")
    print("next: sh harness/core/scripts/run.sh and python3 harness/core/scripts/gates.py")
    return 1 if conflicts else 0


def cmd_status(repo: Path) -> int:
    lock = read_lock(repo)
    if not lock:
        print(f"not installed in {repo} (no {LOCK})")
        return 2
    old, new = lock["version"], kit_version()
    print(f"installed {old} (kit commit {lock.get('commit') or '-'}, schema {lock.get('schema')}),"
          f" this kit {new}")
    behind = changelog_between(old, new)
    if behind:
        print(f"behind by {len(behind)} versions:")
        for section in behind:
            print("\n".join("  | " + line for line in section.splitlines()))
    drift, missing = [], []
    for rel, digest in sorted(lock["managed"].items()):
        p = repo / rel
        if not p.is_file():
            missing.append(rel)
        elif sha(p.read_bytes()) != digest:
            drift.append(rel)
    pending = sorted(str(p.relative_to(repo)) for d in ("harness", ".claude")
                     for p in (repo / d).rglob("*.harness-new"))
    for label, items in (("changed locally (move to the kit or expect a conflict)", drift),
                         ("missing", missing), ("unresolved conflicts", pending)):
        if items:
            print(f"{label}: {len(items)}")
            for i in items:
                print(f"  {i}")
    if not (drift or missing or pending):
        print("kit files intact")
    return 1 if (drift or missing or pending) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install, upgrade and inspect the generic harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("install", "upgrade"):
        p = sub.add_parser(name)
        p.add_argument("repo", type=Path)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--verbose", action="store_true")
        if name == "upgrade":
            p.add_argument("--force", action="store_true",
                           help="replace kit files changed locally, keeping them as .harness-old")
    sub.add_parser("status").add_argument("repo", type=Path)
    sub.add_parser("version")
    args = ap.parse_args(argv)
    if args.cmd == "version":
        print(kit_version())
        return 0
    repo = args.repo.resolve()
    if args.cmd == "install":
        return cmd_install(repo, args.dry_run, args.verbose)
    if args.cmd == "upgrade":
        return cmd_upgrade(repo, args.dry_run, args.verbose, args.force)
    return cmd_status(repo)


if __name__ == "__main__":
    sys.exit(main())
