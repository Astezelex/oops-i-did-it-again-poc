# Porting this to another harness

**Please fork it.** These hooks are written for Claude Code, but nothing in the idea is
specific to it. Any agent runner that can execute a check before a shell command, before a
file write, or after the assistant produces a message, can run this. If you build a version
for another framework, open an issue or a PR pointing at it and it will be linked here.

What is worth carrying across is not the regexes. It is these three things:

1. **The interception points.** Before a command runs, before a file is written, after the
   message is written. Everything else is detail.
2. **The replay step.** Measure a new rule's fire rate on real history before wiring it. A
   rule that annoys people is a rule that gets removed.
3. **The ledger loop.** Record, classify, decide whether it is mechanisable, count
   recurrences, and escalate when the third one arrives.

## The wire contract, if you keep the hook shape

Claude Code speaks this protocol. Verified against the hooks documentation on 2026-09-03;
check the current docs before relying on any detail, because this moves.

**stdin** is one JSON object. Fields used here:

| field | used by | meaning |
|---|---|---|
| `tool_name` | bash-guard, file-guard | `"Bash"`, `"Write"`, `"Edit"`, `"MultiEdit"` |
| `tool_input.command` | bash-guard | the shell command about to run |
| `tool_input.file_path` | file-guard | destination path |
| `tool_input.content` / `.new_string` | file-guard | whole file, or the replacement fragment |
| `transcript_path` | style-guard | jsonl transcript, last assistant message is read from it |
| `session_id` | style-guard | scopes the loop brake counter |
| `stop_hook_active` | style-guard | set once a Stop hook has already blocked this turn |

**stdout**, for a PreToolUse guard, is one JSON object:

```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "why"}}
```

A warning omits `permissionDecision` entirely and carries `additionalContext` instead.
Emitting `"allow"` for a warning would bypass the normal permission prompt, which makes
the guard reduce safety. That distinction is the single most important line to preserve in
any port.

**exit codes**: 0 with JSON on stdout is the normal path. Exit 2 blocks (on `PreToolUse` it
stops the tool call, on `Stop` it prevents the turn from ending and feeds stderr back to the
model). Every hook here exits 0 on any internal error, deliberately.

## If your harness has no hook system

Use `hooks/guard.py`, which is the same rules behind a plain CLI:

```bash
python3 hooks/guard.py --command 'rm -rf /srv/x && rsync -a /src/ /srv/x/'
# exit 0 = pass, 1 = warn (reason on stderr), 2 = deny
python3 hooks/guard.py --file notes.md --content-stdin < new_content.md
python3 hooks/guard.py --command "$CMD" --json      # machine-readable verdict
```

A minimal integration in any language is: shell out to that, and act on the exit code.

```python
# generic pre-exec check
import subprocess
def allowed(cmd):
    p = subprocess.run(["python3", "hooks/guard.py", "--command", cmd],
                       capture_output=True, text=True)
    if p.returncode == 2:
        return False, p.stderr        # refuse, hand the reason back to the model
    if p.returncode == 1:
        return True, p.stderr         # proceed, but put the reason in the context
    return True, ""
```

## Mapping table

| this repo | what to look for in your harness |
|---|---|
| `PreToolUse` on `Bash` | a pre-execution callback for shell/terminal tools, a tool middleware, a permission callback |
| `PreToolUse` on `Write\|Edit` | a pre-write callback, or a wrapper around the file-writing tool |
| `Stop` hook | anything that runs after the assistant message is complete and can send it back |
| `additionalContext` | whatever channel injects text into the model's context without blocking |
| `permissionDecision: deny` | the refusal path that returns a reason to the model, not an exception |
| `replay.py` reading `~/.claude/projects/*/*.jsonl` | wherever your harness stores past sessions |

If your harness has no equivalent of the Stop hook, drop `style-guard.py`. Do not simulate
it with a post-hoc reminder in the system prompt: a prose rule that the model must remember
is exactly what the audit found does not work.

## Porting checklist

- [ ] Rules fire at the moment of the action, not at session start.
- [ ] Warnings and blocks are distinct, and warnings do not grant permission.
- [ ] Every guard fails open. Malformed input, an unknown tool and an internal exception all
      let the work through. There are cases for this in `tests/test_rules.py`.
- [ ] A replay tool exists for your transcript format, and you ran it before wiring anything.
- [ ] Any hook that can block a turn ending has a loop brake. `style-guard.py` uses two: the
      harness's own flag, and a session-scoped counter that gives up after two blocks.
- [ ] The ledger is excluded from version control.
- [ ] `LESSONS.md` still applies, because it is about measurement and evidence, not about
      Claude Code.

- [ ] You MEASURED the target's wire, not read it off this file. See the next section.

## A real port: what measuring the target found

In v2 these rules were run inside a different agent framework (Hermes Agent
v0.20.6, build of 2026-09-24), through `hooks/guard.py`, WARN-only, first replayed over the
agent's own 4,437 past shell commands. Two findings that no reading of this repo predicted,
both verified in that build's code, both likely to apply to whatever you port to:

1. **Its pre-call hook drops warnings.** For `pre_tool_call`, the response parser honours
   only `block`, `modify` and `approve` (the last escalates to a human-approval prompt). A
   `{"context": ...}` reply parses to nothing. So a WARN-only port is invisible there: either
   put warnings on an event that carries context, promote chosen rules to block, or map WARN
   to "ask a human". Check your harness's parser before you believe your warnings are shown.
2. **Its remote runner had a different contract.** The agent's `fleet` wrapper defaulted to a
   60 s session and had no `-t` flag at all (the limit came only from an environment
   variable). The runner rule assumed 30 s and advised `-t`, which on that runner would have
   become part of the remote command. The agent itself read its 33 blocks as "legitimate
   work"; they were real kills at 60 s of jobs that allowed themselves 90 to 140 s. This is
   why `RUNNER`, `RUNNER_LIMIT_FLAG` and `RUNNER_DEFAULT_LIMIT` in `bash-guard.py` are
   configuration, and why a port must set them from the target's own code.

Replay on that agent's history, for scale: 94.2% pass, 5.1% warn, 0.74% deny; the noisiest
rule was `r_pipe_masks_exit_code` at 3.4%, and 15 of 21 rules never fired there.

## Language ports

The rule functions in `hooks/bash-guard.py` are pure: string in, `(level, message)` or
`None` out. That makes a port to another language mostly a translation of regexes, and the
test file is the specification. Keep the docstrings. A rule whose incident has been
forgotten is a rule that gets deleted the first time it is inconvenient.
