#!/usr/bin/env python3
"""file-guard: PreToolUse guard for Write and Edit.

Three jobs:
  1. ShellCheck any shell script before it is written. This is the community-standard
     linter, and it detects the exact bug class that made a test gate lie here:
     SC2312 (check-extra-masked-returns), where a pipeline hides a command's exit code.
     That check is OPTIONAL upstream and must be enabled by name.
  2. Refuse to write a literal credential into a file.
  3. Flag edits to the guardrail config itself, so the agent cannot silently disable it
     (community pattern: config-guard).
  v2 (ledger 2026-09), all WARN:
  4. BANNED-WORD: a word from your own ~/.claude/oops-banned-words.json in human-facing text.
  5. PROBE: a probe script that can measure a stranger, or exit 0 after skipping its summary.
  6. OWNER: a write to a file owned by another user, before that service is restarted.
  7. CRON-TZ: cron lines written without re-deriving the host's timezone.

Severity:
  BLOCK  shell SYNTAX errors, and literal secrets. Both are unambiguous.
  WARN   shellcheck warnings/info, and guardrail-config edits. ShellCheck has known
         false positives around pipefail scoping (koalaman/shellcheck issues #2368,
         #2582, #3025), so its style findings must not be a hard block.

Fails open on any internal error.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

SHELL_EXT = (".sh", ".bash", ".zsh", ".ksh")
SHEBANG = re.compile(r'^#!.*\b(bash|sh|zsh|ksh)\b')

SECRETS = [
    (re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}'),                 "OpenAI-style API key"),
    (re.compile(r'\bsk-or-v1-[A-Za-z0-9]{16,}'),              "OpenRouter API key"),
    (re.compile(r'\bghp_[A-Za-z0-9]{30,}'),                   "GitHub personal access token"),
    (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{30,}'),           "GitHub fine-grained token"),
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'),                     "AWS access key id"),
    (re.compile(r'\bhf_[A-Za-z0-9]{30,}'),                    "HuggingFace token"),
    (re.compile(r'\btskey-(api|auth)-[A-Za-z0-9\-]{10,}'),    "Tailscale key"),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),       "private key material"),
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9\-]{10,}'),          "Slack token"),
]

CONFIG_PATHS = re.compile(r'(\.claude/settings.*\.json|\.claude/hooks/|bash-guard\.py|file-guard\.py)')

# --- VENDOR-CLAIM -------------------------------------------------------------
# Third class-A incident in the ledger: "Gmail uses the template name to fill the subject
# line" was written into a handoff AS FACT, straight out of model memory, and became a
# design decision downstream (a filter keyed on the subject). Two real sends disproved it:
# the subject was empty, then it was whatever the human typed. The prose version of this
# rule ("search the web before asserting vendor behaviour") already existed and did not
# fire. A handoff is what the NEXT session treats as fact, so the check happens at WRITE
# time.
#
# Scope is the SENTENCE, not the paragraph: a first version scanned per paragraph and so
# stayed quiet on the incident itself, because a URL sat next to the claim. A URL is an
# address, not the result of a probe.
# Adjust to wherever your durable notes live: this is what the next session will read
# back as fact.
NOTES_PATHS = re.compile(r'(-notes/.*\.md$|HANDOFF-.*\.md$|/memory/.*\.md$|reflection-notes\.md$)')

VENDOR = re.compile(
    r'\b(Gmail|Outlook|Google|Microsoft|Apple Mail|Yahoo|mailbox\.org|Proton|Tuta|Migadu|'
    r'Cloudflare|Tailscale|GitHub|OpenAI|Anthropic|HuggingFace|OpenRouter|Dovecot|'
    r'Godot|Proxmox|Excel|Windows|Android|Chrome|Firefox|Safari)\b')

VENDOR_VERB = re.compile(
    r'\b(uses|fills|strips|blocks|supports|requires|removes|converts|rewrites|allows|'
    r'limits|caps|sends|keeps|rejects|ignores|stores|renames|wraps|inlines|re-hosts|'
    r'rehosts|expires|defaults|treats|returns|accepts|forbids)\b')

VENDOR_EVIDENCE = re.compile(
    r'(VERIFIED|PROVEN|proven|INFERRED|UNVERIFIED|UNPROVEN|'
    r'\bLEAD\b|\bassumed\b|\bpresumed\b|HTTP \d{3}|\bexit \d|\brc=\d|\bmeasured\b|'
    r'\bprobed?\b|\.eml\b|\.log\b|\bgrep\b|\bcurl\b|systemctl|docker ps|'
    r'received (HTML|message|bytes)|real bytes)', re.IGNORECASE)

SENTENCE = re.compile(r'(?<=[.!?])\s+|\n')


def vendor_claims(text):
    """Sentences asserting a third-party product's behaviour with no evidence nearby.

    Evidence is looked for in a +/-1 sentence window, so a claim followed by its own
    proof stays quiet. An explicit INFERRED / assumed / presumed label also counts:
    the rule asks for the uncertainty to be VISIBLE, not for the claim to be dropped.
    """
    sents = [z.strip() for z in SENTENCE.split(text) if z.strip()]
    out = []
    for i, z in enumerate(sents):
        if len(z) < 20:
            continue
        v = VENDOR.search(z)
        if not v or not VENDOR_VERB.search(z):
            continue
        if VENDOR_EVIDENCE.search(' '.join(sents[max(0, i - 1):i + 2])):
            continue
        out.append((v.group(1), ' '.join(z.split())[:110]))
    return out


# ---------------------------------------------------------------- v2 checks (ledger 2026-09)

# BANNED WORDS. Class J: a rule stated and acknowledged, then broken by habit. A word the
# user had banned from the product came back in three new UI strings a week after the ban,
# in a session that had read the ban. A written rule did not hold; a check on the write does.
# Your list lives OUTSIDE the repo, because it is yours:
#   ~/.claude/oops-banned-words.json
#   [{"pattern": "\\bsimply\\b", "word": "simply", "why": "reads as condescending"}]
# Only human-facing text is checked: quoted strings in code, and text nodes in templates.
# WARN, not BLOCK: the same word can be a variable name, or a quote of the user's own words.
BANNED_WORDS_FILE = os.path.expanduser("~/.claude/oops-banned-words.json")
STRINGS = re.compile(r"'([^'\n]{3,200})'|\"([^\"\n]{3,200})\"|`([^`\n]{3,200})`")
MARKUP = re.compile(r'<script.*?</script>|<style.*?</style>|{#.*?#}|{%.*?%}|{{.*?}}|<[^>]+>', re.S)


def load_banned():
    try:
        with open(BANNED_WORDS_FILE, encoding="utf-8") as fh:
            return [(re.compile(b["pattern"], re.I), b.get("word", b["pattern"]), b.get("why", ""))
                    for b in json.load(fh)]
    except Exception:
        return []


def banned_words(text, path="", banned=None):
    banned = load_banned() if banned is None else banned
    if not banned:
        return []
    pieces = [m.group(1) or m.group(2) or m.group(3) or "" for m in STRINGS.finditer(text)]
    if path.endswith((".html", ".htm", ".jinja", ".j2")):
        pieces.extend(MARKUP.sub(" ", text).split("."))
    hits = []
    for piece in pieces:
        for rx, word, why in banned:
            if rx.search(piece):
                hits.append((word, " ".join(piece.split())[:90], why))
                break
    return hits


# PROBE SCRIPTS. Class B + C. A probe that starts its own instance on a fixed port measured
# an ORPHAN instance with a different database, and then exited 0 with seven red rows,
# because an early `return` in main() skipped the summary that set the exit code. A probe
# that can report green while measuring a stranger is theatre. Two checks, on files named
# like probes only: a fixed port with no port check, and summary + sys.exit inside a main()
# that can return early.
PROBE_FILE = re.compile(r'(^|/)(probe|gate|smoke|check)[_.\-]', re.I)
PROBE_FIXED_PORT = re.compile(r'(127\.0\.0\.1|localhost):\d{4,5}|\b\w*PORT\s*=\s*\d{4,5}|--port[= ]\d{4,5}')
PROBE_PORT_CHECKED = re.compile(r'/proc/net/tcp|ss -ltn|lsof -i|Address already in use|EADDRINUSE'
                                r'|netstat -ltn|pkill', re.I)
PROBE_STARTS_SERVER = re.compile(r'Popen|nohup|waitress|uvicorn|gunicorn|app\.py|--remote-debugging-port')


def probe_gaps(text, path=""):
    if not PROBE_FILE.search(path or ""):
        return []
    gaps = []
    if PROBE_FIXED_PORT.search(text) and PROBE_STARTS_SERVER.search(text) \
            and not PROBE_PORT_CHECKED.search(text):
        gaps.append("the probe starts its own instance on a FIXED port and never checks that "
                    "the port was free, so it can measure an orphan instead of your code. Check "
                    "the port before starting (/proc/net/tcp AND /proc/net/tcp6) and abort if taken.")
    if re.search(r'\bdef main\s*\(', text):
        # main()'s body ends at the first unindented line. The first version took
        # "everything up to the next def", so a correct `sys.exit(...)` placed AFTER main()
        # counted as inside it and the check punished exactly the fix it recommends.
        after = text.split("def main", 1)[-1].split("\n")[1:]
        body = []
        for line in after:
            if line.strip() and not line[:1].isspace():
                break
            body.append(line)
        body = "\n" + "\n".join(body)
        if re.search(r'\n\s{4,}return\b', body) and "sys.exit(" in body:
            gaps.append("the summary and `sys.exit` live inside a main() that has an early "
                        "`return`. A probe once exited 0 with seven red rows this way. Compute "
                        "the exit code outside main(), and count that EVERY check actually ran.")
    return gaps


def owner_warning(path):
    """Class F. An Edit tool rewrote a service's config as root; the service restarted and
    could not read its own file. A write to a file owned by another user changes who can
    read it, and a later restart is where that surfaces."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_uid == os.geteuid():
        return None
    try:
        import grp
        import pwd
        own = "%s:%s" % (pwd.getpwuid(st.st_uid).pw_name, grp.getgrgid(st.st_gid).gr_name)
    except (KeyError, ImportError):
        own = "%d:%d" % (st.st_uid, st.st_gid)
    return ("OWNER: %s is owned by %s (mode %s), not by this process. The write may leave it "
            "owned by you and unreadable to its service. Afterwards restore the owner "
            "(`chown %s %s`) and prove the service user can read it BEFORE any restart."
            % (os.path.basename(path), own, oct(st.st_mode & 0o777), own, path))


CRON_PATH = re.compile(r'(/etc/cron\.d/|crontab|(^|/)cron[.\-_][^/]*$)')
CRON_LINE = re.compile(r'^\s*[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+\S', re.M)


def cron_warning(path, text):
    """Class A. Cron jobs written for "UTC" on a host that ran Europe/Warsaw never fired
    at the intended hour. Same incident as bash-guard's r_cron_timezone, other door."""
    if not (CRON_PATH.search(path) and CRON_LINE.search(text)):
        return None
    try:
        import time
        z = os.path.realpath("/etc/localtime").split("zoneinfo/")[-1] + time.strftime(" (%Z %z)")
    except OSError:
        z = "?"
    return ("CRON-TZ: cron schedule lines in %s. Cron fires in the system timezone of the host "
            "it is INSTALLED on; this box = %s. If it goes to another host, probe that host's "
            "zone first. Re-derive every hour field, and every UTC/local comment, against it."
            % (os.path.basename(path), z))


def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def shellcheck(text):
    """Return (blocks, warns). Empty lists if shellcheck is unavailable."""
    if not text.strip():
        return [], []
    exe = None
    for cand in ("/usr/bin/shellcheck", "shellcheck"):
        if os.path.exists(cand) or cand == "shellcheck":
            exe = cand
            break
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
            fh.write(text)
            tmp = fh.name
        r = subprocess.run(
            [exe, "--format=json1", "--severity=info",
             "--enable=check-extra-masked-returns,require-variable-braces,quote-safe-variables",
             tmp],
            capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout or '{"comments":[]}')
    except Exception:
        return [], []
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    blocks, warns = [], []
    for c in data.get("comments", [])[:12]:
        line = f"SC{c.get('code')} line {c.get('line')}: {c.get('message')}"
        (blocks if c.get("level") == "error" else warns).append(line)
    return blocks, warns


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name")
    if tool not in ("Write", "Edit", "MultiEdit"):
        return 0
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    text = ti.get("content") or ti.get("new_string") or ""
    if not text:
        return 0

    blocks, warns = [], []

    for rx, what in SECRETS:
        if rx.search(text):
            blocks.append(f"a literal {what} is being written into {os.path.basename(path)}. "
                          f"Secrets belong in a chmod-600 file read at runtime, never in a "
                          f"tracked file. A cloud API token had to be rotated twice this way.")
            break

    # ShellCheck only on a WHOLE file. On Edit/MultiEdit, `new_string` is a fragment:
    # linting it as a standalone script yields bogus SC2148/SC2168/SC1089 syntax errors
    # and BLOCKS legitimate edits. That happened here on an edit adding a function
    # body. A guard that blocks real work gets switched off, and then it guards nothing.
    is_shell = (tool == "Write"
                and (path.endswith(SHELL_EXT) or bool(SHEBANG.match(text.lstrip()[:200]))))
    if is_shell:
        sb, sw = shellcheck(text)
        if sb:
            blocks.append("shellcheck found SYNTAX ERRORS: " + " | ".join(sb[:3]))
        if sw:
            warns.append("shellcheck: " + " | ".join(sw[:5]) +
                         (f" (+{len(sw)-5} more)" if len(sw) > 5 else "") +
                         ". SC2312 in particular is the exit-code-masking class that made a "
                         "test gate lie here. Note shellcheck has known false "
                         "positives around pipefail scoping, so judge, do not obey blindly.")

    if NOTES_PATHS.search(path):
        vc = vendor_claims(text)
        if vc:
            lista = " | ".join(f"[{v}] {frag}" for v, frag in vc[:3])
            warns.append(
                f"VENDOR-CLAIM: {len(vc)} sentence(s) state how a third-party product "
                f"behaves, with no probe and no INFERRED label nearby: {lista}. "
                f"In the real case \"Gmail uses the template name to fill the subject line\" "
                f"went into a handoff as fact and became a design lever; two real sends "
                f"disproved it. Either probe it, or write INFERRED next to it.")

    # v2 checks
    bw = banned_words(text, path)
    if bw:
        shown = " | ".join('"%s"' % frag for _, frag, _ in bw[:3])
        warns.append("BANNED-WORD: %d string(s) contain \"%s\": %s. %s Check whether it is "
                     "text a person reads; a variable name or a quote of the user may stay."
                     % (len(bw), bw[0][0], shown, bw[0][2]))
    for gap in probe_gaps(text, path):
        warns.append("PROBE: " + gap)
    ow = owner_warning(path)
    if ow:
        warns.append(ow)
    cw = cron_warning(path, text)
    if cw:
        warns.append(cw)

    if CONFIG_PATHS.search(path):
        warns.append("this edits the guardrail configuration itself. Legitimate, but it must "
                     "be visible and backed up, never a silent self-disable.")

    if blocks:
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "file-guard: " + " | ".join(blocks)}})
        return 0
    if warns:
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "file-guard: " + " | ".join(warns)}})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
