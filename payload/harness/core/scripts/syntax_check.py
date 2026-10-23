#!/usr/bin/env python3
"""Syntax of changed files, without writing anything (no bytecode, no caches).

Used by the Stop hook on the files the agent changed. By extension:
  .py    - ast.parse
  .json  - json.loads
  .toml  - tomllib (Python 3.11+)
  .sh    - sh -n
Other files are skipped. Prints "file:line: error" per problem, exit 1 on any.

    python3 harness/core/scripts/syntax_check.py a.py b.json c.sh
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


def check(path: Path) -> str | None:
    """The error of one file, or None."""
    suffix = path.suffix
    try:
        if suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), str(path))
        elif suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif suffix == ".toml":
            import tomllib  # noqa: PLC0415
            tomllib.loads(path.read_text(encoding="utf-8"))
        elif suffix == ".sh":
            r = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
            if r.returncode != 0:
                return f"{path}: {r.stderr.strip()}"
    except SyntaxError as err:
        return f"{path}:{err.lineno}: {err.msg}"
    except json.JSONDecodeError as err:
        return f"{path}:{err.lineno}: {err.msg}"
    except (ValueError, UnicodeDecodeError) as err:
        return f"{path}: {err}"
    except ImportError:
        return None  # no tomllib before Python 3.11: skip, do not guess
    return None


def main(argv: list[str]) -> int:
    errors = [e for e in (check(Path(a)) for a in argv) if e]
    for e in errors:
        print(e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
