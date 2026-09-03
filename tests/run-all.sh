#!/usr/bin/env bash
# Run every suite in this repo. Exits non-zero if any of them fails.
#
#   bash tests/run-all.sh
#
# Expected on a clean checkout: 83 cases, 0 failures.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

rc=0
for t in tests/test_rules.py tests/test_style_guard.py tests/test_guard_cli.py; do
  out="$(python3 "$t")"
  status=$?
  printf '%-28s %-22s exit %d\n' "$t" "$(printf '%s' "$out" | tail -1)" "$status"
  [ "$status" -ne 0 ] && rc=1
done

out="$(bash tests/test_install.sh)"
status=$?
printf '%-28s %-22s exit %d\n' "tests/test_install.sh" "$(printf '%s' "$out" | tail -1)" "$status"
[ "$status" -ne 0 ] && rc=1

if [ "$rc" -eq 0 ]; then
  echo "ALL SUITES PASS"
else
  echo "FAILURES ABOVE. Run the failing file directly to see which case."
fi
exit "$rc"
