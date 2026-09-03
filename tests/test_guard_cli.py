#!/usr/bin/env python3
"""Tests for hooks/guard.py, the harness-neutral front door.

Run:  python3 tests/test_guard_cli.py

If you are porting this to another agent framework, these are the cases your adapter has
to reproduce: exit 0 quiet, exit 1 warn with the rule named, exit 2 deny, and the same
verdicts whether the input arrives on argv or on stdin.
"""
import json
import os
import subprocess
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "hooks", "guard.py")

J = lambda *parts: "".join(parts)


def run(args, stdin=""):
    p = subprocess.run([sys.executable, GUARD] + args, input=stdin,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    cases = []

    def chk(name, got, want):
        cases.append((name, got, want))

    chk("clean command passes", run(["--command", "ls -la /tmp"])[0], 0)

    rc, out = run(["--command", "find /backups -mtime +7 -delete"])
    chk("warn exits 1", rc, 1)
    chk("warn names the rule", "r_time_based_delete" in out, True)

    chk("deny exits 2", run(["--command", J("docker ", "run --rm llama-bench --help")])[0], 2)
    chk("command on stdin", run(["--command", "-"],
                                stdin="find /backups -mtime +7 -delete")[0], 1)

    rc, out = run(["--command", "find /backups -mtime +7 -delete", "--json"])
    chk("json verdict", json.loads(out.splitlines()[0])["verdict"], "WARN")

    tmp = tempfile.mkdtemp(prefix="guard-cli-test-")
    notes = os.path.join(tmp, "HANDOFF-2026-01-01-example.md")
    with open(notes, "w", encoding="utf-8") as fh:
        fh.write("Gmail uses the template name to fill the subject line, so we key on it.")
    chk("unproven vendor claim warns", run(["--file", notes])[0], 1)

    code = os.path.join(tmp, "util.py")
    with open(code, "w", encoding="utf-8") as fh:
        fh.write("def add(a, b):\n    return a + b\n")
    chk("ordinary file passes", run(["--file", code])[0], 0)

    chk("content on stdin", run(["--file", notes, "--content-stdin"],
                                stdin="The importer refuses to print an empty table.")[0], 0)

    fails = 0
    for name, got, want in cases:
        ok = got == want
        fails += not ok
        print("  %-4s %-34s want=%s got=%s" % ("ok" if ok else "FAIL", name, want, got))
    print("\n%d cases, %d failures" % (len(cases), fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
