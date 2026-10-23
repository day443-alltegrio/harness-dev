#!/bin/sh
# Checks of the kit itself, before a release:
#   1. tests of harness.py (install, upgrade, status on temporary repositories);
#   2. a fresh install into a temporary git repository, where the kit tests, run.sh
#      and the gate table must work as in a real project;
#   3. the style check over the kit documents (research/sources/ is verbatim material).
#   sh check.sh
set -u
cd "$(dirname "$0")" || exit 2
KIT=$(pwd)
rc=0
echo "== harness.py tests"
python3 -m unittest discover -s tests -t tests 2>&1 | tail -3 || rc=1
python3 -m unittest discover -s tests -t tests >/dev/null 2>&1 || rc=1

echo "== fresh install"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
(cd "$WORK" && git init -q -b main && git config user.email t@example.com && git config user.name t \
  && echo "# demo" > README.md && git add -A && git commit -qm init) || rc=1
python3 "$KIT/harness.py" install "$WORK" | tail -2 || rc=1
(cd "$WORK" && sh harness/core/scripts/run.sh --offline) || rc=1
(cd "$WORK" && git add -A && git commit -qm "harness" && python3 harness/core/scripts/gates.py)
echo "(QG2 fails here until the adoption contract exists: that is the point)"

echo "== style of the kit documents"
python3 "$WORK/harness/core/scripts/style_check.py" --config "$WORK/harness/config/style.json" \
  README.md ADOPT.md CLAUDE.md CHANGELOG.md research/README.md research/harness-engineering.md \
  research/case-study-pilot.md research/reviews extras/claude-context/README.md prompts payload/harness/core/docs \
  payload/harness/core/rules.md payload/harness/core/templates payload/.claude || rc=1
exit $rc
