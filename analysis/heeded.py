#!/usr/bin/env python3
"""heeded.py - did a warning change the next command?

v1 of this repo measured how often a command CARRIED a guarded shape. That counts shapes,
not behaviour, and README.md named the better measurement as future work: the hook's
verdict lands in the transcript, so each warning can be paired with the next command in
the same session. This is that measurement.

For every Bash call the hook actually warned on or denied (read from the transcript's
`hook_success` records, keyed by toolUseID, so this is what was really shown, not what the
current rules would say), take the NEXT Bash call in the same session and classify:

  REWRITTEN  the next command is a close variant (token overlap >= 0.3) and the same rule
             no longer fires on it: the warning was acted on
  REPEATED   the same rule fires on the next command too: ignored, or the rule is wrong
  MOVED ON   the next command is unrelated and clean: cannot tell, counted separately

Rule attribution uses the rules in hooks/bash-guard.py (current version), applied to both
commands with the hook's own heredoc shaping.

    python3 analysis/heeded.py [n_transcripts] > analysis/heeded.json

Limits, stated before anyone reads the numbers: one operator, one machine; a WARN runs the
command anyway, so REWRITTEN can mean "fixed after seeing the result", not only "fixed
because of the warning"; and similarity is a crude proxy for "same intent".
"""
import collections
import glob
import importlib.util
import json
import os
import re
import sys

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("bg", os.path.join(HERE, "..", "hooks", "bash-guard.py"))
bg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bg)


def fired(cmd):
    shaped = bg.strip_written_heredocs(cmd)
    out = {}
    for r in bg.RULES:
        try:
            h = r(shaped)
        except Exception:
            continue
        if h:
            out[r.__name__] = h[0]
    return out


def tokens(cmd):
    return set(re.findall(r"[A-Za-z0-9_./:-]{3,}", cmd))


def similar(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / max(1, len(ta | tb))


def sessions():
    files = sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")),
                   key=os.path.getmtime, reverse=True)[:N]
    for f in files:
        calls, verdict = [], {}
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            att = rec.get("attachment") or {}
            if att.get("type") == "hook_success" and att.get("hookName") == "PreToolUse:Bash":
                try:
                    hso = json.loads(att.get("stdout") or "{}").get("hookSpecificOutput") or {}
                except Exception:
                    hso = {}
                if hso.get("permissionDecision") == "deny":
                    verdict[att.get("toolUseID")] = "BLOCK"
                elif hso.get("additionalContext"):
                    verdict.setdefault(att.get("toolUseID"), "WARN")
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, list):
                for c in content:
                    # A DENY is not an attachment: it comes back as the tool result itself.
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        body = c.get("content")
                        body = body if isinstance(body, str) else json.dumps(body)
                        if body.startswith("PreToolUse:Bash hook error") and "bash-guard" in body[:80]:
                            verdict[c.get("tool_use_id")] = "BLOCK"
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Bash":
                        cmd = (c.get("input") or {}).get("command")
                        if cmd:
                            calls.append((c.get("id"), rec.get("timestamp", "")[:10], cmd))
        yield calls, verdict


def main():
    per = collections.defaultdict(collections.Counter)
    shown = collections.Counter()
    for calls, verdict in sessions():
        for i, (tid, day, cmd) in enumerate(calls[:-1]):
            level = verdict.get(tid)
            if not level:
                continue
            shown[level] += 1
            nxt = calls[i + 1][2]
            now, after = fired(cmd), fired(nxt)
            if not now:
                # shown by the rule version of that day, silent under the current one:
                # a verdict the current rules would no longer give (a repaired false positive,
                # or a rule since narrowed)
                shown[level + " no longer fired by current rules"] += 1
            for rule in now:
                key = "%s [%s]" % (rule, level)
                if rule in after:
                    per[key]["repeated"] += 1
                elif similar(cmd, nxt) >= 0.3:
                    per[key]["rewritten"] += 1
                else:
                    per[key]["moved_on"] += 1
    rows = []
    for rule, c in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        decided = c["rewritten"] + c["repeated"]
        rows.append({"rule": rule, "n": n, **dict(c),
                     "rewritten_of_decided": round(c["rewritten"] / decided, 3) if decided else None})
    json.dump({"warnings_shown": dict(shown), "rules": rows}, sys.stdout, indent=1)
    sys.stdout.write("\n")
    sys.stderr.write("shown: %s\n" % dict(shown))
    for r in rows:
        sys.stderr.write("%-30s n=%-4d rewritten=%-4d repeated=%-4d moved_on=%-4d  rewritten/decided=%s\n"
                         % (r["rule"], r["n"], r.get("rewritten", 0), r.get("repeated", 0),
                            r.get("moved_on", 0), r["rewritten_of_decided"]))


if __name__ == "__main__":
    main()
