# oops-i-did-it-again

A Claude Code skill and three hooks that turn an agent's mistakes into machinery instead of
into promises.

The whole thing comes out of one measurement. An audit of 73 session handoffs from a
long-running project asked a single question: which failure classes stopped recurring?

> **Failure classes that were turned into machinery stopped happening. Failure classes that
> were only written down as rules did not.**

The top rule in that project's instruction file was broken the same night it was cited, and
another within 24 hours of being written. A wrapper that removed hand-rolled ssh quoting
erased its entire error class and it never came back.

So this is not a prompt about being careful. It is the loop that runs after an error, plus
the guards that loop produced.

## What is in here

| path | what it is |
|---|---|
| `LESSONS.md` | **the part worth reading even if you install nothing.** Every generalisable lesson from 43 logged mistakes |
| `skills/oops-i-did-it-again/SKILL.md` | the skill: stop, record, classify, mechanise, count recurrences |
| `hooks/bash-guard.py` | PreToolUse guard on Bash. 14 rules, each carrying the incident that created it |
| `hooks/file-guard.py` | PreToolUse guard on Write/Edit. ShellCheck, literal secrets, unproven vendor claims in notes |
| `hooks/style-guard.py` | Stop hook. Checks the finished reply against your own writing rules, before the user reads it |
| `hooks/replay.py` | replays a guard against your real command history, so you learn its false-positive rate before wiring it |
| `hooks/guard.py` | the same rules behind a plain CLI, for harnesses that are not Claude Code |
| `install.sh` | wires it up: runs the tests first, backs up `settings.json`, idempotent, `--dry-run` and `--uninstall` |
| `tests/` | 94 cases across four suites, including fail-open and installer tests. `bash tests/run-all.sh` |
| `ledger/LEDGER-TEMPLATE.md` | the append-only error ledger, empty, with one worked example |
| `analysis/` | the impact measurement: `measure.py` scores your own transcripts, `gen_charts.py` draws them, `ledger_stats.py` counts your ledger without quoting it |
| `AGENTS.md` | install and extension instructions written for an agent doing this on someone's behalf |
| `PORTING.md` | the wire contract, a mapping table, and an invitation to fork this onto other harnesses |

## Start here

`LESSONS.md` is the distillation of a real error ledger: 43 entries, classified. The
distribution is the surprising part. The largest class by far is not a broken tool or a
hallucinated fact. It is **a working tool, a real number, and the wrong question**, 13 of
43. Silent failures are 9. Assumed tool contracts are 6.

## Did it work

`analysis/measure.py` scores every Bash command in this machine's Claude Code transcripts
against the current rule set: **9,426 commands over 28 days**, both periods scored
by the same rules. The metric is how often an issued command carried a shape a guard
objects to, per 100 commands.

**9.15 per 100 before, 4.29 after.** The daily swing narrows from 0-23 to 2-7.

![Daily rate of commands carrying a guarded shape, falling from a mean of 9.15 per 100 before the guards to 4.29 after](analysis/charts/rate-over-time.svg)

⛔ **These numbers replaced an earlier 9.97 -> 7.41, and the reason matters more than the
numbers.** A heredoc written into a file is content, not commands, but the scorer was
reading the body anyway. A handoff quoting `systemctl is-active a b c` was being counted
as though that command had been run. Stripping those bodies is the whole of the change:

| method | before | after | drop |
|---|---|---|---|
| as first published | 9.87 | 7.00 | 29.1% |
| wider meta filter only | 9.87 | 6.98 | 29.3% |
| heredoc bodies stripped only | 9.15 | 4.31 | 52.9% |
| both, as published now | 9.15 | 4.29 | 53.1% |

Two things follow, and neither flatters the result. The measured improvement roughly
doubled because of a scorer bug, not because anything got better. And the fix moves the
*after* period far more than the *before* one, which means the later period contains much
more written documentation; part of what the original chart called improvement was really
us writing more handoffs. A metric that counts prose as commands rewards writing prose.

Per rule, split on each rule's own start date, since a rule cannot have changed a command
written before it existed:

![Per-rule before and after rates. arbitrary_row_from_listing down 88, cuda_without_gpus down 85, package_install down 79, stderr_discarded down 56, catastrophic down 54, pipe_masks_exit_code down 42, empty_grep_as_absence down 26, delete_before_verify up 19, guessed_unit_candidates up 45, git_safety up 469](analysis/charts/per-rule.svg)

Reading it:

- The rule that BLOCKS is among the steepest falls: `cuda_without_gpus`, down 85%.
- 7 rules fell, 3 rose: `delete_before_verify` up 19%, `guessed_unit_candidates` up 45%, `git_safety` up 469%.
  Task mix, warning fatigue and a rule that is simply too broad all fit that data, and this
  measurement cannot tell them apart. `git_safety` moves on single figures, so its percentage
  is noise, not a finding.
- It counts command shapes, not errors avoided. Most rules warn instead of blocking.
- Six days of "after", one operator, one machine, an uncontrolled workload.
- ⛔ The scorer was wrong once already, and the correction halved the headline. Treat any
  version of this chart as provisional until someone reruns it on their own transcripts.

The better measurement, for a later version: the hook's warning text lands in the
transcript, so pairing each warning with the next command in that session would show how
often it was rewritten.

```bash
python3 analysis/measure.py > analysis/data.json      # your transcripts, your numbers
python3 analysis/gen_charts.py
```

## Install

Needs Python 3.7 or newer (it uses `subprocess.run(capture_output=...)`), bash, and Claude
Code. ShellCheck is optional and only used by `file-guard.py`. Developed on Linux; the hooks
themselves are pure Python and portable, `install.sh` and the shell tests assume a POSIX
shell.

```bash
git clone <this repo> ~/.claude/oops && cd ~/.claude/oops
bash tests/run-all.sh      # expect: ALL SUITES PASS, 94 cases, 0 failures
./install.sh --dry-run     # shows the settings.json it would write, changes nothing
./install.sh
```

`install.sh` runs the suites first and refuses to install if any fail, copies the skill,
backs up `settings.json` before merging, and writes absolute paths. Rerun it after a `git
pull`: it is idempotent. `./install.sh --uninstall` removes only what it added, and
`--project` installs into `./.claude` instead of your home directory.

To wire it by hand instead, merge `settings.example.json` yourself and replace the
placeholder with your clone's absolute path. Do not use `~` in a hook command: whether it
expands depends on whether your build runs the command through a shell, and on the
platform. `${CLAUDE_PROJECT_DIR}` is the supported placeholder for project-scoped installs.

Before you trust the guards on your own machine, run them against your own history:

```bash
python3 ~/.claude/oops/hooks/replay.py 12
```

That reads your recent Claude Code transcripts, feeds every Bash command through
`bash-guard.py`, and reports what fires and how often. **Read the block rate first.** If a
rule denies work you recognise as legitimate, the rule is wrong. Measured on the machine
these were built for, over 3,502 real commands: **8.5% warn, 0.5% block**, and every block
was either a genuine trap or a command that merely quoted a rule's own text.

## The guards

`bash-guard.py`, at the moment a command is typed:

| rule | catches |
|---|---|
| `r_pipe_masks_exit_code` | a pipe into `tail` feeding a conditional, so the conditional tests tail and never the command |
| `r_stderr_discarded` | `2>/dev/null` on ssh/rsync/docker/tar when the result is consumed |
| `r_measurement_silenced` | `\|\| true` on a measurement, which turns a failure into an empty section |
| `r_delete_before_verify` | a delete ahead of the replacement in the same command |
| `r_time_based_delete` | `find -mtime -delete`, which reaches zero once the producing job stops |
| `r_cuda_without_gpus` | `docker run` on a CUDA binary with no `--gpus`, so it dies before printing |
| `r_arbitrary_row_from_listing` | `$(list ... \| head -1)`, picking whichever row the tool printed first |
| `r_guessed_unit_candidates` | `systemctl is-active a b c d`, where a negative only covers your guesses |
| `r_empty_grep_as_absence` | a counting grep over a log, read as proof an event did not happen |
| `r_catastrophic` | recursive deletes of `/`, fork bombs, `dd` to a raw device, curl piped into a shell |
| `r_secret_exposure` | secrets on the command line, passwords passed as flags, credential files printed to the transcript |
| `r_git_safety` | force pushes without a lease, repo deletion, hard resets |
| `r_config_guard` | edits to the guardrail configuration itself |
| `r_package_install` | installs into a live environment (typosquats, no venv) |

`file-guard.py`, at the moment a file is written:

- ShellCheck on whole shell scripts, with `check-extra-masked-returns` enabled by name.
  That is SC2312, the exact class that makes a test gate lie.
- Literal secrets refused: API keys, tokens, private key material.
- **VENDOR-CLAIM**: a sentence in a note or handoff that asserts how a third-party product
  behaves, with no probe and no `INFERRED` label within one sentence, gets a warning.
  Handoffs are what the next session treats as fact. The incident behind this rule is a
  remembered claim about an email client that became a design decision and was disproved by
  the first real message.

`style-guard.py` is the odd one, and the pattern is more useful than its contents. Guards on
tool calls cannot see prose. The Stop hook is the only place that sees the finished reply,
so exit 2 there sends the message back to be rewritten before the user reads it. The two
rules shipped are one person's writing preferences: replace them with yours.

## Adding a rule

1. Write the ledger entry first, with the artefact path. Never edit a past entry.
2. Classify it. If it fits no class, add one.
3. Decide whether it is syntactically detectable at all. Classes A, C and G usually are not,
   and pretending otherwise produces rules that never fire.
4. **BLOCK only what is never legitimate. Everything else WARNs.** A guard that blocks real
   work gets uninstalled, and then it protects nothing. A WARN must emit no
   `permissionDecision` at all: emitting `allow` bypasses the normal permission prompt and
   makes the guard reduce safety.
5. Add a true-positive AND a true-negative case to `tests/test_rules.py`.
6. Replay it against real history before wiring it. A first draft of the pipe rule fired on
   8.1% of real commands, and only the replay showed that.
7. Prove it fires on the exact command that caused the incident.

Steps 5 and 6 measure different things. A replay shows what a rule does fire on; only an
expected-deny test shows what it should have fired on and did not. A command printing an AWS
credentials file passed this repo's own secret rule for weeks because `ls\b` matched the
tail of "credentiaLS", and the test caught it.

## What it does to your machine

- **No network.** No hook opens a socket or imports an HTTP client. Check with
  `grep -rE 'socket|urllib|requests|urlopen' hooks/`: the only hits are the regexes that
  match such commands in your text.
- **They read and return a verdict.** They never run the command, never touch your files.
  The only thing written is `style-guard.py`'s counter file in the temp directory.
  `file-guard.py` runs `shellcheck` on a temp copy of a shell script and deletes it.
- **They fail open.** Malformed input, unknown tool, internal exception: exit 0, work
  proceeds. Asserted in `tests/test_rules.py`.
- **The Stop hook has two brakes**, the harness's `stop_hook_active` flag and a
  session-scoped counter that stops blocking after two turns. Asserted in
  `tests/test_style_guard.py`.
- **`replay.py` stays local**, but it prints your own command history to your terminal.
  Read a report before pasting it anywhere.
- **`install.sh --dry-run`** prints the JSON it would write. Every settings write takes a
  timestamped backup first, and `--uninstall` reverses it.

## Limits

- Regexes over command strings catch shapes, not intent. A tripwire, not a sandbox, and not
  a security boundary.
- The class distribution comes from one project, one operator, one model. Treat it as a
  hypothesis about your own work.
- Several of the most expensive lessons in `LESSONS.md` are not mechanised, because nobody
  has worked out how.
- `replay.py` reads transcripts from `~/.claude/projects/*/*.jsonl`. If that path changes it
  finds nothing, so it prints the command count first.

## Fork it onto your own harness

The hooks are Claude Code shaped, the idea is not. `PORTING.md` has the wire contract, a
mapping table for the three interception points (before a command, before a write, after the
message), and `hooks/guard.py`, which exposes the same rules as a plain CLI: exit 0 pass,
1 warn, 2 deny. A port is mostly a translation of pure functions, and `tests/test_rules.py`
is the specification. If you build one, link it back.

## Your ledger is not in here

The ledger these rules came from is an operations diary of real machines, so it does not
ship. `ledger/LEDGER-TEMPLATE.md` is the empty form plus one example written on an invented
incident, and `.gitignore` already excludes `oops-ledger.md`. Keep yours out of anything you
publish.


## License

MIT. See `LICENSE`.
