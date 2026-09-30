#!/usr/bin/env python3
"""Tests for claim-guard, the Stop hook that asks an absence claim to name its search.

Run:  python3 tests/test_claim_guard.py

Must-fire cases are the incident shapes. Must-pass cases are the exemptions that keep it
installed: a named scope, a named source ("the handoff says"), a conditional that describes
behaviour, and evidence shown in code. Plus the loop brake: a Stop hook that blocks
forever is a session that cannot end.
"""
import json
import os
import subprocess
import sys
import tempfile
import uuid

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "hooks", "claim-guard.py")
RUN = uuid.uuid4().hex[:8]
TMP = tempfile.mkdtemp(prefix="claim-guard-test-")
ENV = dict(os.environ, TMPDIR=TMP)


def run(text, name, stop_hook_active=False):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "text", "text": text}]}}) + "\n")
    fh.close()
    try:
        payload = {"session_id": "%s-%s" % (name, RUN), "transcript_path": fh.name}
        if stop_hook_active:
            payload["stop_hook_active"] = True
        p = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                           capture_output=True, text=True, env=ENV)
        return p.returncode
    finally:
        os.unlink(fh.name)


FIRE = [
    ("absence of a set", "31 memory files are linked from nowhere."),
    ("decay count", "I found 31 orphans in the notes directory."),
    ("component absence", "No importer exists for that workbook, so we need to write one."),
    ("nothing ingests", "Nothing ingests the export, it just sits there."),
]
PASS = [
    ("scope named", "Across all three indexes, 3 files are linked from nowhere."),
    ("source named", "The handoff says no importer exists; not checked yet."),
    ("conditional describes behaviour", "If nothing parses, it says so and dumps the lines."),
    ("evidence in code", "The grep printed:\n```\n31 orphans\n```\nChecking the other indexes next."),
    ("single identifier talk", "Nothing calls parse_row after the refactor, per the grep over src/."),
    ("decision, not discovery", "No importer exists by design: the user rejected automatic imports."),
    ("ordinary prose", "The importer refuses to print an empty table and dumps the unparsed lines."),
]


def main():
    fails = 0
    for name, text in FIRE:
        rc = run(text, "fire-" + name.replace(" ", "-"))
        ok = rc == 2
        fails += not ok
        print("  %-4s must fire: %-34s rc=%d" % ("ok" if ok else "FAIL", name, rc))
    for name, text in PASS:
        rc = run(text, "pass-" + name.replace(" ", "-"))
        ok = rc == 0
        fails += not ok
        print("  %-4s must pass: %-34s rc=%d" % ("ok" if ok else "FAIL", name, rc))
    # loop brake: the same claim twice in one session blocks once, then lets the turn end
    first, second = run(FIRE[0][1], "brake"), run(FIRE[0][1], "brake")
    ok = first == 2 and second == 0
    fails += not ok
    print("  %-4s loop brake: blocks once, then yields        rc=%d,%d" % ("ok" if ok else "FAIL", first, second))
    ok = run(FIRE[0][1], "active", stop_hook_active=True) == 0
    fails += not ok
    print("  %-4s stop_hook_active is honoured" % ("ok" if ok else "FAIL"))
    n = len(FIRE) + len(PASS) + 2
    print("%d cases, %d failures" % (n, fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
