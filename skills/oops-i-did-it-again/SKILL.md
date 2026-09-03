---
name: oops-i-did-it-again
description: Run IMMEDIATELY after any mistake, wrong claim, false pass, or correction. Classifies the error against the known failure modes, then converts it into a MECHANISM (a guard rule, a hook, a gate) instead of a promise to do better. Use when the agent catches its own error, when the user catches one, or when a result turns out to be wrong. Also use when a "green" result looks too good.
---

# oops-i-did-it-again

An audit of 73 session handoffs found one thing that matters above everything else:

> **Failure classes that were turned into machinery stopped happening. Failure classes that
> were only written down as rules did not.**

A wrapper that replaced hand-rolled nested ssh quoting erased an entire error class
permanently. A harness change ended sleep-polling for good. Meanwhile the top rule in the
project's own instruction file was broken the same night it was cited, and another was
broken within 24 hours of being written.

So the output of this skill is never an apology and never a resolution. **It is a diff.**
A guard rule, a hook, a gate, or an explicit "this one cannot be mechanised, here is why".

## STOP first

Do not continue the task. Do not "fix it and move on". The mistake is now the task.

If work is in flight that depends on the wrong thing, say so in one line before anything else.

## Step 1: record the raw evidence, before analysing it

Append to `~/.claude/oops-ledger.md`. Never edit a past entry; corrections are new
entries. Minimum fields:

```
## <ISO timestamp>  <one-line title>
CLASS:     <letter from the table below>
CLAIMED:   what I said, or what the run reported
ACTUAL:    what was true, with the probe that showed it
CAUGHT BY: me | the user | a hook | a control run
EVIDENCE:  path to the raw artefact, kept not deleted
MECHANISM: what now makes this impossible, or why it cannot be mechanised
```

Keeping the wrong artefact is mandatory. A false pass you deleted is a false pass you will
repeat. Copy the failed log to `<name>.false-pass-<timestamp>` before rerunning anything.

## Step 2: classify

| class | signature |
|---|---|
| **A** asserted from memory instead of probing | stated a fact without running the check |
| **B** silent failure | the thing broke and nothing said so |
| **C** measured the wrong thing | the number was real but answered a different question |
| **D** estimated instead of measured | a guessed number entered the reasoning |
| **E** destroyed before verifying | delete/overwrite ahead of the proof |
| **F** assumed a tool contract | flag, API or format taken from memory of another version |
| **G** changed a knob without re-deriving dependents | one edit invalidated a neighbouring assumption |
| **H** state written under duress | handoff or record skipped or panicked |
| **I** long job in the foreground | blocked, polled, or lost to a timeout |

If it fits none, add a new class. Do not force a bad fit. (Class J, "rule stated and
acknowledged, then violated by habit in the same turn", was added this way.)

## Step 3: route by whether it is mechanisable

**Syntactically detectable, so BUILD THE GUARD.** Classes B, E, F, and most of D and I.

1. Add a rule to `hooks/bash-guard.py` (commands) or `hooks/file-guard.py` (Write/Edit).
2. Each rule carries a docstring naming the incident it came from. A rule whose reason has
   been forgotten gets deleted the first time it is inconvenient.
3. **BLOCK only for traps that are never legitimate.** Everything else WARNs. A guard that
   blocks real work gets disabled, and then it protects nothing.
4. A WARN must emit NO `permissionDecision`. Emitting `allow` bypasses the permission
   prompt and makes the guard reduce safety.
5. Test true positives AND true negatives: `bash tests/run-all.sh`.
6. **Replay against real history** before wiring it: `python3 hooks/replay.py`. A first
   draft of the pipe rule fired on 8.1% of real commands; the replay caught it before it
   went live.
7. Prove it fires on the exact command that caused the incident.

**Semantic, not syntactic, so memory plus a written trigger.** Classes A, C, G. A regex
cannot see "you assumed". If the class has now recurred twice or more, consider a
prompt-handler or agent-handler hook that can judge, and in the meantime write the trigger
list down where the next session will read it.

**Genuinely one-off, so a ledger entry only.** Say so explicitly. Not every mistake
deserves a mechanism, and inventing one for a singleton is its own failure.

## Step 4: check for recurrence, and escalate

```bash
grep -c '^CLASS: <letter>' ~/.claude/oops-ledger.md
```

- **1st occurrence:** guard, or ledger entry.
- **2nd:** the existing mechanism did not work. Fix the mechanism, not the instance.
- **3rd or later:** stop and say out loud that the mechanism is failing, and why. Do not
  add a fourth rule on top of three that are not firing.

## Step 5: report in one short paragraph

What was claimed, what was true, who caught it, which class, and **what now prevents it**.
No apology, no self-criticism, no rumination. State the finding and move on.

If the answer to "what now prevents it" is "I will be careful", the skill has failed. Go
back to step 3.

## The tells that should trigger this skill unprompted

- A result that looks too clean. **`5/5 identical` where every string was empty.**
- A step that finished far faster than its budget. 46 s for four 7 GB model loads.
- A gate that passed without producing an artefact you can point at.
- Any count, size or duration you did not run the arithmetic for.
- `--help` that printed nothing, an empty grep, a zero-row table.

A green result you cannot explain is the highest-value moment to run this.

## Reference incidents, all real

| what | class | mechanised as |
|---|---|---|
| smoke gate reported OK while testing nothing (`\| tail` ate the exit code) | B | bash-guard pipe rule, plus `set -o pipefail` |
| `docker run` without `--gpus`, binary died before `--help` printed | F | bash-guard BLOCK, third occurrence |
| `2>/dev/null` hid ENOSPC in a backup job for four days | B | bash-guard WARN when the result is consumed |
| a backup deleted the off-box copy, then checked space | E | measure-before-delete, budget computed first |
| `find -mtime -delete` reaches zero if the producing job stops | B/E | count-based retention instead |
| identity test hashed empty strings, `5/5` false pass | B/C | harness refuses empty captures, `rc=2 INVALID` |
| acceptance regex missed padded numbers, printed an empty table | B | parser refuses to print an empty table |
| `tail -60` truncated the log and lost the configs | C | tee to a file, never rely on terminal output |
| a vendor's behaviour asserted from model memory, then built on | A | file-guard VENDOR-CLAIM on notes and handoffs |
| `systemctl is-active` over four guessed unit names read as "nothing is running" | C | bash-guard enumerate-instead-of-guess rule |

`LESSONS.md` in this repo generalises the whole ledger. Read it once before writing rules
of your own.
