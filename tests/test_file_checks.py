#!/usr/bin/env python3
"""Tests for file-guard's v2 checks: BANNED-WORD, PROBE, OWNER, CRON-TZ.

Run:  python3 tests/test_file_checks.py

Each check gets a trigger (the shape of its incident) and a quiet case (ordinary work that
must pass). Runs file-guard as the harness would: JSON on stdin, verdict on stdout.
BANNED-WORD reads a list from $HOME, so every case runs with HOME pointing at a scratch
directory; your real list is never read or touched.
"""
import json
import os
import subprocess
import sys
import tempfile

FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "hooks", "file-guard.py")


def verdict(path, content, home):
    env = dict(os.environ, HOME=home)
    p = subprocess.run([sys.executable, FILE], env=env, capture_output=True, text=True,
                       input=json.dumps({"tool_name": "Write",
                                         "tool_input": {"file_path": path, "content": content}}))
    if not p.stdout.strip():
        return "PASS", ""
    hso = json.loads(p.stdout).get("hookSpecificOutput") or {}
    text = hso.get("additionalContext") or hso.get("permissionDecisionReason") or ""
    return (hso.get("permissionDecision") or "WARN"), text


def main():
    tmp = tempfile.mkdtemp(prefix="oops-fc-")
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", "oops-banned-words.json"), "w") as fh:
        json.dump([{"pattern": r"\bchore\b", "word": "chore", "why": "the user banned it."}], fh)

    # OWNER needs a file owned by SOMEONE ELSE. As root: chown a scratch file to nobody.
    # As a normal user: any root-owned file will do, and it is never written to.
    if os.geteuid() == 0:
        foreign = os.path.join(tmp, "service.conf")
        open(foreign, "w").write("x=1\n")
        os.chown(foreign, 65534, 65534)
    else:
        foreign = "/etc/hostname" if os.path.exists("/etc/hostname") else "/etc/passwd"
    mine = os.path.join(tmp, "mine.conf")
    open(mine, "w").write("x=1\n")

    probe_bad = ("import subprocess, sys\n"
                 "subprocess.Popen(['python3', 'app.py'], env={'PORT': '5049'})\n"
                 "def main():\n    rows = run()\n    if not rows:\n        return\n"
                 "    print(summary(rows))\n    sys.exit(1 if red(rows) else 0)\n")
    probe_good = ("import subprocess, sys\n"
                  "if ':13B1' in open('/proc/net/tcp').read(): sys.exit('port 5049 taken')\n"
                  "subprocess.Popen(['python3', 'app.py'], env={'PORT': '5049'})\n"
                  "def main():\n    return run()\n"
                  "rows = main()\nprint(summary(rows))\nsys.exit(1 if red(rows) else 0)\n")

    cases = [
        # (name, path, content, want verdict, marker that must appear in the reason)
        ("BANNED-WORD in a UI string", "/srv/app/templates/list.html",
         "<button>Add a chore</button>", "WARN", "BANNED-WORD"),
        ("BANNED-WORD quiet: other text", "/srv/app/templates/list.html",
         "<button>Add a task</button>", "PASS", ""),
        ("BANNED-WORD quiet: identifier, not a string", "/srv/app/util.py",
         "chore = load()\n", "PASS", ""),
        ("PROBE: fixed port unchecked + early return", "/srv/qa/probe_orders.py",
         probe_bad, "WARN", "PROBE"),
        ("PROBE quiet: port checked, exit outside main", "/srv/qa/probe_orders.py",
         probe_good, "PASS", ""),
        ("PROBE quiet: same code, not a probe file", "/srv/qa/orders.py",
         probe_bad, "PASS", ""),
        ("OWNER: file of another user", foreign, "x=2\n", "WARN", "OWNER"),
        ("OWNER quiet: my own file", mine, "x=2\n", "PASS", ""),
        ("OWNER quiet: new file", os.path.join(tmp, "new.conf"), "x=2\n", "PASS", ""),
        ("CRON-TZ: schedule written", "/etc/cron.d/report",
         "0 10 * * * root /usr/local/bin/report\n", "WARN", "CRON-TZ"),
        ("CRON-TZ quiet: not a cron path", "/srv/app/notes.md",
         "0 10 * * * root /usr/local/bin/report\n", "PASS", ""),
    ]
    fails = 0
    for name, path, content, want, marker in cases:
        got, text = verdict(path, content, home)
        ok = got == want and (marker in text if marker else True)
        fails += not ok
        print("  %-4s %-48s want=%-4s got=%-4s" % ("ok" if ok else "FAIL", name, want, got))
    print("%d cases, %d failures" % (len(cases), fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
