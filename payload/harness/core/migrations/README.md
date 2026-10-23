# Config migrations

A migration changes project-owned settings when a new kit version changes their
format (a renamed key, a moved file). `harness.py upgrade` runs every migration whose
number is above `schema` in `harness/harness.lock.json`, in order, once each, then
records the highest number. A fresh install starts at the latest number and runs none.

File: `NNNN_<what>.py`, a four-digit number and a short name. It defines
`migrate(root: Path) -> list[str]`: the changes made, one message each, empty when
there was nothing to do. A migration must be idempotent (running it twice changes
nothing the second time), must never delete project content without keeping a copy,
and must be listed in the `CHANGELOG.md` entry of its version with an `[!]` note.

```python
"""0002: scan.ids was renamed to scan.id_patterns."""
import json
from pathlib import Path


def migrate(root: Path) -> list[str]:
    path = root / "harness/config/harness.json"
    conf = json.loads(path.read_text(encoding="utf-8"))
    scan = conf.get("scan", {})
    if "ids" not in scan:
        return []
    scan["id_patterns"] = scan.pop("ids")
    path.write_text(json.dumps(conf, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ["harness/config/harness.json: scan.ids -> scan.id_patterns"]
```
