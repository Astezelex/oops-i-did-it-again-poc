# AGENTS.md

Instructions for an agent asked to install, verify, or extend this repo. A human reader
wants `README.md` instead.

## What this is, in one line

Guards that fire at the moment a command is typed, plus the loop that turns a mistake into
a new guard. The premise, from an audit of 73 session handoffs: failure classes turned into
machinery stopped recurring, failure classes written down as rules did not.

## Install, verified at every step

Run these in order. Each has an expected result. If one does not match, stop and report it
rather than continuing.

```bash
git clone <repo> ~/.claude/oops && cd ~/.claude/oops
bash tests/run-all.sh          # expect: ALL SUITES PASS, 95 cases, 0 failures
./install.sh --dry-run         # expect: prints the settings.json it WOULD write
./install.sh                   # expect: "installed skill:", "backed up:", "wired: ..."
```

`install.sh` runs the suites itself and refuses to install if any fail. It backs up
`settings.json` before touching it, is idempotent (rerun prints "already correct"), and
`--uninstall` removes only what it added.

Then prove the hook actually fires in the live session, because an entry in `settings.json`
is not evidence:

```bash
python3 hooks/guard.py --command 'find /backups -mtime +7 -delete'   # expect exit 1 + reason
python3 hooks/replay.py 12                                          # expect a rate report
```

`replay.py` is the important one. It reports how often these rules fire on **this user's**
real history. Read it out to them: block rate first, then any warn above about 5%. On the
machine the rules were written for, the numbers are 8.5% warn and 0.5% block over 3,502
commands. Materially different numbers on this machine mean a rule needs narrowing here.

## Do not

- **Do not commit a ledger.** `~/.claude/oops-ledger.md` is an operations diary of real
  systems. `.gitignore` already excludes it. Before any push of a fork, grep the diff for
  host names, user names, client names, tokens and internal paths.
- **Do not turn WARNs into BLOCKs** because a warning looks weak. A guard that blocks real
  work gets uninstalled, and then it protects nothing. BLOCK is only for traps that are
  never legitimate.
- **Do not emit `permissionDecision: "allow"` for a warning.** That bypasses the normal
  permission prompt and makes the guard reduce safety. A WARN emits `additionalContext`
  and no decision.
- **Do not add a rule you have not replayed.** A first draft of the pipe rule fired on 8.1%
  of real commands.
- **Do not edit `hooks/*.py` in place on someone's machine without a backup.** Copy first,
  then edit, then rerun `tests/run-all.sh`.

## Adding a rule (the actual work)

1. Write the ledger entry first, from `ledger/LEDGER-TEMPLATE.md`. Keep the failed artefact,
   do not delete it.
2. Classify it against the table in `skills/oops-i-did-it-again/SKILL.md`. If it fits none,
   add a class.
3. Decide if it is syntactically detectable at all. "Asserted from memory", "measured the
   wrong thing" and "changed a knob without re-deriving dependents" usually are not, and a
   regex pretending otherwise produces a rule that never fires. Say so out loud instead.
4. Write the rule as a function in `hooks/bash-guard.py` returning `("WARN"|"BLOCK", text)`
   or `None`, with a docstring naming the incident. Register it in `RULES`.
5. Add a true positive AND a true negative to `tests/test_rules.py`. The true negative is
   the one that keeps the guard installed.
6. `bash tests/run-all.sh`, then `python3 hooks/replay.py 12`. Compare the new rate against
   the previous one.
7. Prove it fires on the exact command from the incident, and quote that output.

## Reporting back

State: which files changed, the suite result as a count, the replay rates before and after,
and what the new rule blocks or warns on. If you could not mechanise the failure, say that
explicitly and say why. "I will be careful" is not an outcome this repo accepts.

## Porting to another harness

`PORTING.md` has the wire contract and a checklist. `hooks/guard.py` is the harness-neutral
front door: argv in, exit code out (0 pass, 1 warn, 2 deny), same rules. Forks that adapt
this to other agent frameworks are wanted, and the interesting part to keep is the loop and
the replay step, not these particular regexes.
