#!/usr/bin/env python3
"""bash-guard: PreToolUse guard for the Bash tool.

Each rule here corresponds to a failure class from the audit described in README.md.
The point is that these fire at the moment the command is typed, not at session start,
because the audit's own conclusion is that rules which are only written down do not fire.

Contract (verified against code.claude.com/docs/en/hooks, 2026-08-28):
  stdin  : JSON with .tool_name and .tool_input.command
  BLOCK  : print {"hookSpecificOutput":{"hookEventName":"PreToolUse",
                  "permissionDecision":"deny","permissionDecisionReason":...}} and exit 0
  WARN   : print {"hookSpecificOutput":{"hookEventName":"PreToolUse",
                  "additionalContext":...}} and exit 0
           NOTE: a WARN deliberately emits NO permissionDecision. Emitting "allow" would
           bypass the normal permission prompt, which would make this guard less safe,
           not more.
  PASS   : exit 0 silently.

Fail-open by design: any internal error exits 0 without blocking. A guard that breaks
the session is worse than the bugs it prevents.
"""
import json
import re
import sys

# ---------------------------------------------------------------- rules

def r_cuda_without_gpus(cmd):
    """Class F. Cost a retracted upstream bug report and two more evenings on three
    separate occasions. Without --gpus a CUDA binary dies on libcuda before it prints
    anything, so an empty --help looks like 'the flag does not exist'."""
    if not re.search(r'\bdocker\s+run\b', cmd):
        return None
    if re.search(r'--gpus\b', cmd):
        return None
    if not re.search(r'\b(llama-|cuda|nvidia|nvml|ggml|vllm)', cmd, re.I):
        return None
    return ("BLOCK", "docker run against a CUDA binary without --gpus. It will die on "
                     "libcuda.so.1 before printing anything, and an empty --help will look "
                     "like the flag does not exist. This exact trap caused a retracted "
                     "upstream bug report and cost two evenings since. Add --gpus all.")

def r_pipe_masks_exit_code(cmd):
    """Class B. This is the bug that made a benchmark smoke gate report OK while testing
    nothing: the || sees tail's exit status, never the real command's."""
    # Must be the SAME simple command: no newline, no ; separator, and the conditional
    # must follow closely. An earlier draft spanned newlines and matched any later && in a
    # multi-line block: 39 false blocks in 484 real commands (replay, 2026-08-28).
    if not re.search(r'\|\s*(tail|head)\b[^\n;|&]{0,40}(\|\||&&)', cmd):
        return None
    if 'pipefail' in cmd:
        return None
    # WARN, not BLOCK: replay showed 18 real instances, all genuine (head/tail exit 0 even
    # on empty input, so the || branch never fires), but the usual cost is a missing
    # fallback message rather than data loss. An unbypassable block on ~5% of commands
    # would be worse than the bug. BLOCK is reserved for traps that are never legitimate.
    return ("WARN", "a pipe into tail/head feeds a || or && , so the conditional tests "
                     "tail's exit code and never the real command's. This is exactly how a "
                     "broken step reports success. "
                     "Add 'set -o pipefail', or capture to a file and test separately.")

def r_stderr_discarded(cmd):
    """Class B. Hid 'No space left on device' in a nightly backup job for four days; the
    log only ever said 'pull from the source host FAILED'."""
    if not re.search(r'2>\s*/dev/null', cmd):
        return None
    m = re.search(r'\b(ssh|scp|rsync|curl|docker|pct|tar|zstd|vzdump)\b', cmd)
    if not m:
        return None
    # Only when the RESULT is consumed: captured to a file/var, or tested by a conditional.
    # A bare informational probe discarding stderr is fine and was 14% noise in replay.
    # Redirect order varies: the real case was `... > out.tar 2>/dev/null`, so look for a
    # capture ANYWHERE on the line, not only after the discard.
    captured_to_file = re.search(r'(?<![0-9])>\s*(?!/dev/null)[^\s&|;]+', cmd)
    in_substitution  = re.search(r'(\$\(|`)[^\n]*2>\s*/dev/null', cmd)
    tested           = re.search(r'2>\s*/dev/null[^\n]{0,30}(\|\||&&)\s*(echo\s+)?(FAIL|fail|exit|return|log)', cmd)
    consumed = captured_to_file or in_substitution or tested
    if not consumed:
        return None
    return ("WARN", f"stderr is being discarded on a '{m.group(1)}' command. If it fails you "
                    f"get a generic failure with no cause. That hid an ENOSPC in a backup job "
                    f"for four days. Prefer 2>\"$err\" and log the contents on failure.")

def r_measurement_silenced(cmd):
    """Class D/B. A GPU VRAM probe began `python3 gpustat.py 2>/dev/null || true`. The file
    did not exist, the discard and the `|| true` ate both the error and the exit code, the
    VRAM section printed EMPTY, and the empty section read as unremarkable. So a 5,400 MiB
    ESTIMATE survived into a recommendation the user was asked to act on. Measured truth
    was 967 MiB, off by 5.6x. An empty section where a number belongs is a failed
    measurement, not a quiet pass."""
    # Narrowed after replay: the first draft named df/du/free/ipfs and accepted a bare
    # 2>/dev/null, which fired on 83 of 2,233 real commands (3.72%) -- almost all of them
    # legitimate multi-part digests where a missing sub-probe is obvious in context. What
    # actually destroyed the signal here was '|| true' on the measurement itself: it asserts
    # the number is optional, which for a measurement is never true. That is the rule.
    m = re.search(r'\b(gpustat|nvidia-smi|nvmlDeviceGetMemoryInfo|smartctl|dumpe2fs|'
                  r'lvs|vgs|pvs|blkid)\b', cmd)
    if not m:
        return None
    if not re.search(r'\|\|\s*(true|:)\s*(;|$|\n)', cmd):
        return None
    return ("WARN", f"a measurement command ('{m.group(1)}') has its stderr discarded or its "
                    f"exit code swallowed by '|| true'. If it fails you get an EMPTY section, "
                    f"not an error, and an estimate quietly takes the number's place (a real case "
                    f"estimated 5,400 MiB where the measurement was 967). Let it fail loudly, or "
                    f"print an explicit MEASUREMENT-FAILED marker in the fallback branch.")

def r_delete_before_verify(cmd):
    """Class E. Four separate incidents: a live application file overwritten, a machine
    provisioned over its own boot disk, a backup's only off-box copy deleted before the
    space check, and a mirror script with a mass-deletion path."""
    if not re.search(r'\brm\s+-[rf]{1,2}\b', cmd):
        return None
    if not re.search(r'(&&|;)\s*(scp|rsync|cp\b|tar\s+-?x|mv\b|docker\s+cp)', cmd):
        return None
    return ("WARN", "a delete happens before the replacement is created in the same command. "
                    "Copy first, verify (md5/size/exists), then delete. Delete-before-verify "
                    "has caused four separate incidents here.")

def r_time_based_delete(cmd):
    """Class B/E. If the job stops running, time-based pruning deletes the surviving good
    copies and leaves zero. A backup script was converted away from this after a near miss."""
    if not re.search(r'\bfind\b[^\n]*-mtime\b[^\n]*-delete', cmd):
        return None
    return ("WARN", "time-based pruning (find -mtime -delete). If the producing job stops, "
                    "this still ages out the last good copies and leaves zero. Prefer "
                    "count-based: ls -t | tail -n +$((KEEP+1)).")

# ---------------------------------------------------------------- community rules
# Sourced from the widely-used Claude Code guardrail sets (block-dangerous-commands,
# protect-secrets, git-safety, config-guard). Adapted to the environment they run in:
# these sessions run as root on Linux, so "block sudo" is meaningless, and ext4 is
# case-sensitive so the APFS/NTFS case-collision guard does not apply. Re-check these
# assumptions before reusing the file: on a laptop with sudo, add the sudo rules back.

def r_catastrophic(cmd):
    """Community: block-dangerous-commands. Unrecoverable one-liners."""
    pats = [
        (r'\brm\s+(-[a-zA-Z]*\s+)*-?[rRfF]{2}\s+(/|/\*|~|\$HOME)\s*($|;|&)', "rm -rf on / or ~"),
        (r':\(\)\s*\{.*\|.*&.*\}\s*;', "fork bomb"),
        (r'\bdd\b[^\n]*\bof=/dev/(sd|nvme|vd|hd)', "dd writing to a raw disk device"),
        (r'\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b', "piping a downloaded script straight into a shell"),
        (r'\bmkfs(\.\w+)?\s+/dev/', "mkfs on a device"),
        (r'>\s*/dev/(sd|nvme|vd)[a-z]', "redirect over a raw disk device"),
        (r'\bchmod\s+(-[a-zA-Z]+\s+)*777\s+/(\s|$)', "chmod 777 on /"),
    ]
    for rx, why in pats:
        if re.search(rx, cmd):
            return ("BLOCK", f"catastrophic command ({why}). Community guardrail: this class is "
                             f"unrecoverable and is never worth the risk. If genuinely intended, "
                             f"do it by hand outside the agent.")
    return None

def r_secret_exposure(cmd):
    """Community: protect-secrets. A cloud API token had to be rotated twice here after
    being echoed onto a command line. Pattern that IS allowed: TOKEN=$(cat ~/.mytoken)."""
    # a literal secret on the command line
    if re.search(r'\b(export\s+\w*(KEY|TOKEN|SECRET|PASSWORD)\w*\s*=\s*[\'"]?[A-Za-z0-9_\-]{16,})', cmd, re.I):
        return ("BLOCK", "a literal secret on the command line. It lands in shell history, the "
                         "transcript and process listings. Use the house pattern instead: "
                         "TOKEN=$(cat ~/.mytoken) with the file chmod 600.")
    if re.search(r'\bsshpass\s+-p\s*\S', cmd):
        return ("BLOCK", "sshpass -p puts the password in the process list where any user can "
                         "read it. Use a key, or the house chmod-600 file pattern.")
    # exfiltration: secret piped to the network
    if re.search(r'(\.env|id_rsa|id_ed25519|\.pem|token)[^\n]{0,40}\|\s*(curl|wget|nc)\b', cmd, re.I):
        return ("BLOCK", "a credential is being piped to the network. Refusing.")

    # printing a credential file to stdout, i.e. into the transcript
    # NOTE: `echo` is deliberately NOT in this list. `echo "checking /path/.env"` is a
    # heading, not a leak; including it produced false blocks on real commands (replay,
    # 2026-08-28). Only verbs that actually read a file's contents belong here.
    # `id_<name>` with a \b and a negative lookahead, so a PUBLIC key does not match.
    # Replay caught this: `head -1 ~/.ssh/id_ed25519.pub` is ordinary work and the strict
    # token denied it. The \b matters: without it the \w+ backtracks to a shorter name and
    # the lookahead never sees ".pub".
    # v2: `[^\n|;&]`, not `[^\n|]`. Replay 2026-10-01: `head -3 app.log; grep -c KEY .env`
    # and `tail -5 run.log; shred -u ~/.probe_pass` were denied as prints of a secret. The
    # reading verb belonged to a different command than the credential path.
    if re.search(r'\b(cat|less|more|head|tail)\b[^\n|;&]*(\.env\b|/\.ssh/id_\w+\b(?!\.pub)|\.pem\b|\.\w*token\b|/\.\w*(pass|passwd|password|secret|secret_key|_key)\b|credentials\.json|\.aws/credentials|kubeconfig)', cmd):
        # The capture pattern is explicitly allowed: TOKEN=$(cat ~/.mytoken).
        # A command substitution captures into a variable; it never reaches the transcript.
        # Only a bare print of the file is a leak.
        # Any command substitution that ends up reading the file counts as a capture, not
        # a leak: the value lands in a variable, never in the transcript. The wrapper in
        # between varies (ssh, a remote-exec helper, sudo), so do not require `cat` to sit
        # immediately after the opening paren. Replay caught that: 2 legitimate
        # `T=$(remote-exec -- cat ...token)` commands were denied by the strict form.
        captured = re.search(r'(\$\(|`)[^)`]*\b(cat|head|tail)\b[^)`]*'
                             r'(\.env|/\.ssh/id_\w+\b(?!\.pub)|\.pem|\.\w*token\b|/\.\w*(pass|passwd|password|secret|secret_key|_key)\b|credentials\.json|'
                             r'\.aws/credentials|kubeconfig)', cmd)
        # \b on BOTH sides of every verb. Without the leading boundary, `ls\b` matches the
        # tail of "credentiaLS", so `cat ~/.aws/credentials` silently passed this rule.
        # Found by the true-positive suite in tests/, not by the replay: a replay can only
        # show what a rule DOES fire on, never what it should have.
        # A PIPE IS A CAPTURE TOO, not a leak. Feeding a secret to another
        # process's stdin puts nothing in the transcript, exactly like $(...).
        # Replay over 9680 real commands: without this exemption the rule denied
        # 6 ordinary `cat ~/.svc_token | remote-exec ...` calls and caught no leak.
        # Safe because sending to the network is rejected above, by the
        # exfiltration rule, which now deliberately runs FIRST.
        if not captured:
            captured = re.search(r'\b(cat|head|tail)\b[^\n]*'
                                 r'(\.env|/\.ssh/id_\w+\b(?!\.pub)|\.pem|\.\w*token\b|/\.\w*(pass|passwd|password|secret|secret_key|_key)\b|credentials\.json|\.aws/credentials|kubeconfig)'
                                 r'[^\n]*\|', cmd)
        if not captured and not re.search(r'(\bmd5sum\b|\bsha\d+sum\b|\bwc\b|\bstat\b|\bls\b|grep -c)', cmd):
            return ("BLOCK", "this prints a credential file into the transcript. Check that it "
                             "EXISTS or its length instead, never its contents.")
    return None

def r_git_safety(cmd):
    """Community: git-safety. Matches the house rule 'if on the default branch, branch first'."""
    if re.search(r'\bgit\s+push\b[^\n]*(--force\b|-f\b)(?![a-zA-Z])', cmd) and \
       not re.search(r'--force-with-lease', cmd):
        return ("BLOCK", "git push --force can destroy remote history. Use --force-with-lease, "
                         "which refuses when the remote moved under you.")
    if re.search(r'\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f|checkout\s+\.)', cmd):
        return ("WARN", "this git command discards uncommitted work irreversibly. Confirm there "
                        "is nothing unsaved first.")
    if re.search(r'\bgh\s+repo\s+delete\b', cmd):
        return ("BLOCK", "gh repo delete is irreversible.")
    return None

def r_config_guard(cmd):
    """Community: config-guard. An agent must not be able to quietly disable its own
    guardrails. WARN not BLOCK, because legitimately editing settings is part of the work,
    but it should never happen without being visible."""
    # v2, replay 2026-10-01: all 26 sampled hits of the first version were READS
    # (`sed -n 1,40p .../bash-guard.py`), because any `sed` counted as a write and the verb
    # could sit in a different command from the path. Worse, it MISSED the plain overwrite
    # `echo '{}' > ~/.claude/settings.json`: `>\b` needs a word character after the `>`.
    # Now: a real write verb (sed -i, perl -i, tee, rm, python) and the path inside ONE
    # simple command, or a redirect whose target IS a guard file.
    if re.search(r'(\bsed\b[^\n;&|]*\s-i|\bperl\b[^\n;&|]*\s-\w*i|\btee\b|\brm\b|\bpython3?\b)[^\n;&|]*'
                 r'(\.claude/settings|\.claude/hooks|bash-guard|file-guard)'
                 r'|>>?\s*\S*(\.claude/settings|\.claude/hooks/|bash-guard|file-guard)', cmd):
        if not re.search(r'\b(cat|grep|ls|stat|md5sum|sha\d+sum|diff|cp\b|py_compile|json\.load)', cmd):
            return ("WARN", "this modifies the guardrail configuration itself (settings.json or "
                            "the hooks). That is legitimate work, but it must be visible and "
                            "backed up first, never a silent self-disable.")
    return None

def r_package_install(cmd):
    """Community: security-aware dependency changes (slopsquatting / supply chain)."""
    m = re.search(r'\b(pip3?\s+install|npm\s+i(nstall)?|yarn\s+add|pnpm\s+add|cargo\s+install)\b', cmd)
    if not m or re.search(r'--dry-run|--help', cmd):
        return None
    return ("WARN", f"installing a package ('{m.group(1)}') into a live environment. Check the "
                    f"name against typosquats, and prefer a venv over a prod interpreter.")

def r_arbitrary_row_from_listing(cmd):
    """Class C, eleventh occurrence. Reported a workstation as a console-only box because
    `loginctl show-session $(loginctl list-sessions --no-legend | awk "NR==1{print $1}")`
    picked ROOT's tty session out of three and I read its Type=tty as the machine's state.
    The human's session, two rows down, was Type=wayland with a desktop live on it.

    The identical rule already existed in prose in the ledger ("select test subjects by
    IDENTITY, never by first element matching a shape") and did not fire, because prose does
    not fire. Hence this.

    An ORDERED listing reduced to one row is a deliberate pick (newest file, largest dir), so
    a sort flag or an explicit sort in the pipeline passes silently."""
    sub = re.search(r'\$\((.*?)\)', cmd, re.S)
    if not sub:
        return None
    inner = sub.group(1)
    listing = re.search(r'\b(list-\w+|list\b|ls\b|ps\b|find\b|dpkg|pgrep|docker\s+ps)', inner)
    if not listing:
        return None
    reducer = re.search(r'\|\s*(head\s+-n?\s?1\b|tail\s+-n?\s?1\b|'
                        r'awk\s+[\'"]?\s*NR==1|sed\s+-n\s+[\'"]?1p)', inner)
    if not reducer:
        return None
    # An explicit ordering makes "the first row" a real answer, not an arbitrary one.
    if re.search(r'(\bsort\b|--sort|\bls\s+-[a-zA-Z]*[tS]|\bfind\b.*-newer|-printf.*%T)', inner):
        return None
    return ("WARN", "this reduces an UNORDERED listing to one row (head -1 / tail -1 / NR==1) "
                    "and then acts on it. The first row is whichever the tool happened to "
                    "print, not the subject you mean. In the real case it picked root's tty "
                    "session out of three and made a live desktop look like a console. "
                    "Select by identity (grep the user/name/id you actually want), or sort "
                    "explicitly so 'first' means something.")

def r_guessed_unit_candidates(cmd):
    """Class C, same incident, second half. `systemctl is-active gdm gdm3 sddm lightdm`
    returned four 'inactive' and I read it as 'no display manager is running'. It only ever
    answered a question about those four. The real one, cosmic-greeter, was in the dpkg
    output of the same command block and went untested.

    Two units is normally checking things you own. Three or more reads as guessing a
    candidate list, where a negative proves nothing about what is actually installed."""
    m = re.search(r'\bsystemctl\s+(?:--\w+\s+)*is-(?:active|enabled|failed)\s+([^\n;|&]+)', cmd)
    if not m:
        return None
    units = [u for u in m.group(1).split() if not u.startswith('-')]
    if len(units) < 3:
        return None
    return ("WARN", f"`systemctl is-active` over {len(units)} guessed unit names. A negative "
                    f"here only covers the units you named, it does not mean nothing is "
                    f"running. In the real case four 'inactive' results for gdm/gdm3/sddm/lightdm "
                    f"were read as 'no display manager', while cosmic-greeter was active. "
                    f"Enumerate instead: systemctl list-units --type=service --state=running.")

def r_empty_grep_as_absence(cmd):
    """Class C, 12th occurrence. The command was
        journalctl -u myapp --since -3h | grep -cE "GET|POST"
    got 0, and concluded "no POST reached the server", which ruled out a server-side
    rejection and sent the whole diagnosis the wrong way. The service (waitress) does not
    log requests AT ALL. The zero proved the log has no such lines, never that the event
    did not happen. The user had been using the app throughout.

    A counting grep over a log, used to establish that something did NOT occur, is only
    valid once you have shown that this log carries that kind of line at all. Absence of
    evidence needs the positive control first."""
    if not re.search(r'\b(journalctl|docker\s+logs|kubectl\s+logs|'
                     r'(?:tail|cat|less|zcat)\b[^|;]*(?:\.log\b|/var/log/))',
                     cmd):
        return None
    if not re.search(r'\|\s*grep\b[^|;]*\s-\w*c', cmd):
        return None
    return ("WARN", "a counting grep over a log. If you are about to read a 0 as proof that "
                    "something did NOT happen, that only holds once you have shown this log "
                    "contains lines of that kind at all. In the real case `journalctl | grep -cE "
                    "'GET|POST'` returned 0 because the service logs no requests whatsoever, "
                    "and that zero was misread as 'the request never arrived'. Run the "
                    "positive control first: grep for a line you KNOW is there.")

# ---------------------------------------------------------------- v2 rules (ledger 2026-09)
# Seven rules added after v1, each from a logged incident between 2026-09-04 and 2026-09-30.
# Every one was replayed against real history before it was wired, and two were narrowed
# by that replay (see the comments inside r_runner_timeout_shorter).

def local_tz():
    """This box's cron timezone, read live. Cron schedules in the system zone."""
    import os, time
    try:
        z = os.path.realpath("/etc/localtime").split("zoneinfo/")[-1]
    except OSError:
        z = "?"
    return f"{z} ({time.strftime('%Z %z')})"


CRON_WRITE = re.compile(
    r'(>>?\s*\S*/etc/cron\.d/|\b(cp|install|mv|tee|rsync)\b[^\n;|&]*\s\S*/etc/cron\.d/|'
    r'\bcrontab\s+(-e|-\s|\S+\.\w+)|>>?\s*/etc/crontab\b|'
    r'\b(scp|rsync)\b[^\n;|&]*:\S*/etc/cron\.d/)')


def r_cron_timezone(cmd):
    """Class A. Two cron jobs were written for 10:00 because a project note said "system
    clocks are UTC". The host ran Europe/Warsaw, so they fired two hours early, an hour gate
    inside the script skipped them, and the morning report would never have been sent.
    Cron fires in the zone of the host it is INSTALLED on. The zone is printed live."""
    if not CRON_WRITE.search(cmd):
        return None
    remote = re.search(r'\b(scp|rsync)\b[^\n;|&]*:\S*/etc/cron', cmd)
    where = ("the TARGET host: probe it first (`ssh <host> timedatectl`)"
             if remote else f"this box = {local_tz()}")
    return ("WARN", f"a cron schedule is being installed. Cron fires in the host's system "
                    f"timezone; {where}. Re-derive every hour field, and every comment that "
                    f"says UTC or local, against that zone.")


_HA_SECRET_STORE = re.compile(
    r'\.storage/(core\.config_entries|auth\b|auth_provider\.\w+|mobile_app\w*|http\.auth|onboarding)'
    r'|/(config|ha/config)/secrets\.yaml\b')
_HA_COUNT_ONLY = re.compile(r'(\bgrep -c\b|\buniq -c\b|\bwc\b|\bstat\b|\bls\b|\bsha\d+sum\b|\bmd5sum\b)')


def r_ha_storage_dump(cmd):
    """Class L (secret exposure while inspecting a store). Printing Home Assistant's config
    entries "minus latitude and longitude" dumped a companion app's push token, secret and
    webhook id into the transcript. The filter was a BLOCKLIST: drop two keys, print the
    rest. HA's .storage holds live credentials. WARN, not BLOCK: reading one whitelisted
    field, or counting domains, is ordinary work."""
    if not _HA_SECRET_STORE.search(cmd):
        return None
    if _HA_COUNT_ONLY.search(cmd) and not re.search(r'\b(print|cat|json\.dump|grep -[A-Z]?[AB]\d*|sed -n)\b', cmd):
        return None
    return ("WARN", "this reads a Home Assistant store that holds live credentials (mobile_app "
                    "push tokens and webhook ids, auth tokens, integration passwords). Print a "
                    "WHITELIST of the keys you need, never 'everything except X'.")


def r_push_over_state_file(cmd):
    """Class E, third occurrence. A push of a node registry replaced the target's copy
    wholesale. The target copy carried `"paused": true` for one node, set there and never
    in the source. The node un-paused, the monitor paged it as DOWN, and a critical SMS went
    out. A push over a config or state file overwrites state you have not read."""
    m = re.search(r'\b(pct\s+push\s+\d+|scp\b[^|;]*?|rsync\b[^|;]*?|docker\s+cp|kubectl\s+cp)'
                  r'\s+\S+\s+(?P<dst>[^\s;|&]+\.(json|db|sqlite3?|ya?ml|conf|toml|ini))\b', cmd)
    if not m:
        return None
    # pulling, diffing or backing up the target in the same command is the right shape
    if re.search(r'\bdiff\b|pct\s+pull|\.bak-|cp\s+-a', cmd):
        return None
    # A push to a staging name overwrites nothing live. Replay 2026-10-01: most hits of the
    # first version were exactly this (`/tmp/cfg-new.yaml`, `configuration.new.yaml`).
    if re.search(r'(^|:)/tmp/|[.\-_](new|staging|candidate|tmp)\.\w+$', m.group('dst')):
        return None
    return ("WARN", f"pushing over `{m.group('dst')}`: a state file on the target can carry keys "
                    "the source does not. Pull it and diff first, merge the target-only keys, "
                    "or back it up in the same command.")


def r_restore_from_memory(cmd):
    """Class A. "Restoring a task to its original shape" ran an UPDATE with a value typed
    from memory. The task had never had that shape, and a backup taken 50 minutes earlier
    sat in the same directory. A restore is a claim about a PAST value, so it needs a probe
    of that value, and the probe is the backup that already exists."""
    if not re.search(r'\bsqlite3\b[^\n;&|]*\bUPDATE\b[^\n]*\bSET\b', cmd, re.I):
        return None
    if not re.search(r'\.bak\b|\.bak-|\.backup\b|\.orig\b', cmd):
        return None
    # reading the backup in the same command is exactly the right shape
    if re.search(r'\.(bak|backup|orig)[^\s"\']*["\']?\s*["\']?\s*select\b', cmd, re.I):
        return None
    return ("WARN", "UPDATE against a database that keeps backup copies. If this is a restore, "
                    "the old value is a FACT to be read, not typed: select it from the newest "
                    "backup first, then write what it says.")


def r_server_identity_unverified(cmd):
    """Class B. A benchmark script lost the `docker rm -f` teardown its predecessor had. The
    smoke container kept holding the port under `--network host`, every later container
    failed to bind and was erased by `--rm`, and the health probe was answered by the STALE
    server. One arm scored 95 of 119 cases against the wrong model, under the right label.
    An open port proves that SOMETHING answers there, never that it is yours."""
    if not re.search(r'\bdocker\s+run\b', cmd):
        return None
    if not re.search(r'--network\s+host|-p\s+\d+:\d+|--publish\s+\d+:\d+', cmd):
        return None
    if re.search(r'docker\s+(rm|stop)\b', cmd):
        return None
    return ("WARN", "docker run binds a fixed port or --network host with no teardown of the "
                    "previous container in the same command. If a stale server holds the port, "
                    "your container exits, --rm erases it, and your health probe gets a 200 "
                    "from the OLD process. Tear down first, verify YOUR container is running, "
                    "then confirm identity from the server itself (/props, /v1/models).")


_SERVER_START = re.compile(r'\bnohup\b|\bwaitress\b|\bgunicorn\b|\buvicorn\b'
                           r'|\bflask\s+run\b|python3?\s+(-u\s+)?\S*app\.py|http\.server')
_FIXED_PORT = re.compile(r'\b\w*PORT\s*=\s*\d{4,5}|--port[= ]\d{4,5}')
_PORT_CHECKED = re.compile(r'\bpkill\b|\bkill\b|/proc/net/tcp|\bss\s+-[a-z]*l|lsof -i'
                           r'|\bfuser\b|systemctl\s+(stop|restart)|Address already in use'
                           r'|EADDRINUSE')


def r_port_start_unchecked(cmd):
    """Class B, same mechanism as r_server_identity_unverified, one size larger. That rule
    covered `docker run` only; six days later the same trap arrived without docker. A probe
    started `nohup python3 -u app.py` on a fixed port, an orphan from the night before held
    it (over IPv6), the new process died on EADDRINUSE, and /health answered 200 from the
    orphan, which had a different database. The probe reported two red rows against code
    that was correct. A mechanism can exist and still be one size too small."""
    if not _SERVER_START.search(cmd) or not _FIXED_PORT.search(cmd):
        return None
    if _PORT_CHECKED.search(cmd):
        return None
    return ("WARN", "this starts a server on a FIXED port with no teardown and no port check in "
                    "the same command. If something already holds the port, your process dies on "
                    "EADDRINUSE and every probe afterwards is answered by the stranger. Check the "
                    "port first (/proc/net/tcp AND /proc/net/tcp6), then verify YOUR pid is alive.")


# A remote-exec wrapper that kills its own session after a fixed time. `fleet run` is the
# wrapper this rule was written for; replace these three values with your own wrapper's.
RUNNER = re.compile(r"""(?P<pre>\btimeout\s+(?:-\S+\s+)*(?P<outer>\d+)s?\s+)?"""
                    r"""\bfleet\s+run\s+(?P<args>[^'"\n]*)(?P<rest>[^\n]*)""")
RUNNER_LIMIT_FLAG = re.compile(r'(?:^|\s)-t\s+(\d+)')
RUNNER_DEFAULT_LIMIT = 30

_INNER_TIMEOUT = re.compile(r'\btimeout\s+(?:-\S+\s+)*(\d+)s?\b')
_LONG_REMOTE = re.compile(r'bash\s+\S+\.sh|\bnode\s+\S+\.js|python3?\s+\S+\.py|\bpytest\b'
                          r'|\bdocker\s+(run|build|pull)|\bmake\b|llama-bench')
_DETACHED = re.compile(r'\b(nohup|setsid|disown)\b|&\s*[\'"]?\s*(;|$)')


def _remote_arg(rest):
    """The first shell word after the runner and its options: the remote command itself.
    Replay 2026-10-01: reading timeouts to the END OF THE LINE made 82 of 124 BLOCKs false,
    e.g. `until timeout 15 fleet run a '...'; do sleep 5; done; timeout 20 fleet run b '...'`
    read the second command's numbers as the first one's. Unparseable quoting falls back to
    the old reading, so a parse failure errs toward a warning, never toward silence."""
    import shlex
    try:
        lex = shlex.shlex(rest.lstrip(), posix=True, punctuation_chars=';&|')
        lex.whitespace_split = True
        tok = lex.get_token()
        return tok if tok else rest
    except ValueError:
        return rest


def r_runner_timeout_shorter(cmd):
    """Class F + I. A remote-exec wrapper had ITS OWN session timeout (30 s by default).
    Wrapping it in `timeout 420 <wrapper> ...`, or putting `timeout 240 bash test.sh` inside
    it, extended nothing: the wrapper closed the session at 30 s and returned 124, while the
    remote job KEPT RUNNING unsupervised. Three "hangs" were misdiagnosed that day, while the
    tests went on writing test rows into a live database. A remote job allowed to outlive
    its session is never what anyone wants: BLOCK. Detached jobs return at once: exempt."""
    for m in RUNNER.finditer(cmd):
        args, remote = m.group('args'), _remote_arg(m.group('rest'))
        t = RUNNER_LIMIT_FLAG.search(args)
        limit = int(t.group(1)) if t else RUNNER_DEFAULT_LIMIT
        if _DETACHED.search(remote):
            continue
        # Replay 2026-09-11: counting the OUTER `timeout N <wrapper>` as the job's need
        # blocked 39.5% of real commands; an outer timeout is usually a generous ceiling on
        # a short command. Only a timeout INSIDE the remote command says what the job needs.
        need = [int(x) for x in _INNER_TIMEOUT.findall(remote)]
        if need and max(need) > limit:
            return ("BLOCK", f"the runner closes its session after {limit}s, but the remote "
                             f"command allows itself {max(need)}s. The job would keep running "
                             "unsupervised and you would read exit 124 as a hang. Raise the "
                             "runner's own limit, or detach the job (nohup ... > log 2>&1 &) "
                             "and read the log.")
        # WARN only when the remote side runs something that can be long. Without this
        # narrowing the warning fired on 25.6% of commands and would have meant nothing.
        if (not t and m.group('outer') and int(m.group('outer')) > limit
                and _LONG_REMOTE.search(remote)):
            return ("WARN", f"the outer `timeout {m.group('outer')}` does not extend the runner: "
                            f"it closes the session after {limit}s on its own. If this job can "
                            "take longer, raise the runner's own limit.")
    return None


RULES = (r_cuda_without_gpus, r_pipe_masks_exit_code, r_stderr_discarded,
         r_measurement_silenced,
         r_delete_before_verify, r_time_based_delete,
         r_catastrophic, r_secret_exposure, r_git_safety, r_config_guard, r_package_install,
         r_arbitrary_row_from_listing, r_guessed_unit_candidates,
         r_empty_grep_as_absence,
         # v2
         r_cron_timezone, r_ha_storage_dump, r_push_over_state_file, r_restore_from_memory,
         r_server_identity_unverified, r_port_start_unchecked, r_runner_timeout_shorter)


# ---------------------------------------------------------------- input shaping

# A heredoc written INTO A FILE is content, not commands. Measured 2026-09-03:
# `cat > handoff.md <<'MD' ... MD` whose text quoted `systemctl is-active a b c`
# fired the guessed-units rule, as though the command had been run. Documentation
# that quotes a command is not that command. This polluted both the live warnings
# and the measurement, and it does so on BOTH sides of any before/after chart.
#
# ⛔ Only heredocs redirected to a FILE are stripped. The body of `bash <<EOF`,
# `ssh host <<EOF` or `python3 - <<PY` really does execute, so it stays in scope;
# stripping those would let anything hide inside a heredoc.
# Commands whose heredoc body is TEXT, not commands. Found by using the guard: it
# warned on its own commit message, because `git commit -F - <<'EOF'` carries prose.
# ⛔ Options may sit between `git` and the subcommand: the real call is
# `git -c user.name=... commit -q -F -`. The first version required them adjacent
# and warned on the very commit that shipped it. Twice.
# ⛔ Named explicitly and kept short. Everything absent from this list stays in scope,
# because `bash <<EOF`, `ssh host <<EOF` and `python3 - <<PY` do execute their bodies.
#
# ⚖ v2 measured the cost of that choice, and left it as a switch. A program fed to an
# interpreter on stdin (`python3 - <<'PY'`) is source in ANOTHER language, and shell-shape
# rules match its string literals. Replay over 8,516 real commands, 2026-10-01: treating
# those bodies as content removed 36 hits; every BLOCK among them was a Python program
# whose source quoted a dangerous command as data (mostly programs editing this guard).
# The price is the one named above: a real `os.system(...)` inside such a body would no
# longer be seen. Default False keeps v1's behaviour. Set True if your history looks
# like that replay, and measure it first with hooks/replay.py.
STRIP_INTERPRETER_HEREDOCS = False
_INTERPRETER = r'|(python3?|node|perl|ruby)\s+-(?=[\s<])' if STRIP_INTERPRETER_HEREDOCS else ''
HEREDOC_AS_DATA = re.compile(
    r'\b(git\b[^\n]*?\b(commit|tag|notes)\b[^\n]*-F\s*-|tee\b|mail\b|sendmail\b' + _INTERPRETER + r')'
    r'[^\n]*<<-?\s*[\'"]?([A-Za-z_][A-Za-z0-9_]*)[\'"]?[^\n]*\n')

HEREDOC_TO_FILE = re.compile(
    r'>\s*[^\s<>|;&]+[^\n]*<<-?\s*[\'"]?([A-Za-z_][A-Za-z0-9_]*)[\'"]?[^\n]*\n')


def strip_written_heredocs(cmd):
    """Remove heredoc bodies that are content: written to a file, or fed to a
    command that consumes text as data (git commit -F -, tee, mail)."""
    out, pos = [], 0
    while True:
        m_plik = HEREDOC_TO_FILE.search(cmd, pos)
        m_dane = HEREDOC_AS_DATA.search(cmd, pos)
        kandydaci = [x for x in (m_plik, m_dane) if x]
        if not kandydaci:
            out.append(cmd[pos:])
            break
        m = min(kandydaci, key=lambda x: x.start())
        out.append(cmd[pos:m.end()])
        znacznik = m.group(m.lastindex)
        koniec = re.search(r'^\s*%s\s*$' % re.escape(znacznik),
                           cmd[m.end():], re.M)
        if not koniec:
            # unterminated: leave the rest in scope. v1 said this and did the opposite: the
            # `break` dropped everything after the opener, so `cat > f <<EOF` followed by an
            # `rm -rf /` and no terminator was never scored. Found by a v2 control case.
            out.append(cmd[m.end():])
            break
        pos = m.end() + koniec.end()
    return ''.join(out)


# ---------------------------------------------------------------- driver

def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0                      # unreadable input: never block
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return 0

    # Content written into a file is not a command. See strip_written_heredocs.
    cmd = strip_written_heredocs(cmd)

    blocks, warns = [], []
    for rule in RULES:
        try:
            hit = rule(cmd)
        except Exception:
            continue                  # a broken rule must not break the session
        if not hit:
            continue
        (blocks if hit[0] == "BLOCK" else warns).append(hit[1])

    if blocks:
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "bash-guard: " + " | ".join(blocks)}})
        return 0
    if warns:
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "bash-guard warning: " + " | ".join(warns)}})
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)                   # fail open, always
