# What 43 logged mistakes actually taught

This is the generalisable content of one private error ledger. The ledger itself does not
ship: it is a real operations diary of real machines. What follows is every lesson from it
that transfers, with the incident stripped down to its shape.

Counts are as of 2026-09-03 and are regenerated from the ledger by
`analysis/ledger_stats.py`, which emits structure only, never entry text.

Read the distribution first, because it is the surprising part.

| class | count | what it is |
|---|---|---|
| **C** measured the wrong thing | 13 | the number was real and answered a different question |
| **B** silent failure | 9 | it broke and nothing said so |
| **F** assumed a tool contract | 6 | a flag or format remembered from another version |
| **A** asserted from memory | 3 | stated as fact without a probe |
| **G** knob changed, dependents not re-derived | 3 | one edit invalidated a neighbouring assumption |
| **E** destroyed before verifying | 2 | delete or overwrite ahead of the proof |
| **D** estimated instead of measured | 1 | a guessed number entered the reasoning |
| **J** rule acknowledged, then broken | 1 | added later, when a rule was violated in the same turn it was cited |
| **K** derived artefact carried its source | 1 | added later: a generated stats file quoted the private commands it counted |

Almost nobody expects C to be the largest. Wrong answers from broken tools are the ones
people build for, and they are only a third of the total. The dominant failure is a
**working tool, a real number, and the wrong question**. It is also the hardest class to
mechanise, which is why several lessons below are checks a person has to run, not regexes.

---

## 1. The finding that outranks the rest

An audit of 73 session handoffs asked which failure classes stopped recurring. The split
was clean:

- Classes turned into **machinery** (a wrapper, a hook, a gate, a harness change) stopped.
- Classes written down as **rules** kept happening, including the rule broken the same
  night it was written, and the one broken within 24 hours.

An instruction not to make a mistake is a probability reduction at best. A guard that runs
at the moment the command is typed is a category removal. So the standing question after
any error is not "what should I remember" but **"what makes this impossible, or at least
loud"**.

Corollary, learned twice: **a guard that blocks legitimate work gets switched off, and then
it protects nothing.** BLOCK is only for traps that are never legitimate. Everything else
warns.

---

## 2. Measuring the wrong thing (13 of 43)

**A number is not a finding until you can say which question it answers.** These all
produced real, correct numbers.

- **A metric with no completion rate is unreadable.** An accuracy gap between two models
  was read as a reasoning-quality difference. It was a token cap: one model was being cut
  off mid-answer. The fix that generalises is a gate that refuses to print accuracy alone
  and always emits accuracy, completion rate, cap rate and accuracy-given-completion
  together, exiting non-zero when the cap rate is high enough to matter. **Make the caveat
  travel with the number by construction.**
- **Absence of evidence needs a positive control.** `journalctl -u app | grep -c 'GET|POST'`
  returned 0, which was read as "no request ever arrived". The service does not log
  requests at all. Before reading a zero as proof that something did not happen, grep for a
  line you know is there.
- **Select subjects by identity, never by first row.** `list-sessions | awk 'NR==1'` picked
  root's tty session out of three and made a live graphical desktop look like a console-only
  box. An unordered listing reduced to one row is whichever row the tool printed first.
- **Do not test a candidate list you guessed.** `systemctl is-active gdm gdm3 sddm lightdm`
  returned four inactives, read as "no display manager". The real one was a fifth name
  nobody listed. Enumerate what exists; a negative over guessed names proves nothing.
- **The proxy is not the artefact.** An open port is not a working page. A file that
  compiles is not a working feature. `node --check` passes a `ReferenceError` straight to
  the branch. A handler that fires is not a control a human can reach: hit-test it (real
  rect, on screen, `elementFromPoint` returns your element), then look at the rendered
  result. Eight text-level gates once passed on a blank screen.
- **Verify through the route the user takes.** A change was declared verified by 22
  assertions against internal functions. Every one of them bypassed the HTTP layer where
  the actual defect lived.
- **A test that touches a datastore must first prove which datastore.** A guard test
  reported "ALL TESTS OK" against an empty throwaway database. Two assertions fix the whole
  class: assert the resolved path is the one you mean, and refuse to run when the fixture
  set comes back empty.
- **Synthetic padding is only valid for content-independent metrics.** Random-token filler
  is fine for VRAM, fit and allocation. It invalidates acceptance rate, perplexity and
  accuracy. Before padding a context, name the metric and say whether it depends on what
  the tokens say.
- **One composition is not a statement about the variable.** "The drafter degrades past 8k"
  was generalised from a single synthetic prefix. Depth was the label; composition was the
  cause.
- **A component price is not the total.** A per-seat figure was quoted as the monthly bill.
  When a number will drive a decision, restate what it is a price *of*.
- **Three bad measurements in a row can hide correct code.** In one incident the feature
  worked the whole time and every measurement of it was broken differently. If two
  successive measurements disagree, suspect the measurement before the code.

---

## 3. Silent failure (9 of 43)

**Every one of these was green.** The signal was always available and always ignored.

- **A pipe into `tail`/`head` returns tail's exit code.** `cmd | tail -5 || echo FAILED`
  can never print FAILED: `tail` exits 0 on empty input. This is how a smoke gate reported
  OK while every invocation inside it failed on a bad flag. `set -o pipefail`, or capture to
  a file and test separately.
- **`2>/dev/null` on a real operation hides the cause, not the failure.** A nightly backup
  logged "pull FAILED" for four days; the discarded stderr said "No space left on device".
- **`|| true` on a measurement is a lie about optionality.** A VRAM probe pointed at a file
  that did not exist. The discard plus `|| true` ate both the error and the exit code, the
  section printed empty, and a 5,400 MiB estimate took the missing number's place. Measured
  truth was 967 MiB. **An empty section where a number belongs is a failed measurement, not
  a quiet pass.**
- **An empty capture must be an error.** An identity test hashed empty strings and reported
  5/5 identical. Harnesses now exit `rc=2 INVALID` when any capture is empty, and parsers
  refuse to print an empty table, dumping the unparsed lines instead.
- **Read the clock as evidence.** 46 seconds for four 7 GB model loads was the tell that the
  gate was testing nothing, and it was visible before anything else was.
- **Syntax checks are not smoke tests.** `node --check` and `py_compile` prove the file
  parses. They say nothing about whether it runs.

The general form: **a check whose failure mode is silence is not a check.** Make the
failure branch print something a human would notice, and prefer counting produced output
(characters, rows, files) over trusting exit 0.

---

## 4. Assumed tool contracts (6 of 43)

**Flags move between builds, and the model's memory of a tool is a memory of some other
version of it.**

- Read `--help` of the binary in front of you, not the one you remember.
- **A tool can do nothing and exit 0.** A download with several bare `--exclude` patterns
  fetched nothing and reported success; the flag must be repeated per pattern. Every
  download or build step needs an artefact check afterwards: does the file exist, is it the
  expected size. That check is the part that generalises across every tool.
- **A missing flag is not a missing feature.** `pgrep -q` does not exist on all builds; it
  exited non-zero, which inverted a `until ! pgrep` wait-loop and declared a live download
  finished. Prefer loop forms with no negation to invert, and **always pair a wait-loop with
  a magnitude check on the thing being waited for** ("5 GB present where 55 GB is expected"
  is the check that caught it).
- **A CUDA binary without GPU access dies before it prints anything**, so its empty
  `--help` looks exactly like "that flag does not exist". This cost a retracted upstream bug
  report. When a tool prints nothing, prove it started.
- **Before concluding a thing does not exist, enumerate every distribution channel**:
  release assets, container images, package managers, and the images already on the machine.
  One "no binary exists" deferral was wrong because the binary was inside a container that
  was already running locally.

---

## 5. Asserted from memory (3 of 43)

- **Vendor behaviour stated from memory becomes a design lever.** "Gmail uses the template
  name to fill the subject line" went into a handoff as fact and a filter was keyed on it.
  Two real sends disproved it. This is the one class here that is worth a hook: notes and
  handoffs are what the next session treats as fact, so `file-guard.py` warns when a
  sentence asserts a third-party product's behaviour with no probe and no INFERRED label
  nearby. Either probe it, or write the uncertainty next to it.
- **An auth error names neither input.** SMTP 535 and IMAP `[AUTHENTICATIONFAILED]` are
  ambiguous by design. Six failed logins were blamed on the password; the username had a
  hyphen where it needed a dot. A value the user reads back to you is not a probe of it.
- **Grep your own repo before analysing a result.** A finding was written up as new; the
  project's own published README already stated it. Prior art in your own work is the
  cheapest literature review there is and costs one grep.

---

## 6. Destroy-before-verify and stale writes (2 of 43, and the most expensive)

- **Copy, verify, then delete.** Never `rm -rf X && cp ... X`. Compute the space budget
  before deleting anything, not after.
- **Time-based pruning reaches zero.** `find -mtime +N -delete` keeps ageing out backups
  after the job that produced them has stopped. Count-based retention (`ls -t | tail -n
  +$((KEEP+1))`) cannot empty the directory.
- **Never overwrite a script while it is executing.** Bash reads the file as it runs; the
  running process starts executing the new bytes at its old offset.
- **A write based on a stale read silently destroys someone else's edit.** A save built on
  a read from ten minutes earlier clobbered a correction made in between. The fix is
  compare-and-swap: send the value you believe is current, and have the writer refuse when
  the stored value differs.

---

## 7. Knobs, dependents, and parked decisions (3 of 43)

- **After changing a layout or config variable, sweep for constants derived from its old
  value**, and prove each survivor by measurement, not by eye. Three stale geometry
  constants shipped this way; the sweep that "found" them was a habit, not a command.
- **When a data file and the code that reads it disagree, never fix it in the data file.**
  Re-run the documented path end to end into a scratch directory and diff its output
  against the committed artefact. Two commands, and the broken generator would have failed
  loudly instead of shipping.
- **Anything parked must be recorded with the constraint that justified parking it.** A
  deferral outlived its reason by weeks because the reason lived only in the decision, not
  in the note. Keep one file of parked items; when a constraint changes, grep it.

---

## 8. Scale, and the arithmetic you skipped

- **Prove it small, then bigger, then all: n=1, n=5, n=all.** A 20-cell GPU sweep was armed
  with no n=1 proof and no ETA.
- **A passing proof does not survive a change to the prompt, the flags, the batch path or a
  bugfix.** Re-prove. An indexing driver was relaunched over 21,790 files on the strength of
  a single-file test that predated two changes; it emitted zero records for the first 15.
- **Make the script print its own ETA arithmetic before it starts**, computed from measured
  per-unit cost, and refuse to launch when the total exceeds a budget typed by the caller.
  The same shape catches "`--limit N`" being read as "N items" when the runner multiplies it
  by a subset count.
- **A script that has never executed is not a plan, it is a draft.**
- **Dry-run every destructive write**, and keep the output.

---

## 9. Evidence discipline

- **Keep the wrong artefact.** Copy the failed log to `<name>.false-pass-<timestamp>` before
  rerunning. A false pass you deleted is one you will repeat, and it is the only proof of
  what the failure actually looked like.
- **Record the full output**, including the fields you did not ask about: the finish reason,
  the truncation flag, the aborted run. The cap-rate lesson in section 2 exists because a
  harness discarded exactly that field.
- **`tail -N` hides the answer and swallows the exit code.** Tee to a file and grep the
  file.
- **`grep`, do not range-read, when the question is "does a rule for X exist".** A bounded
  `sed -n 'a,bp'` can prove presence and never absence. A duplicate CSS rule shipped on
  exactly this.

---

## 10. Turning one of these into a mechanism

The loop that produced everything above:

1. **Stop.** The mistake is now the task. If work in flight depends on the wrong thing, say
   so first.
2. **Write the raw entry before analysing it**, with the artefact path.
3. **Classify.** If it fits no class, add one, do not force it.
4. **Route.** Syntactically detectable, so write the guard rule. Semantic, so write the
   trigger down and watch for the second occurrence. Genuinely one-off, so say that out loud
   and stop.
5. **Test the guard both ways**, true positives and true negatives, then **replay it against
   real history** before wiring it. A first draft of the pipe rule fired on 8.1% of real
   commands. Nothing but a replay would have shown that.
6. **Count recurrences.** Second occurrence means the mechanism failed, so fix the
   mechanism. Third means stop adding rules and say the approach is not working.

The failure mode of this whole practice is a growing pile of rules that nobody enforces.
The counter to that is step 5: a rule that has been replayed, tested and proven to fire on
its own incident is machinery. Everything else is a note.
