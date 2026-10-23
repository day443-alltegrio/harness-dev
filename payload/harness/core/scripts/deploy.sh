#!/bin/sh
# Gated deploy: only committed, checked code replaces the running code.
#
#   sh harness/core/scripts/deploy.sh -m "[+] what was added" [-m "[X] what was fixed"]
#   sh harness/core/scripts/deploy.sh ... --allow-breaking "<reason>"   # allow an API break
#   DEPLOY_NOTES_FILE=notes.txt sh harness/core/scripts/deploy.sh
#
# Steps:
#   1. notes are required (release notes): every non-empty line starts with a marker
#      [+] added, [*] changed, [X] fixed, [-] removed or [!] attention;
#   2. QG2 preflight on this machine (harness/core/scripts/preflight.py): when it fails,
#      nothing is copied and the attempt is journaled as BLOCKED;
#   3. the project steps from harness/config/deploy-hooks.sh (DEPLOY_HOOKS overrides):
#        deploy_package  - the archive of what ships, only committed files;
#        deploy_ship     - copy it to the target; a failed copy is an error, not silence;
#        deploy_verify   - QG3: unpack into a temporary folder on the target and run
#                          harness/core/scripts/deploy_check.py there, print its JSON line;
#        deploy_swap     - only after "pass": replace the running code, restart;
#        deploy_health   - QG5: the service is up (plus smoke checks); non-zero is a
#                          failed deploy, never a warning;
#        deploy_journal  - record DONE, BLOCKED or FAILED with the notes and the report;
#                          the default appends to harness/.state/deploys.jsonl;
#   4. the report goes to harness/.state/deploy-last.json (the QG3 row of gates.py);
#      after a success the deployed ref moves to HEAD, and the next preflight checks
#      that the new commit descends from it.
set -eu

NL='
'
NOTES=""
ALLOW_BREAKING=""
while [ $# -gt 0 ]; do
  case "$1" in
    -m)
      [ $# -ge 2 ] || { echo "-m needs the notes text" >&2; exit 2; }
      NOTES="${NOTES:+$NOTES$NL}$2"; shift 2 ;;
    --allow-breaking)
      [ $# -ge 2 ] || { echo "--allow-breaking needs a reason" >&2; exit 2; }
      ALLOW_BREAKING="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$NOTES" ] && [ -n "${DEPLOY_NOTES:-}" ]; then
  NOTES="$DEPLOY_NOTES"
fi
# The notes file is read before moving to the repo root: a relative path is taken
# from where the script was started.
if [ -z "$NOTES" ] && [ -n "${DEPLOY_NOTES_FILE:-}" ]; then
  [ -r "$DEPLOY_NOTES_FILE" ] || { echo "cannot read DEPLOY_NOTES_FILE=$DEPLOY_NOTES_FILE" >&2; exit 2; }
  NOTES=$(cat "$DEPLOY_NOTES_FILE")
fi
NOTES=$(printf '%s\n' "$NOTES" | tr -d '\r')
legend() {
  cat >&2 <<'EOF'
Every non-empty notes line starts with a marker:
  [+] added   [*] changed   [X] fixed   [-] removed   [!] attention
Example:
  sh harness/core/scripts/deploy.sh -m "[+] export of the report to CSV" -m "[X] search by code with a dot"
EOF
}
if [ -z "$(printf '%s' "$NOTES" | tr -d '[:space:]')" ]; then
  echo "No deploy without notes: say what changed (-m, DEPLOY_NOTES or DEPLOY_NOTES_FILE)." >&2
  legend
  exit 2
fi
BAD=$(printf '%s\n' "$NOTES" | grep -v '^[[:space:]]*$' \
  | grep -v '^[[:space:]]*\[[-+*X!]\][[:space:]]*[^[:space:]]' || true)
if [ -n "$BAD" ]; then
  echo "Notes lines without a marker:" >&2
  printf '%s\n' "$BAD" | sed 's/^/  /' >&2
  legend
  exit 2
fi

cd "$(dirname "$0")/../../.."
STATE=harness/.state
mkdir -p "$STATE"
export NOTES

# Default journal: one JSON line per attempt; prints the attempt number. A project
# with a deploy table on the server redefines it in deploy-hooks.sh.
deploy_journal() {  # $1 = DONE|BLOCKED|FAILED, $2 = report JSON
  printf '%s' "$2" | python3 -c '
import datetime, json, subprocess, sys, os
raw = sys.stdin.read().strip()
try:
    report = json.loads(raw)
except ValueError:
    report = {"verdict": "error", "reasons": ["unreadable report"]}
head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
path = sys.argv[2]
n = sum(1 for _ in open(path, encoding="utf-8")) + 1 if os.path.exists(path) else 1
rec = {"id": n, "at": datetime.datetime.now().isoformat(timespec="seconds"), "status": sys.argv[1],
       "commit": head, "notes": os.environ.get("NOTES", ""), "report": report}
with open(path, "a", encoding="utf-8") as out:
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(n)' "$1" "$STATE/deploys.jsonl"
}

HOOKS="${DEPLOY_HOOKS:-harness/config/deploy-hooks.sh}"
[ -f "$HOOKS" ] || { echo "no $HOOKS: fill in the project deploy steps first" >&2; exit 2; }
# shellcheck source=/dev/null
. "$HOOKS"

# The last report, for the QG3 row of gates.py. Local only, no test output tails.
save_report() {  # $1 = report JSON, $2 = deploy id (may be empty), $3 = extra reason
  printf '%s' "$1" | python3 -c '
import datetime, json, sys
raw = sys.stdin.read().strip()
try:
    rep = json.loads(raw)
except ValueError:
    rep = {"verdict": "error", "reasons": ["no report from the deploy check"]}
if sys.argv[3]:
    rep["verdict"] = "fail"
    rep.setdefault("reasons", []).append(sys.argv[3])
rep.update(deploy_id=sys.argv[2] or None, at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
for f in (rep.get("tests") or {}).get("failed") or []:
    f.pop("tail", None)
json.dump(rep, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
print(json.dumps(rep, ensure_ascii=False))' "$STATE/deploy-last.json" "$2" "${3:-}"
}

if ! PF=$(python3 harness/core/scripts/preflight.py 2>&1); then
  printf '%s\n' "$PF" >&2
  J=$(printf '%s\n' "$PF" | python3 harness/core/scripts/preflight.py --report)
  ID=$(deploy_journal BLOCKED "$J" 2>/dev/null || true)
  echo "preflight stopped the deploy: nothing copied${ID:+ (attempt $ID recorded)}" >&2
  exit 1
fi
[ -z "$PF" ] || printf '%s\n' "$PF"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export WORK
ARCHIVE="$WORK/release.tar.gz"
deploy_package "$ARCHIVE"
echo "archive $(($(wc -c < "$ARCHIVE") / 1024)) KB"
deploy_ship "$ARCHIVE" || { echo "could not copy the archive to the target: nothing changed" >&2; exit 1; }

REPORT=$(deploy_verify "$ALLOW_BREAKING" | grep '^{' | tail -1 || true)
[ -n "$REPORT" ] || REPORT='{"agent": "agent:deployer", "verdict": "error", "reasons": ["the deploy check did not answer"]}'
VERDICT=$(printf '%s' "$REPORT" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("verdict", "error"))' 2>/dev/null || echo error)
if [ "$VERDICT" != pass ]; then
  ID=$(deploy_journal BLOCKED "$REPORT" 2>/dev/null || true)
  save_report "$REPORT" "$ID" "" >/dev/null
  printf '%s' "$REPORT" | python3 -c 'import json, sys
for r in json.load(sys.stdin).get("reasons") or ["no reason given"]:
    print("  " + r)' >&2 || true
  echo "the deploy check stopped the deploy: running code and service unchanged${ID:+ (attempt $ID recorded)}" >&2
  exit 1
fi

if ! deploy_swap; then
  FAILED=$(save_report "$REPORT" "" "the swap failed")
  deploy_journal FAILED "$FAILED" >/dev/null 2>&1 || true
  echo "FAILED: the swap did not complete; check the target, then deploy again or deploy the previous commit" >&2
  exit 1
fi
if ! deploy_health; then
  FAILED=$(save_report "$REPORT" "" "service not healthy after the swap")
  deploy_journal FAILED "$FAILED" >/dev/null 2>&1 || true
  echo "FAILED: the service is not healthy after the swap; to roll back, deploy the previous commit again" >&2
  exit 1
fi
ID=$(deploy_journal DONE "$REPORT" 2>/dev/null || true)
save_report "$REPORT" "$ID" "" >/dev/null
REF=$(python3 -c 'import sys; sys.path.insert(0, "harness/core/scripts"); import harness_config; print(harness_config.load()["deployed_ref"])')
git update-ref "$REF" HEAD
echo "deployed $(git rev-parse --short HEAD)${ID:+, attempt $ID}"
