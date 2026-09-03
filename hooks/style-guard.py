#!/usr/bin/env python3
"""style-guard: Stop hook that checks what I actually wrote against the standing style rules.

Built after using a banned phrase in the same reply that acknowledged the rule banning it,
and after noticing a style rule in CLAUDE.md had been violated continuously for a whole
session without anyone catching it.

bash-guard and file-guard inspect tool calls. Neither can see prose. The Stop hook is the
only handler that sees the finished message, so it is the only place this class can be
mechanised at all.

Exit 2 on Stop blocks the turn from ending and returns stderr to the model as context, so
the offending sentence is rewritten before the user ever reads it.

The two rules below are EXAMPLES from one person's CLAUDE.md. Replace them with your own.
The mechanism is the point: a rule the model must obey in prose is only enforceable here.

Fails open on any internal error: a broken style check must never wedge a session.

⛔ LOOP HAZARD, read before deploying this one. A Stop hook that exits 2 forever is a
session that can never end. Two independent brakes are wired in below:

  1. `stop_hook_active`, which the harness sets once a Stop hook has already blocked. Not
     every build sends it, so it is not sufficient on its own.
  2. A session-scoped counter in the temp directory. After MAX_BLOCKS consecutive blocks
     the guard gives up and lets the turn end, no matter what the text says. A style rule
     is not worth wedging someone's session over.

Test any new rule with a phrase the model cannot easily avoid before you trust it.
"""
import json
import os
import re
import sys
import tempfile
import time

# After this many consecutive blocks in one session, let the turn end anyway.
MAX_BLOCKS = 2
# Forget the counter after this long, so a later turn starts fresh.
COUNTER_TTL_S = 900

# (compiled pattern, what to say instead)
RULES = [
    # Catches the SPLIT construction too. The incident that produced this rule was
    # "I would rather tell you that now THAN after a weekend", where the literal string
    # "rather than" never appears. A first draft matched only the adjacent form and would
    # have passed the exact sentence it was written for.
    (re.compile(r'\brather\b(?:\W+\w+){0,10}?\W+\bthan\b', re.I),
     'the "rather ... than" construction is a known model tic and reads unnatural. '
     'Say it as a person would: "X, not Y", "instead of X", '
     '"I am telling you now, before the weekend is spent".'),
    (re.compile(r'—'),
     'em dash. CLAUDE.md: "No em dashes, ever, anywhere." Use a comma, a colon, '
     'a full stop, or brackets.'),
]

FENCE = re.compile(r'```.*?```', re.S)
INLINE = re.compile(r'`[^`\n]*`')


def last_assistant_text(path):
    """Return the text of the final assistant message in the transcript, or ''."""
    if not path or not os.path.exists(path):
        return ""
    text = ""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            msg = rec.get("message") or {}
            if rec.get("type") != "assistant" and msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = [b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text"]
                if parts:
                    text = "\n".join(parts)
    return text


def strip_uncheckable(text):
    """Remove code and quoted material. Rules govern MY prose, not quoted evidence.

    A log line, a file being cited, or the user's own words may legitimately contain a
    banned phrase, and flagging those would make the guard a nuisance and get it removed.
    """
    text = FENCE.sub(" ", text)
    text = INLINE.sub(" ", text)
    kept = []
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith(">") or s.startswith("|"):
            continue
        kept.append(line)
    text = "\n".join(kept)
    text = re.sub(r'"[^"\n]{0,400}"', " ", text)
    return text


def _counter_path(session_id):
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(session_id or "nosession"))[:64]
    return os.path.join(tempfile.gettempdir(), "style-guard-%s.count" % safe)


def blocks_so_far(session_id):
    """Consecutive blocks already issued in this session, 0 if none or expired."""
    p = _counter_path(session_id)
    try:
        with open(p, encoding="utf-8") as fh:
            ts, n = fh.read().split()
        if time.time() - float(ts) > COUNTER_TTL_S:
            return 0
        return int(n)
    except Exception:
        return 0


def record_block(session_id, n):
    try:
        with open(_counter_path(session_id), "w", encoding="utf-8") as fh:
            fh.write("%f %d" % (time.time(), n))
    except Exception:
        pass


def clear_blocks(session_id):
    try:
        os.unlink(_counter_path(session_id))
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    session_id = data.get("session_id")

    # Brake 1: the harness sets this when a Stop hook already blocked once. Not every
    # build sends it, which is why brake 2 exists.
    if data.get("stop_hook_active"):
        clear_blocks(session_id)
        return 0

    # Brake 2: never block more than MAX_BLOCKS times in a row, whatever the text says.
    if blocks_so_far(session_id) >= MAX_BLOCKS:
        clear_blocks(session_id)
        return 0

    text = last_assistant_text(data.get("transcript_path"))
    if not text.strip():
        return 0

    checkable = strip_uncheckable(text)
    hits = []
    for rx, advice in RULES:
        m = rx.search(checkable)
        if m:
            start = max(0, m.start() - 45)
            ctx = checkable[start:m.end() + 45].replace("\n", " ").strip()
            hits.append(f'found "{m.group(0)}" in: ...{ctx}...  -> {advice}')

    if hits:
        record_block(session_id, blocks_so_far(session_id) + 1)
        sys.stderr.write(
            "style-guard: your reply breaks a standing style rule. Rewrite the sentence "
            "and send it again; do not explain or apologise for the edit.\n  "
            + "\n  ".join(hits) + "\n")
        return 2
    clear_blocks(session_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
