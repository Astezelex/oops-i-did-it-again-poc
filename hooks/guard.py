#!/usr/bin/env python3
"""guard.py - the same rules, without Claude Code.

Claude Code speaks a specific hook protocol (JSON on stdin, JSON on stdout, exit codes).
Every other harness speaks something else, and most of them can at least run a command
before executing a shell command or writing a file. This is the adapter for those: plain
argv in, human-readable verdict on stderr, meaningful exit code.

    python3 guard.py --command 'rm -rf /srv/x && rsync -a /src/ /srv/x/'
    python3 guard.py --file path/to/notes.md            # reads the file's content
    python3 guard.py --file notes.md --content-stdin    # content on stdin instead
    echo '<cmd>' | python3 guard.py --command -

Exit codes, chosen so a shell wrapper can act on them without parsing text:

    0   nothing to say, proceed
    1   WARN, proceed but the reason is on stderr
    2   DENY, do not run this

Use it as a pre-exec check in your own agent loop:

    if ! python3 guard.py --command "$CMD"; then
        case $? in
          1) echo "proceeding with warning" >&2 ;;
          2) exit 2 ;;
        esac
    fi

The rules themselves live in bash-guard.py and file-guard.py and are imported from there,
so a fork only ever edits one copy of a rule. See PORTING.md.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    """Import a hook module whose filename contains a hyphen."""
    path = os.path.join(HERE, name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_command(cmd):
    """Return (exit_code, [messages]) for a shell command."""
    bash_guard = load("bash-guard")
    deny, warn = [], []
    for rule in bash_guard.RULES:
        try:
            got = rule(cmd)
        except Exception:
            continue                      # fail open, one broken rule must not block
        if not got:
            continue
        level, msg = got
        (deny if level == "BLOCK" else warn).append("%s: %s" % (rule.__name__, msg))
    if deny:
        return 2, deny + warn
    if warn:
        return 1, warn
    return 0, []


def check_file(path, content):
    """Return (exit_code, [messages]) for a file write, by asking file-guard directly.

    file-guard's checks are wired into its main(), so this drives it through its own
    protocol instead of reimplementing them. One implementation, two front doors.
    """
    payload = json.dumps({"tool_name": "Write",
                          "tool_input": {"file_path": path, "content": content}})
    p = subprocess.run([sys.executable, os.path.join(HERE, "file-guard.py")],
                       input=payload, capture_output=True, text=True)
    if not p.stdout.strip():
        return 0, []
    try:
        hso = json.loads(p.stdout).get("hookSpecificOutput") or {}
    except Exception:
        return 0, []
    if hso.get("permissionDecision") == "deny":
        return 2, [hso.get("permissionDecisionReason", "denied")]
    ctx = hso.get("additionalContext")
    return (1, [ctx]) if ctx else (0, [])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--command", help="shell command to check, or - to read it from stdin")
    ap.add_argument("--file", help="path of a file about to be written")
    ap.add_argument("--content-stdin", action="store_true",
                    help="with --file, read the new content from stdin")
    ap.add_argument("--json", action="store_true", help="emit the verdict as JSON on stdout")
    args = ap.parse_args()

    if args.command:
        cmd = sys.stdin.read() if args.command == "-" else args.command
        code, msgs = check_command(cmd)
    elif args.file:
        if args.content_stdin:
            content = sys.stdin.read()
        else:
            try:
                with open(args.file, encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError as e:
                sys.exit("cannot read %s: %s" % (args.file, e))
        code, msgs = check_file(args.file, content)
    else:
        ap.error("give --command or --file")

    verdict = {0: "PASS", 1: "WARN", 2: "DENY"}[code]
    if args.json:
        sys.stdout.write(json.dumps({"verdict": verdict, "messages": msgs}) + "\n")
    elif msgs:
        sys.stderr.write("%s\n  %s\n" % (verdict, "\n  ".join(msgs)))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # Fail open, exactly like the hooks. A broken guard must never stop the work.
        sys.exit(0)
