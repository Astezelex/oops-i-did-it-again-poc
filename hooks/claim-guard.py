#!/usr/bin/env python3
"""claim-guard: Stop hook that catches ABSENCE claims and DECAY COUNTS in the agent's prose.

Built after the agent told the user "31 memory files are linked from nowhere", off a grep
that covered one index and neither of the two park files that index names in its own header.
The true count was 3. Class C in the ledger (measured the wrong thing), which was then 15 of
47 entries and the largest class. Every earlier mechanism for class C was a written rule;
none of them held.
bash-guard and file-guard see tool calls, style-guard sees prose style. Nothing was
watching the shape of an evidence claim, so this does.

TWO rule families, both narrow on purpose:

  1. ABSENCE. "linked from nowhere", "nothing references", "no caller exists", "never
     called". An absence claim is only as wide as the search behind it. A grep over one
     file cannot support "nowhere"; it supports "not in this file".

  2. DECAY COUNTS. "31 orphans", "12 dead links", "8 broken references". The user's
     point, and the better half of the lesson: in a well maintained environment a
     large decay count should first make you doubt the INSTRUMENT, not the system. The
     31 were also thematically coherent, all one era and one topic, and rot does not
     arrive sorted. A clean cluster is the signature of a deliberate act, in that case
     someone parking them on purpose.

EXEMPTION: if the paragraph naming the claim also names the scope of the search
("all three indexes", "across every", "exhaustive", or a canonical audit tool), it
passes. The guard wants the search named, it does not want the claim suppressed.

Exit 2 on Stop blocks the turn and hands stderr back as context, so the sentence gets
its evidence attached before the user ever reads it. Never blocks more than MAX_BLOCKS times
in a row, and fails open on any internal error: a broken guard must not wedge a session.
"""
import json
import os
import re
import sys
import tempfile
import time

MAX_BLOCKS = 1              # one interruption per session is enough to make the point
COUNTER_TTL_S = 900

ABSENCE = [
    (re.compile(r"\b(?:linked|referenced|listed|documented|mentioned|indexed)\s+"
                r"(?:from\s+|in\s+)?nowhere\b", re.I),
     "an absence claim"),
    # Deliberately NOT "nothing reads/writes/uses/calls": replay over 5,465 real messages
    # showed those are almost always a precise statement about ONE named identifier while
    # reading the code, already evidenced. The failure this guard exists for is a claim
    # about a SET, so only set-shaped verbs stay.
    (re.compile(r"\bnothing\s+(?:references|links to|points to|indexes|lists)\b", re.I),
     "an absence claim"),
    # Up to two modifier words, so "no MEMORY FILE references ..." matches the same way
    # "no file references ..." does. Missing that cost a must-fire case in the unit test.
    (re.compile(r"\bno\s+(?:\w+\s+){0,2}(?:files?|scripts?|entry|entries|references?|"
                r"callers?|tests?|records?|indexes|handoffs?|notes?|memories)\s+"
                r"(?:exists?|references?|links?|uses?|calls?|mentions?)\b", re.I),
     "an absence claim"),
    # Same reason: "never called/used/read" is ordinary single-identifier code talk.
    (re.compile(r"\bnever\s+(?:linked|referenced|indexed|listed|documented)\b", re.I),
     "an absence claim"),
]

DECAY_NOUN = (r"orphans?|orphaned|dead links?|broken links?|dangling|unreferenced|"
              r"unlinked|missing files?|stale entries|untracked files?")
DECAY = [
    (re.compile(r"\b\d{2,}\s+(?:%s)\b" % DECAY_NOUN, re.I), "a decay count"),
    (re.compile(r"\b(?:%s)\s*[:=]\s*\d{2,}\b" % DECAY_NOUN, re.I), "a decay count"),
]

# 3. COMPONENT ABSENCE. "no importer exists", "nothing ingests it", "has never
#    imported this file", "stores nothing like it", "no shared key". Added after a
#    session-start summary relayed a handoff's "no importer exists" as fact. There WAS
#    one, three months old and wired live; run on the real workbook it parsed 1,479
#    orders. The claim was not unproven, it was inverted. Class A, fifth occurrence,
#    and the first mechanism aimed at it.
#    Narrow by design: only the shape "named component does not exist / never ran",
#    which is a claim nobody can make without having searched the tree for it.
_COMPONENT = (r"importers?|parsers?|ingesters?|exporters?|migrations?|watchers?|"
              r"shared keys?|common keys?|join keys?|machinery|pipelines?")
COMPONENT = [
    (re.compile(r"\bno\s+(?:\w+\s+){0,2}(?:%s)\s+(?:exists?|is present)\b" % _COMPONENT, re.I),
     "a component-absence claim"),
    (re.compile(r"\b(?:there is|there's)\s+no\s+(?:\w+\s+){0,2}(?:%s)\b" % _COMPONENT, re.I),
     "a component-absence claim"),
    (re.compile(r"\bnothing\s+(?:has\s+)?(?:ingests?|ingested|imports?|imported|"
                r"parses?|parsed|consumes?|consumed)\b", re.I),
     "a component-absence claim"),
    (re.compile(r"\b(?:has|have|had)\s+never\s+(?:ingested|imported|parsed|consumed)\b", re.I),
     "a component-absence claim"),
    (re.compile(r"\bstores?\s+nothing\s+(?:like|of the sort|comparable|equivalent)\b", re.I),
     "a component-absence claim"),
]

SCOPE_MARKERS = re.compile(
    r"\ball (?:three|four|five|of the|the) \w+|\bacross (?:all|every)\b|\bexhaustive\b|"
    r"\bevery index\b|\bwhole (?:system|set|tree|corpus)\b|"
    r"\bin scope\b|\bfull sweep\b|"
    # Provenance and decision exemptions, added 2026-09-04 with the COMPONENT family.
    # The guard wants the source named, not the sentence suppressed. Attributing a claim
    # to a handoff/memory/another person is the CORRECT move and must not be punished,
    # and "no route exists because it was rejected" is a decision, not a discovery.
    r"\bhandoffs? says?\b|\bper the handoff\b|\bthe handoff\b|\bmemory says\b|"
    r"\baccording to\b|\b(?:he|she|they|the user) said\b|\bnot (?:yet )?(?:checked|probed|verified)\b|"
    r"\bunverified\b|\bINFERRED\b|"
    r"\b(?:rejected|by design|on purpose|deliberately|by decision|intentionally)\b", re.I)

ADVICE = (
    "%s. Name the search that backs it, in the sentence: which files or hosts were in "
    "scope, and what the denominator was. A grep over one file supports \"not in this "
    "file\", never \"nowhere\". And check the magnitude before you believe it: in a "
    "maintained system a large decay count is more often a wrong instrument than real "
    "rot, and a decay set that is thematically coherent (one era, one topic) is the "
    "signature of a deliberate act, not decay. Incident: \"31 memory files linked from "
    "nowhere\", true count 3, the other 28 were parked on purpose."
)


COMPONENT_ADVICE = (
    "%s. Saying a component does not exist is a claim about the whole tree, so it needs "
    "the search that covered the tree, named in the sentence: the find/grep you ran and "
    "where it rooted. If the claim came from a handoff, a note or memory rather than from "
    "your own probe this session, write \"handoff says\" and keep it separate from what "
    "you verified. Incident: a handoff's \"no importer exists\" was relayed as fact; an "
    "importer had been reading exactly that file for three months, and parsed 1,479 "
    "orders from it on the first run."
)


def advice_for(kind):
    if "component" in kind:
        return COMPONENT_ADVICE % kind.capitalize()
    return ADVICE % kind.capitalize()


# A claim inside a conditional is a description of behaviour, not an assertion about
# the world. Replay 2026-09-04 fired on "If nothing parses, it says so and dumps the
# lines it failed on", which is documentation of a guard, not a finding.
CONDITIONAL = re.compile(r"^\s*(?:if|when|unless|should)\b|\.\s+If\b", re.I)

FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`\n]*`")


def last_assistant_text(path):
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
    """Code, quotes, tables and block quotes are evidence being shown, not claims."""
    text = FENCE.sub(" ", text)
    text = INLINE.sub(" ", text)
    kept = []
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith(">") or s.startswith("|"):
            continue
        kept.append(line)
    text = "\n".join(kept)
    return re.sub(r'"[^"\n]{0,400}"', " ", text)


def paragraphs(text):
    for para in re.split(r"\n\s*\n", text):
        if para.strip():
            yield para


def findings(text):
    """(matched string, kind, paragraph) for every unexcused claim."""
    out = []
    for para in paragraphs(strip_uncheckable(text)):
        if SCOPE_MARKERS.search(para):
            continue                     # the search is named, that is all this wants
        if CONDITIONAL.search(para):
            continue                     # "If nothing parses, it says so" describes, not claims
        for rx, kind in ABSENCE + DECAY + COMPONENT:
            m = rx.search(para)
            if m:
                out.append((m.group(0), kind, para))
                break
    return out


def _counter_path(session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id or "nosession"))[:64]
    return os.path.join(tempfile.gettempdir(), "claim-guard-%s.count" % safe)


def blocks_so_far(session_id):
    try:
        with open(_counter_path(session_id), encoding="utf-8") as fh:
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
    if data.get("stop_hook_active"):
        clear_blocks(session_id)
        return 0
    if blocks_so_far(session_id) >= MAX_BLOCKS:
        clear_blocks(session_id)
        return 0

    text = last_assistant_text(data.get("transcript_path"))
    if not text.strip():
        return 0
    hits = findings(text)
    if not hits:
        clear_blocks(session_id)
        return 0

    matched, kind, para = hits[0]
    ctx = " ".join(para.split())[:180]
    sys.stderr.write(
        'claim-guard: "%s" in: %s...\n  -> %s\n' % (matched, ctx, advice_for(kind)))
    record_block(session_id, blocks_so_far(session_id) + 1)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)          # fail open, always
