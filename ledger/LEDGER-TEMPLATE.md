# OOPS LEDGER

Append-only record of mistakes, wrong claims and false passes. Never edit a past entry;
add a correction entry instead. Written by the `oops-i-did-it-again` skill.

The purpose is not confession. It is **recurrence detection**: the third time a class
appears, the mechanism guarding it has failed, and the mechanism is what needs fixing, not
the instance.

    grep -c '^CLASS: B' oops-ledger.md

Classes:
A asserted-from-memory · B silent-failure · C measured-wrong-thing · D estimated-not-measured
E destroyed-before-verifying · F assumed-tool-contract · G knob-without-dependents
H state-under-duress · I long-job-foreground

Add your own class when something fits none of these. Do not force a bad fit.

Keep this file OUT of any repo you publish. It is an operations diary of real systems, and
it will name hosts, services, people and mistakes made on their behalf.

---

## <ISO timestamp>  <one-line title, the mistake not the topic>
CLASS:     <letter>. <n>th occurrence of this class.
CLAIMED:   what I said, or what the run reported
ACTUAL:    what was true, and the probe that showed it
CAUGHT BY: me | the user | a hook | a control run
EVIDENCE:  path to the raw artefact, kept not deleted
MECHANISM: the guard rule / gate / harness change that now prevents it,
           or an explicit statement that it cannot be mechanised, and why

---

## 2026-01-01T09:00Z  Example entry, written on an invented incident
CLASS:     B (silent failure). First B.
CLAIMED:   "migration applied cleanly, 0 errors"
ACTUAL:    the migration binary exited 127 (not installed). The command was
           `migrate up | tail -3 || echo FAILED`, so the `||` tested tail's exit
           code and FAILED could never print. `psql -c '\dt'` shows no new table.
CAUGHT BY: me, on the timing. 0.4 s for a migration that normally takes 30 s.
EVIDENCE:  logs/migrate-2026-01-01.log.false-pass-090012 (kept, not overwritten)
MECHANISM: bash-guard rule r_pipe_masks_exit_code (WARN), replayed over 3,400 real
           commands first: 18 hits, all genuine, 0 false. Plus the runner now
           counts created tables and exits non-zero at 0.
