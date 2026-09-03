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

Usage:  python3 replay.py [n_transcript_files]      (default 12)

Reads Claude Code transcripts from ~/.claude/projects/*/*.jsonl, extracts every Bash
command, feeds each to bash-guard.py exactly as the harness would, and reports how often
each distinct finding fired plus two example commands for it.

Read the output like this:
  BLOCKS (deny) on anything you recognise as legitimate work  -> the rule is wrong, fix it
  a WARN above ~5% of commands                                -> too noisy, narrow it
  a rule that fires 0 times over hundreds of commands         -> prove it fires on the
                                                                 original incident by hand
"""
import json, glob, os, subprocess, sys, collections

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bash-guard.py')
TRANSCRIPTS = os.path.expanduser('~/.claude/projects/*/*.jsonl')

files = sorted(glob.glob(TRANSCRIPTS), key=os.path.getmtime, reverse=True)[:N]
commands = []
for f in files:
    try:
        with open(f, encoding='utf-8') as fh:
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

count = collections.Counter()
examples = collections.defaultdict(list)
denied = []
for cmd in commands:
    p = subprocess.run(['python3', GUARD], input=json.dumps(
        {'tool_name': 'Bash', 'tool_input': {'command': cmd}}),
        capture_output=True, text=True)
    if not p.stdout.strip():
        continue
    try:
        out = json.loads(p.stdout)
    except Exception:
        continue
    hso = out.get('hookSpecificOutput') or {}
    text = hso.get('additionalContext') or hso.get('permissionDecisionReason') or ''
    if hso.get('permissionDecision') == 'deny':
        denied.append(cmd)
    # Bucket by the opening of the finding, so this works for any rule set without
    # a hand-maintained label table.
    for part in text.split(' | '):
        part = part.replace('bash-guard: ', '').strip()
        if not part:
            continue
        key = ' '.join(part.split())[:58]
        count[key] += 1
        if len(examples[key]) < 2:
            examples[key].append(cmd[:96])

print()
for key, n in count.most_common():
    print('%4d  (%4.1f%% of commands)  %s' % (n, 100.0 * n / len(commands), key))
    for ex in examples[key]:
        print('        %s' % ex)
print()
print('DENIED (block): %d  (%.1f%%)' % (len(denied), 100.0 * len(denied) / len(commands)))
for d in denied[:5]:
    print('        %s' % d[:96])
