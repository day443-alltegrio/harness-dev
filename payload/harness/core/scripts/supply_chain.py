#!/usr/bin/env python3
"""Supply chain (QG1, and QG2 for the deployed apps): pins, vulnerabilities, plugins.

Checks (apps are listed in supply_chain of harness.json):
  pins     - every line of an app's requirements.txt is pinned (==) and the app has a
             full version list (lock file). Without it transitive packages drift
             between machines;
  vulns    - pip-audit over the lock files and npm audit over the npm folders.
             Severity comes from OSV (the GHSA label, else computed from the CVSS 3
             vector). CRITICAL always fails (blocks the deploy of its app). Anything
             else fails unless it is in harness/config/vuln-allowlist.txt
             ("id  review-date  reason") with a review date not yet passed;
  plugins  - plugins, marketplaces and MCP servers from .claude/settings.json and
             .mcp.json only from harness/config/plugins-allowlist.txt.

The vulnerability scanners go to the internet (PyPI, npm, OSV); --offline skips them.

    python3 harness/core/scripts/supply_chain.py [--offline] [--json] [--apps a,b]
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config  # noqa: E402

ROOT = harness_config.ROOT
PIN = re.compile(r"^[A-Za-z0-9_.\-]+(\[[^\]]*\])?==\S+$")
RANK = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def osv_cache_path(root: Path = ROOT) -> Path:
    return root / "harness" / ".state" / "osv-cache.json"


def read_list(path: Path) -> dict[str, str]:
    """A file of "id  reason" lines (# starts a comment) -> {id: reason}."""
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, why = line.partition(" ")
                out[key] = why.strip()
    return out


def read_accepted(path: Path) -> dict[str, tuple[str, str]]:
    """Accepted vulnerabilities: {id: (review date YYYY-MM-DD, reason)}."""
    out = {}
    for key, rest in read_list(path).items():
        when, _, why = rest.partition(" ")
        out[key] = (when.strip(), why.strip())
    return out


def _roundup(x: float) -> float:
    return math.ceil(x * 10 - 1e-9) / 10


def cvss3_score(vector: str) -> float | None:
    """CVSS 3.x base score from the vector (FIRST specification, section 7)."""
    m = dict(p.split(":", 1) for p in vector.split("/")[1:] if ":" in p)
    try:
        av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}[m["AV"]]
        ac = {"L": 0.77, "H": 0.44}[m["AC"]]
        changed = m["S"] == "C"
        pr = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[m["PR"]]
        ui = {"N": 0.85, "R": 0.62}[m["UI"]]
        cia = {"H": 0.56, "L": 0.22, "N": 0.0}
        c, i, a = cia[m["C"]], cia[m["I"]], cia[m["A"]]
    except KeyError:
        return None
    iss = 1 - (1 - c) * (1 - i) * (1 - a)
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    expl = 8.22 * av * ac * pr * ui
    return _roundup(min(1.08 * (impact + expl), 10) if changed else min(impact + expl, 10))


def _label(score: float) -> str:
    return "CRITICAL" if score >= 9 else "HIGH" if score >= 7 else "MODERATE" if score >= 4 else "LOW"


def osv_severity(ids: list[str], cache_path: Path | None = None) -> str:
    """Severity by OSV, cached in harness/.state. An explicit label (GHSA) beats a
    computed score: vectors of different databases for the same flaw disagree, the
    label is set by a reviewer. The CVSS 3 vector is used only when no id has a label."""
    cache_path = cache_path or osv_cache_path()
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    labels, scores = [], []
    for vid in ids:
        if vid not in cache:
            try:
                with urllib.request.urlopen(f"https://api.osv.dev/v1/vulns/{vid}", timeout=20) as r:
                    d = json.load(r)
                cache[vid] = {"label": (d.get("database_specific") or {}).get("severity"),
                              "vectors": [x["score"] for x in d.get("severity", [])],
                              "summary": (d.get("summary") or d.get("details") or "")[:300]}
            except Exception:  # noqa: BLE001 - one unreachable record does not stop the rest
                continue
        rec = cache[vid]
        if rec.get("label"):
            labels.append(rec["label"].upper())
        scores += [x for x in (cvss3_score(v) for v in rec["vectors"] if v.startswith("CVSS:3"))
                   if x is not None]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    if labels:
        return max(labels, key=lambda x: RANK.get(x, 0))
    return _label(max(scores)) if scores else "UNKNOWN"


def check_pins(root: Path = ROOT) -> list[str]:
    """Pinning violations: a non-empty list is a failure."""
    problems = []
    for app in harness_config.load(root)["supply_chain"]["python"]:
        req = root / app["requirements"]
        if not req.is_file():
            problems.append(f"{app['app']}: no {app['requirements']}")
            continue
        for n, line in enumerate(req.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s and not s.startswith("#") and not PIN.match(s):
                problems.append(f"{app['requirements']}:{n} not pinned: {s}")
        if not app.get("lock") or not (root / app["lock"]).is_file():
            problems.append(f"{app['app']}: no full version list (lock file)")
    return problems


def check_plugins(root: Path = ROOT) -> list[str]:
    allowed = read_list(root / "harness" / "config" / "plugins-allowlist.txt")
    problems = []
    settings = root / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    for name, on in (data.get("enabledPlugins") or {}).items():
        if on and f"plugin:{name}" not in allowed:
            problems.append(f"plugin not in the allowlist: {name}")
    for name in (data.get("extraKnownMarketplaces") or {}):
        if f"marketplace:{name}" not in allowed:
            problems.append(f"marketplace not in the allowlist: {name}")
    mcp = root / ".mcp.json"
    if mcp.is_file():
        for name in (json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers") or {}):
            if f"mcp:{name}" not in allowed:
                problems.append(f"MCP server not in the allowlist: {name}")
    return problems


def pip_audit(lock: Path, root: Path = ROOT) -> list[dict]:
    """Vulnerabilities from pip-audit (through uvx); local versions (+cpu) are skipped."""
    clean = [line for line in lock.read_text(encoding="utf-8").splitlines()
             if PIN.match(line.strip()) and "+" not in line]
    tmp = root / "harness" / ".state" / f"audit-{lock.stem}.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(clean) + "\n", encoding="utf-8")
    r = subprocess.run(["uvx", "pip-audit", "-r", str(tmp), "--no-deps", "--disable-pip",
                        "-f", "json", "--progress-spinner", "off"],
                       capture_output=True, text=True, timeout=900)
    if not r.stdout.strip().startswith("{"):
        raise RuntimeError(f"pip-audit gave no answer: {r.stderr.strip()[:300]}")
    found = []
    for dep in json.loads(r.stdout).get("dependencies", []):
        for v in dep.get("vulns", []):
            found.append({"package": dep["name"], "version": dep.get("version"),
                          "id": v["id"], "aliases": v.get("aliases", []),
                          "fix": v.get("fix_versions", [])})
    return found


def npm_audit(folder: Path) -> list[dict]:
    r = subprocess.run(["npm", "audit", "--omit=dev", "--json"], cwd=folder,
                       capture_output=True, text=True, timeout=300)
    data = json.loads(r.stdout or "{}")
    if "vulnerabilities" not in data:
        raise RuntimeError(f"npm audit gave no answer: {r.stderr.strip()[:300]}")
    return [{"package": name, "severity": v.get("severity"), "id": "npm:" + name,
             "fix": bool(v.get("fixAvailable"))}
            for name, v in data["vulnerabilities"].items()]


def check_vulns(apps: list[str] | None = None, today: date | None = None,
                root: Path = ROOT) -> tuple[list[str], dict]:
    """Failures and a summary. apps limits the scan (default: every configured app).
    CRITICAL always fails; anything else fails when not accepted or past review."""
    today = today or date.today()
    sc = harness_config.load(root)["supply_chain"]
    accepted = read_accepted(root / "harness" / "config" / "vuln-allowlist.txt")
    problems: list[str] = []
    summary = {"python": 0, "npm": 0, "accepted": 0, "critical": 0, "by_severity": {}}
    found = []
    for app in sc["python"]:
        if apps is not None and app["app"] not in apps:
            continue
        seen = set()
        for v in pip_audit(root / app["lock"], root):
            if (v["package"], v["id"]) in seen:
                continue
            seen.add((v["package"], v["id"]))
            v["severity"] = osv_severity([v["id"], *v["aliases"]], osv_cache_path(root))
            found.append((app["app"], v))
            summary["python"] += 1
    for folder in sc["npm"]:
        if apps is not None and folder not in apps:
            continue
        for v in npm_audit(root / folder):
            v["severity"] = (v.get("severity") or "unknown").upper()
            v["aliases"] = []
            found.append((folder, v))
            summary["npm"] += 1
    for app, v in found:
        sev = v["severity"]
        summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
        label = f"{app}: {v['package']} {v.get('version') or ''} {v['id']} [{sev}]".replace("  ", " ")
        acc = next((accepted[k] for k in [v["id"], *v["aliases"]] if k in accepted), None)
        if sev == "CRITICAL":
            summary["critical"] += 1
            problems.append(f"{label}: critical, blocks the deploy of {app}")
        elif acc is None:
            problems.append(f"{label}: not accepted in vuln-allowlist.txt")
        elif acc[0] < today.isoformat():
            problems.append(f"{label}: review date {acc[0]} has passed")
        else:
            summary["accepted"] += 1
    return problems, summary


def main(argv: list[str]) -> int:
    report = {"pins": check_pins(), "plugins": check_plugins(), "vulns": [], "summary": {}}
    apps = argv[argv.index("--apps") + 1].split(",") if "--apps" in argv else None
    sc = harness_config.load()["supply_chain"]
    if "--offline" not in argv and (sc["python"] or sc["npm"]):
        try:
            report["vulns"], report["summary"] = check_vulns(apps)
        except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as err:
            # Could not measure: a failure, not "zero vulnerabilities" (B10).
            report["vulns"] = [f"scanner failed: {err}"]
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False))
    else:
        if not (sc["python"] or sc["npm"]):
            print("apps: none configured in harness.json (supply_chain)")
        for key in ("pins", "plugins", "vulns"):
            print(f"{key}: {'ok' if not report[key] else len(report[key])}")
            for p in report[key]:
                print(f"   {p}")
        if report["summary"]:
            print("found:", report["summary"])
    return 0 if not (report["pins"] or report["plugins"] or report["vulns"]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
