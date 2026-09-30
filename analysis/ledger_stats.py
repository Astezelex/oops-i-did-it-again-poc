#!/usr/bin/env python3
"""ledger_stats.py - counts from a private ledger, without publishing the ledger.

Reads ~/.claude/oops-ledger.md (or a path you give it) and emits only structure: the date
of each entry, its class letter, and whether it was caught by a person, by the model, or by
a hook. No titles, no paths, no prose. The result is safe to publish; the ledger is not.

    python3 analysis/ledger_stats.py > analysis/ledger.json

⛔ Read the output before you publish it. This script strips content by construction, but
your ledger is an operations diary and you are the last check.

Note what this can and cannot show. The ledger BEGINS on the day the skill was written, so
it has no "before" period. Entries going up is what recording looks like, not what getting
worse looks like. What it does show is which classes keep coming back after a mechanism was
supposed to have closed them.
"""
import json
import os
import re
import sys
from collections import Counter

DEFAULT = os.path.expanduser("~/.claude/oops-ledger.md")
# First words that mean "the model caught it". Add your own language's first person.
MODEL_WORDS = {"me", "i", "ja", "myself", "moi", "ich", "yo"}

ENTRY = re.compile(r'^##\s+(\d{4}-\d{2}-\d{2})')
CLASS = re.compile(r'^CLASS:\s*([A-Z])\b')
CAUGHT = re.compile(r'^CAUGHT BY:\s*(.+)$')
MECH = re.compile(r'^MECHANISM:')


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.exists(path):
        sys.exit("no ledger at %s" % path)

    entries = []
    cur = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ENTRY.match(line)
            if m:
                if cur:
                    entries.append(cur)
                cur = {"date": m.group(1), "class": None, "caught_by": None,
                       "has_mechanism": False}
                continue
            if not cur:
                continue
            m = CLASS.match(line)
            if m and not cur["class"]:
                cur["class"] = m.group(1)
                continue
            m = CAUGHT.match(line)
            if m and not cur["caught_by"]:
                raw = m.group(1).lower().strip()
                # v2: the OPENING word decides. v1 tested tool words first, anywhere in the
                # line, so "me, while looking for a free slot in `bash-guard.py.bak`" counted
                # as caught by a hook, and "the user, with their own test" as a test run. It
                # also knew only English: a Polish "ja" (me) fell through to "the user".
                # Hand check on the 33 v2 entries: 13 user / 19 model / 1 test, where v1's
                # order reported 14 / 14 / 4 test / 1 hook.
                first = re.split(r"[\s,(]+", raw, maxsplit=1)[0]
                if re.match(r"(a |the )?([\w-]+ ){0,2}(hook|guard)\b", raw):
                    who = "a hook"
                elif (re.match(r"(a |the |my own |my )?([\w-]+ ){0,2}(control|test|replay|check"
                               r"|review|ultrareview|gate)s?\b", raw) or re.match(r"\S+\.py\b", raw)):
                    who = "a test or control run"
                elif first in MODEL_WORDS:
                    who = "the model"
                else:
                    who = "the user"
                cur["caught_by"] = who
                continue
            if MECH.match(line):
                cur["has_mechanism"] = True
    if cur:
        entries.append(cur)

    by_class = Counter(e["class"] for e in entries if e["class"])
    by_date = Counter(e["date"] for e in entries)
    by_catch = Counter(e["caught_by"] for e in entries if e["caught_by"])

    out = {
        "source": "a private ledger, counts only",
        "entries": len(entries),
        "first": min(by_date) if by_date else None,
        "last": max(by_date) if by_date else None,
        "by_class": dict(sorted(by_class.items())),
        "by_date": dict(sorted(by_date.items())),
        "by_caught_by": dict(by_catch),
        "with_mechanism": sum(1 for e in entries if e["has_mechanism"]),
        "rows": [{"date": e["date"], "class": e["class"], "caught_by": e["caught_by"]}
                 for e in entries],
    }
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    sys.stderr.write("%d entries, %s..%s, classes: %s\n"
                     % (out["entries"], out["first"], out["last"],
                        " ".join("%s=%d" % kv for kv in sorted(by_class.items()))))


if __name__ == "__main__":
    main()
