#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replay bash-guard against REAL commands from past transcripts.

Why this exists, and why it is the least obvious file in this repo: the first version of
the pipe rule fired on 8.1% of real commands. Only a replay over actual history caught
that, before the rule ever went live. A guard that shouts at ordinary work gets switched
off, and then it protects nothing.

Run it BEFORE wiring a new rule, and again after every edit to one. A rule is not finished
when it fires on the incident that caused it. It is finished when you know its rate on
work you did not write it for.

Usage:  python3 replay.py [n_transcript_files] [--hits hits.jsonl]      (default 12)

Reads Claude Code transcripts from ~/.claude/projects/*/*.jsonl, extracts every Bash
command, shapes it exactly as the hook does (heredoc bodies that are content are removed),
runs every rule in RULES on it, and reports per RULE: how often it fired, at which level,
and two example commands. `--hits` also writes every hit as JSON lines, for sampling.

⛔ v2: hits are counted per rule NAME. v1 bucketed by the first 58 characters of the
message, and messages carry numbers (`the outer timeout 90 ...`, `... timeout 60 ...`), so
one rule was split across many rows and its real rate never appeared anywhere. The per-rule
count is what exposed a rule whose BLOCKs were two-thirds false (see LESSONS.md).

Read the output like this:
  BLOCK on anything you recognise as legitimate work          -> the rule is wrong, fix it
  a WARN above ~5% of commands                                -> too noisy, narrow it
  a rule that fires 0 times over thousands of commands        -> prove it fires on the
                                                                 original incident by hand
Then SAMPLE the hits of every rule that moved (`--hits`). A rate says how often a rule
fires, never whether it was right to.
"""
import collections
import glob
import importlib.util
import json
import os
import sys

args = [a for a in sys.argv[1:]]
hits_path = None
if "--hits" in args:
    i = args.index("--hits")
    hits_path = args[i + 1]
    del args[i:i + 2]
N = int(args[0]) if args else 12

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bash-guard.py')
spec = importlib.util.spec_from_file_location("bash_guard", GUARD)
bg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bg)
TRANSCRIPTS = os.path.expanduser('~/.claude/projects/*/*.jsonl')

files = sorted(glob.glob(TRANSCRIPTS), key=os.path.getmtime, reverse=True)[:N]
commands = []
for f in files:
    try:
        with open(f, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                content = (rec.get('message') or {}).get('content')
                if not isinstance(content, list):
                    continue
                for c in content:
                    if (isinstance(c, dict) and c.get('type') == 'tool_use'
                            and c.get('name') == 'Bash'):
                        cmd = (c.get('input') or {}).get('command')
                        if cmd:
                            commands.append(cmd)
    except Exception:
        continue

print('files: %d, commands: %d' % (len(files), len(commands)))
if not commands:
    sys.exit('no commands found in %s' % TRANSCRIPTS)

fires = collections.Counter()
levels = collections.defaultdict(collections.Counter)
examples = collections.defaultdict(list)
any_warn = any_block = 0
out = open(hits_path, 'w', encoding='utf-8') if hits_path else None
for cmd in commands:
    shaped = bg.strip_written_heredocs(cmd)
    w = b = False
    for rule in bg.RULES:
        try:
            hit = rule(shaped)
        except Exception:
            continue                  # the hook fails open on a broken rule; so does this
        if not hit:
            continue
        name = rule.__name__
        fires[name] += 1
        levels[name][hit[0]] += 1
        w |= hit[0] == 'WARN'
        b |= hit[0] == 'BLOCK'
        if len(examples[name]) < 2:
            examples[name].append(' '.join(cmd.split())[:96])
        if out:
            out.write(json.dumps({'rule': name, 'level': hit[0], 'cmd': cmd}) + '\n')
    any_block += b
    any_warn += w and not b
if out:
    out.close()

n = len(commands)
print('any WARN:  %d  (%.1f%%)' % (any_warn, 100.0 * any_warn / n))
print('any BLOCK: %d  (%.2f%%)' % (any_block, 100.0 * any_block / n))
print()
for name, k in fires.most_common():
    lv = ' '.join('%s %d' % kv for kv in sorted(levels[name].items()))
    print('%5d  %5.2f%%  %-14s %s' % (k, 100.0 * k / n, lv, name))
    for ex in examples[name]:
        print('        %s' % ex)
silent = [r.__name__ for r in bg.RULES if not fires[r.__name__]]
if silent:
    print('\nfired 0 times (prove by hand that they fire on their incident):')
    print('  ' + ', '.join(silent))
