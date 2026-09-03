#!/usr/bin/env python3
"""True-positive AND true-negative tests for the guards.

Run:  python3 tests/test_rules.py

Two halves, and both matter:

  TRIGGERS  each rule fires on the command that caused its incident. A rule nobody has
            seen fire is a rule you are guessing about.
  QUIET     ordinary work passes. This half is the one that keeps the guard installed.
            `replay.py` covers the same ground at scale against real history; this file
            covers the cases you can state in advance.

A replay can only show what a rule DOES fire on. It can never show what it SHOULD have
fired on and did not. That gap is what this file exists for: the `cat ~/.aws/credentials`
case below passed silently for weeks because `ls\\b` matched the tail of "credentiaLS",
and only an expected-deny assertion could surface it.

Secret-shaped strings are assembled from fragments on purpose, so that this repo never
contains anything a scanner should flag.
"""
import json
import os
import subprocess
import sys

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
BASH = os.path.join(HOOKS, "bash-guard.py")
FILE = os.path.join(HOOKS, "file-guard.py")

J = lambda *parts: "".join(parts)


def verdict(guard, payload):
    """Return 'deny', 'WARN' or 'PASS' for one hook invocation."""
    p = subprocess.run([sys.executable, guard], input=json.dumps(payload),
                       capture_output=True, text=True)
    if not p.stdout.strip():
        return "PASS"
    hso = json.loads(p.stdout).get("hookSpecificOutput") or {}
    return hso.get("permissionDecision") or "WARN"


def bash(cmd):
    return verdict(BASH, {"tool_name": "Bash", "tool_input": {"command": cmd}})


def write(path, content):
    return verdict(FILE, {"tool_name": "Write",
                          "tool_input": {"file_path": path, "content": content}})


BASH_TRIGGERS = [
    ("cuda_without_gpus",      J("docker ", "run --rm llama-bench --help"), "deny"),
    ("pipe_masks_exit_code",   "bash test.sh | tail -5 || echo FAILED", "WARN"),
    ("stderr_discarded",       "rsync -a a b 2>/dev/null > out.log && echo ok", "WARN"),
    ("measurement_silenced",   "nvidia-smi --query-gpu=memory.used --format=csv 2>/dev/null || true", "WARN"),
    ("delete_before_verify",   "rm -rf /srv/x && rsync -a /src/ /srv/x/", "WARN"),
    ("time_based_delete",      "find /backups -mtime +7 -delete", "WARN"),
    ("catastrophic",           J("rm ", "-rf /", " "), "deny"),
    ("secret_on_cmdline",      J("export OPENAI_API", "_KEY=", "sk-", "x" * 24), "deny"),
    ("sshpass_password",       J("sshpass ", "-p hunter2 ssh host"), "deny"),
    ("credential_file_printed", J("cat ", "/root/.aws/credentials"), "deny"),
    ("private_key_printed",     J("cat ", "/home/u/.ssh/id_", "ed25519"), "deny"),
    ("git_force_push",         J("git ", "push --force origin main"), "deny"),
    ("package_install",        "pip install requests", "WARN"),
    ("arbitrary_row",          "loginctl show-session $(loginctl list-sessions --no-legend | awk 'NR==1{print $1}')", "WARN"),
    ("guessed_units",          J("systemctl ", "is-active gdm gdm3 sddm lightdm"), "WARN"),
    ("empty_grep_as_absence",  J("journalctl ", "-u myapp --since -3h | grep -cE 'GET|POST'"), "WARN"),
]

BASH_QUIET = [
    ("plain listing",          "ls -la /tmp"),
    ("plain git",              "git status"),
    ("token captured to var",  J("T=$(cat ~/.mytoken)", "; curl -H \"Authorization: Bearer $T\" https://example.com")),
    ("token via a wrapper",    J("T=$(ssh host -- cat /opt/app/.apitoken)", "; echo \"${#T}\"")),
    ("existence check only",   J("ls ", "-l /root/.aws/credentials")),
    ("checksum not contents",  J("md5sum ", "/root/.aws/credentials")),
    # A public key is not a secret. Found by replay: the strict `/\.ssh/id_` token
    # denied `head -1 ~/.ssh/id_ed25519.pub`, which is ordinary work.
    ("public key is not secret", J("head ", "-1 /home/u/.ssh/id_", "ed25519.pub")),
    ("ssh-copy-id",            J("ssh-copy-id ", "-i ~/.ssh/id_", "ed25519.pub host")),
    ("newest file is a real pick", "cat $(ls -t /var/log/*.log | head -1)"),
    ("two units you own",      J("systemctl ", "is-active nginx postgresql")),
    ("pipefail present",       "set -o pipefail; bash test.sh | tail -5 || echo FAILED"),
    ("force-with-lease",       J("git ", "push --force-with-lease origin topic")),
]

FILE_TRIGGERS = [
    ("private key into a file", "/tmp/keys.txt",
     J("-----BEGIN ", "RSA PRIVATE KEY", "-----\nMIIEow...\n"), "deny"),
    ("unproven vendor claim in a handoff", "/root/x-notes/HANDOFF-2026-01-01-a.md",
     "Gmail uses the template name to fill the subject line, so the filter keys on it.", "WARN"),
    ("guardrail config edit", "/root/.claude/hooks/bash-guard.py", "# tweak\n", "WARN"),
]

FILE_QUIET = [
    ("vendor claim WITH evidence", "/root/x-notes/HANDOFF-2026-01-01-a.md",
     "Gmail strips the class attribute. VERIFIED: the received message body has no class=."),
    ("vendor claim labelled INFERRED", "/root/x-notes/HANDOFF-2026-01-01-a.md",
     "INFERRED, not probed: Outlook requires inline styles. Prove before building on it."),
    ("ordinary prose", "/root/x-notes/HANDOFF-2026-01-01-a.md",
     "The importer now refuses to print an empty table and dumps the unparsed lines."),
    ("ordinary code file", "/root/app/util.py", "def add(a, b):\n    return a + b\n"),
]


def main():
    fails = 0
    print("TRIGGERS (a rule must fire on the incident that created it)")
    for name, cmd, want in BASH_TRIGGERS:
        got = bash(cmd)
        ok = got == want
        fails += not ok
        print("  %-4s %-24s want=%-4s got=%-4s" % ("ok" if ok else "FAIL", name, want, got))
    for name, path, content, want in FILE_TRIGGERS:
        got = write(path, content)
        ok = got == want
        fails += not ok
        print("  %-4s %-24s want=%-4s got=%-4s" % ("ok" if ok else "FAIL", name, want, got))

    print("\nQUIET (ordinary work must pass, or the guard gets uninstalled)")
    for name, cmd in BASH_QUIET:
        got = bash(cmd)
        ok = got == "PASS"
        fails += not ok
        print("  %-4s %-28s got=%s" % ("ok" if ok else "FAIL", name, got))
    for name, path, content in FILE_QUIET:
        got = write(path, content)
        ok = got == "PASS"
        fails += not ok
        print("  %-4s %-28s got=%s" % ("ok" if ok else "FAIL", name, got))

    # Fail-open. A guard that wedges the session is worse than the bugs it prevents, so
    # malformed input, an unknown tool and an empty payload must all pass silently.
    print("\nFAIL-OPEN (a broken guard must never block a session)")
    open_cases = [
        ("garbage on stdin", "not json at all"),
        ("unknown tool", json.dumps({"tool_name": "WebFetch", "tool_input": {"url": "x"}})),
        ("empty object", "{}"),
        ("null tool_input", json.dumps({"tool_name": "Bash", "tool_input": None})),
    ]
    for guard in (BASH, FILE):
        for name, payload in open_cases:
            p = subprocess.run([sys.executable, guard], input=payload,
                               capture_output=True, text=True)
            blocked = (p.returncode != 0) or ('"deny"' in p.stdout)
            fails += blocked
            print("  %-4s %-18s %-16s rc=%d" % ("FAIL" if blocked else "ok",
                                                os.path.basename(guard), name, p.returncode))

    total = (len(BASH_TRIGGERS) + len(FILE_TRIGGERS) + len(BASH_QUIET) + len(FILE_QUIET)
             + 2 * len(open_cases))
    print("\n%d cases, %d failures" % (total, fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
