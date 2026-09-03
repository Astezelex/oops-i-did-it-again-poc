#!/usr/bin/env bash
# Sandbox test for install.sh. Creates a throwaway HOME, installs into it, and checks the
# properties that matter when someone else runs this on a machine with real settings:
#
#   - a dry run writes nothing at all
#   - an existing settings.json keeps its other hooks and its other keys
#   - the written paths are absolute
#   - a rerun changes nothing and does not duplicate entries
#   - uninstall removes only what this repo added
#   - an unparseable settings.json is refused, never overwritten
#
# Run:  bash tests/test_install.sh        (writes only inside its own temp directory)
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SB="$(mktemp -d -t oops-install-test-XXXXXX)"
trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/.claude"
export HOME="$SB"
# install.sh normally runs every suite first, and this file IS one of those suites. Without
# this the chain recurses: install.sh -> run-all.sh -> test_install.sh -> install.sh.
export OOPS_SKIP_TESTS=1

# settings.json that already contains someone else's hook and an unrelated key
cat > "$SB/.claude/settings.json" <<'EOF'
{
  "model": "opus",
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 /opt/other/mine.py"}]}
    ]
  }
}
EOF

pass=0
fail=0
chk() {
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1)); echo "  ok   $1"
  else
    fail=$((fail + 1)); echo "  FAIL $1: want=$3 got=$2"
  fi
}
count() { grep -cE "$1" "$SB/.claude/settings.json" || true; }
exists() { if [ -e "$1" ]; then echo yes; else echo no; fi; }

cd "$REPO" || exit 1

echo "== dry run"
./install.sh --dry-run > "$SB/dry.log" 2>&1
chk "dry-run exits 0" "$?" 0
chk "dry-run wrote no skill" "$(exists "$SB/.claude/skills")" no
chk "dry-run left settings untouched" "$(count 'guard\.py')" 0

echo "== install"
./install.sh > "$SB/install.log" 2>&1
chk "install exits 0" "$?" 0
chk "skill copied" "$(exists "$SB/.claude/skills/oops-i-did-it-again/SKILL.md")" yes
chk "backup created" "$(find "$SB/.claude" -name 'settings.json.bak-oops-*' | wc -l)" 1
chk "other hook preserved" "$(count '/opt/other/mine\.py')" 1
chk "unrelated key preserved" "$(count '"model"')" 1
chk "absolute paths written" "$(count "$REPO/hooks/bash-guard\.py")" 1
chk "no tilde in settings" "$(count 'python3 ~')" 0
chk "three hooks wired" "$(count 'hooks/(bash|file|style)-guard\.py')" 3
chk "settings still valid json" \
    "$(python3 -c 'import json,sys;json.load(open(sys.argv[1]));print("yes")' "$SB/.claude/settings.json")" yes

echo "== rerun is idempotent"
./install.sh > "$SB/install2.log" 2>&1
chk "still exactly three" "$(count 'hooks/(bash|file|style)-guard\.py')" 3
chk "reports nothing to change" "$(grep -c 'already correct' "$SB/install2.log")" 1

echo "== uninstall"
./install.sh --uninstall > "$SB/uninstall.log" 2>&1
chk "uninstall exits 0" "$?" 0
chk "our hooks gone" "$(count 'hooks/(bash|file|style)-guard\.py')" 0
chk "other hook survived" "$(count '/opt/other/mine\.py')" 1
chk "skill removed" "$(exists "$SB/.claude/skills/oops-i-did-it-again")" no

echo "== unparseable settings.json"
printf '{ this is not json' > "$SB/.claude/settings.json"
./install.sh > "$SB/broken.log" 2>&1
chk "refuses to install" "$?" 1
chk "did not overwrite it" "$(cat "$SB/.claude/settings.json")" '{ this is not json'

echo
echo "$((pass + fail)) cases, $fail failures"
[ "$fail" -eq 0 ]
