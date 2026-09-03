#!/usr/bin/env python3
"""Tests for the Stop hook, including the loop brake.

Run:  python3 tests/test_style_guard.py

The loop brake is the case that matters before you deploy this on someone else's machine.
A Stop hook that exits 2 forever is a session that cannot end, so the guard must give up
after MAX_BLOCKS consecutive blocks even when the offending phrase is still there.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "hooks", "style-guard.py")

# The loop brake keeps a per-session counter in the temp directory, so a test that reuses
# a fixed session id inherits the previous run's count and reports a false pass on the
# second run. Every id here is unique per run, and the counters live in a scratch TMPDIR
# that goes away with the process.
RUN = uuid.uuid4().hex[:8]
TMP = tempfile.mkdtemp(prefix="style-guard-test-")
ENV = dict(os.environ, TMPDIR=TMP)


def sid(name):
    return "%s-%s" % (name, RUN)


def transcript(text):
    """Write a one-message transcript in the harness's jsonl shape, return its path."""
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    fh.write(json.dumps({"type": "assistant",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": text}]}}) + "\n")
    fh.close()
    return fh.name


def run(text, session_id, stop_hook_active=False):
    path = transcript(text)
    try:
        payload = {"session_id": session_id, "transcript_path": path}
        if stop_hook_active:
            payload["stop_hook_active"] = True
        p = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                           capture_output=True, text=True, env=ENV)
        return p.returncode, p.stderr.strip()
    finally:
        os.unlink(path)


CLEAN = "The importer refuses to print an empty table and dumps the unparsed lines."
DIRTY = "I would rather do it now than after the weekend."


def main():
    fails = 0

    def check(name, got, want):
        nonlocal fails
        ok = got == want
        fails += not ok
        print("  %-4s %-42s want=%s got=%s" % ("ok" if ok else "FAIL", name, want, got))

    print("Stop hook")
    check("clean prose passes", run(CLEAN, sid("clean"))[0], 0)

    rc, err = run(DIRTY, sid("dirty"))
    check("banned phrasing blocks (exit 2)", rc, 2)
    check("block explains itself", bool(err), True)

    # A phrase inside a fenced block, an inline code span, a quote or a quoted string is
    # evidence, not the model's own prose, and must not trip the guard.
    check("fenced code exempt",
          run("Here is the log:\n```\nrather this than that\n```\n", sid("fence"))[0], 0)
    check("blockquote exempt", run("> rather this than that", sid("quote"))[0], 0)

    # The loop brake: same offending text, same session, three times running.
    loop = sid("loop")
    first = run(DIRTY, loop)[0]
    second = run(DIRTY, loop)[0]
    third = run(DIRTY, loop)[0]
    check("loop brake: 1st blocks", first, 2)
    check("loop brake: 2nd blocks", second, 2)
    check("loop brake: 3rd gives up", third, 0)

    # stop_hook_active is the harness's own brake, honoured when the build sends it.
    check("stop_hook_active short-circuits",
          run(DIRTY, sid("active"), stop_hook_active=True)[0], 0)

    # Fail-open: garbage on stdin must never wedge a session.
    p = subprocess.run([sys.executable, HOOK], input="not json at all",
                       capture_output=True, text=True, env=ENV)
    check("garbage stdin fails open", p.returncode, 0)
    p = subprocess.run([sys.executable, HOOK],
                       input=json.dumps({"transcript_path": "/nonexistent/path.jsonl"}),
                       capture_output=True, text=True, env=ENV)
    check("missing transcript fails open", p.returncode, 0)

    shutil.rmtree(TMP, ignore_errors=True)
    print("\n11 cases, %d failures" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
