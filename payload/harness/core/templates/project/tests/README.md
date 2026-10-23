# Project harness tests

Tests of checks that only make sense in this project: a deploy script that must call
preflight, a build config that must not delete tracked folders, a schema snapshot. They
run with the kit tests (`sh harness/core/scripts/run.sh`, gate QG1).

Name the files `test_project_*.py` so their module names never clash with the kit
tests. Each check gets a case where it fires on the reproduced failure and a clean case
where it stays silent. Record each test in `harness/config/incident-coverage.json` as
`module.Class.method`.

```python
"""Static checks of this project's deploy and build (patterns A4, A9)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class Static(unittest.TestCase):
    def test_deploy_calls_preflight(self):
        text = (ROOT / "deploy/app-sync.sh").read_text(encoding="utf-8")
        self.assertIn("harness/core/scripts/preflight.py", text)
```
