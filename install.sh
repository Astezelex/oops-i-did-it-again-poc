#!/usr/bin/env bash
# install.sh - wire the guards into Claude Code, idempotently and reversibly.
#
# What it does, in this order:
#   1. runs the test suites and REFUSES to install if anything fails
#   2. copies the skill into the skills directory
#   3. backs up settings.json, then merges the three hook entries into it
#
# It never edits a rule, never touches your ledger, and writes absolute paths only.
# Run it again after a git pull: it is idempotent and will not duplicate entries.
#
# Usage:
#   ./install.sh                 install for the current user (~/.claude)
#   ./install.sh --project       install into ./.claude of the current project instead
#   ./install.sh --dry-run       print what would change, write nothing
#   ./install.sh --uninstall     remove only the entries this script added
#
# Requires: python3 (3.7+), bash. ShellCheck is optional and only used by file-guard.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCOPE="user"
DRY=0
UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --project)   SCOPE="project" ;;
    --dry-run)   DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
    *)           echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$SCOPE" = "project" ]; then
  CLAUDE_DIR="$PWD/.claude"
else
  CLAUDE_DIR="$HOME/.claude"
fi
SETTINGS="$CLAUDE_DIR/settings.json"

say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------- 1. prove it first
# OOPS_SKIP_TESTS exists for exactly one caller: tests/test_install.sh, which drives this
# script. Without it the chain would be install.sh -> run-all.sh -> test_install.sh ->
# install.sh, forever. Do not set it by hand to get past a failing suite.
if [ "$UNINSTALL" -eq 0 ] && [ "${OOPS_SKIP_TESTS:-0}" != "1" ]; then
  say "== running the test suites before touching anything"
  # No pipe here on purpose. Piping the suite into `tail` would make this `if` test
  # tail's exit code and install over a failing suite, which is rule
  # r_pipe_masks_exit_code and the incident that started this repo.
  if ! bash "$REPO/tests/run-all.sh"; then
    say "REFUSING TO INSTALL: a test suite failed. Run bash tests/run-all.sh to see which."
    exit 1
  fi
fi

# ---------------------------------------------------------------- 2. the skill
SKILL_SRC="$REPO/skills/oops-i-did-it-again"
SKILL_DST="$CLAUDE_DIR/skills/oops-i-did-it-again"
if [ "$UNINSTALL" -eq 1 ]; then
  if [ -d "$SKILL_DST" ] && [ "$DRY" -eq 0 ]; then
    rm -rf "$SKILL_DST"
    say "removed skill: $SKILL_DST"
  else
    say "would remove skill: $SKILL_DST"
  fi
else
  if [ "$DRY" -eq 1 ]; then
    say "would copy skill: $SKILL_SRC -> $SKILL_DST"
  else
    mkdir -p "$CLAUDE_DIR/skills"
    cp -r "$SKILL_SRC" "$CLAUDE_DIR/skills/"
    say "installed skill: $SKILL_DST"
  fi
fi

# ---------------------------------------------------------------- 3. settings.json
# The merge is done in python because settings.json is a real config with other people's
# entries in it. Backup first, match by command string so a rerun cannot duplicate.
REPO="$REPO" SETTINGS="$SETTINGS" DRY="$DRY" UNINSTALL="$UNINSTALL" python3 <<'PY'
import json, os, shutil, sys, time

repo      = os.environ["REPO"]
settings  = os.environ["SETTINGS"]
dry       = os.environ["DRY"] == "1"
uninstall = os.environ["UNINSTALL"] == "1"

WANT = [
    ("PreToolUse", "Bash",                 "bash-guard.py",  10, "bash-guard"),
    ("PreToolUse", "Write|Edit|MultiEdit", "file-guard.py",  20, "file-guard"),
    ("Stop",       None,                   "style-guard.py", 10, None),
]

def cmd_for(script):
    # Absolute path on purpose. A hook command may run through a shell or be spawned
    # directly depending on the build and the platform, and only an absolute path is
    # correct in every case. Do not put ~ here.
    return "python3 %s" % os.path.join(repo, "hooks", script)

data = {}
if os.path.exists(settings):
    with open(settings, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except Exception as e:
            sys.exit("settings.json is not valid JSON (%s). Fix it first; refusing to write." % e)

hooks = data.setdefault("hooks", {})
wired = []


def canon(h):
    """Order-insensitive fingerprint of the hooks block.

    Comparing the raw JSON reports a change when nothing changed: rewriting two entries
    under one event reorders the list. That false 'changed' would make every rerun write
    a new file and a new backup, which is the kind of harmless-looking noise that hides a
    real diff later.
    """
    return json.dumps({k: sorted(json.dumps(e, sort_keys=True) for e in v)
                       for k, v in h.items()}, sort_keys=True)


before_all = canon(hooks)

for event, matcher, script, timeout, status in WANT:
    entries = hooks.setdefault(event, [])
    ours = cmd_for(script)
    # Drop any entry pointing at this script, wherever it came from. That makes both
    # install and uninstall idempotent, and moves a stale path to the new one.
    for group in list(entries):
        group["hooks"] = [h for h in group.get("hooks", [])
                          if os.path.basename(str(h.get("command", ""))) != script
                          and script not in str(h.get("command", ""))]
        if not group["hooks"]:
            entries.remove(group)
    if not uninstall:
        hook = {"type": "command", "command": ours, "timeout": timeout}
        if status:
            hook["statusMessage"] = status
        group = {"hooks": [hook]}
        if matcher:
            group = {"matcher": matcher, "hooks": [hook]}
        entries.append(group)
    if not entries:
        hooks.pop(event, None)
    wired.append("%s/%s" % (event, script))

if canon(hooks) == before_all:
    print("settings.json already correct, nothing to change")
    sys.exit(0)

rendered = json.dumps(data, indent=2) + "\n"
if dry:
    print("would write %s:\n%s" % (settings, rendered))
    sys.exit(0)

os.makedirs(os.path.dirname(settings), exist_ok=True)
if os.path.exists(settings):
    backup = "%s.bak-oops-%s" % (settings, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(settings, backup)
    print("backed up: %s" % backup)
with open(settings, "w", encoding="utf-8") as fh:
    fh.write(rendered)
print("%s: %s" % ("removed" if uninstall else "wired", ", ".join(wired)))
PY

if [ "$UNINSTALL" -eq 0 ] && [ "$DRY" -eq 0 ]; then
  cat <<EOF

Next, and do not skip it:

  python3 $REPO/hooks/replay.py 12

That measures how often these rules fire on YOUR real command history. Read the block
rate first. If a rule denies work you recognise as legitimate, the rule is wrong: fix it
before you get used to ignoring it.

The ledger lives at ~/.claude/oops-ledger.md and is yours alone. Start it from
$REPO/ledger/LEDGER-TEMPLATE.md and keep it out of any repo you publish.
EOF
fi
