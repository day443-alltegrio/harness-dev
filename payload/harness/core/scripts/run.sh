#!/bin/sh
# All harness quality checks on the developer machine (QG1):
#   tests of the checks themselves, the context budget, the supply chain.
#   sh harness/core/scripts/run.sh [--offline]   # --offline: no vulnerability scan
# Exit 1 when any check fails; every check runs anyway.
cd "$(dirname "$0")/../../.." || exit 2
rc=0
for d in harness/core/tests harness/project/tests; do
  [ -d "$d" ] || continue
  echo "== tests: $d"
  OUT=$(python3 -m unittest discover -s "$d" -t "$d" 2>&1) || rc=1
  printf '%s\n' "$OUT" | grep -E '^(Ran|OK|FAILED)|^(FAIL|ERROR):'
done
echo "== context budget"
python3 harness/core/scripts/context_budget.py || rc=1
echo "== supply chain"
python3 harness/core/scripts/supply_chain.py "$@" || rc=1
exit $rc
