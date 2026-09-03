#!/usr/bin/env python3
"""measure.py - what the guards actually changed, measured from real transcripts.

Reads every Claude Code transcript on this machine, extracts every Bash command with its
timestamp, and runs the CURRENT rule set over all of them. That gives one honest number per
day: how often the commands being written carried a shape a guard objects to.

    python3 analysis/measure.py > analysis/data.json

What this measures, precisely, so nobody over-reads the chart:

  - It is the rate of guarded SHAPES in commands actually issued, per 100 Bash commands.
  - Rules WARN more often than they block, so a drop is a change in what gets written, not
    proof that fewer things broke.
  - The rule set is applied retroactively to old commands. Old sessions were not warned;
    they are being scored by today's rules so the two periods are comparable.
  - Sessions spent building this repo type trigger strings on purpose (test cases, README
    examples). They are counted separately and excluded from the headline.

The output carries COUNTS ONLY, never command text. An earlier version of this script kept
two example commands per rule "for context". Those examples contained host names, an
internal IP address, a client project path and the name of a token file, and the file was
one commit away from a public repository. A derived artefact inherits the sensitivity of
whatever it was derived from. If you add a field here, ask what it copies out of the source.

None of that is a reason to skip the measurement. It is a reason to label it.
"""
import json
import glob
import importlib.util
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# The date the guards were first wired into settings.json.
INSTALL_DATE = "2026-08-28"

# When each rule went live. Derived from the dated backups of bash-guard.py and verified by
# reading which rule functions each backup contains, not from memory. A rule cannot have
# influenced a command written before it existed, so every per-rule comparison uses its own
# date, and the headline series uses only the ten rules that were there on day one.
RULE_BORN = {
    "r_cuda_without_gpus":          "2026-08-28",
    "r_pipe_masks_exit_code":       "2026-08-28",
    "r_stderr_discarded":           "2026-08-28",
    "r_delete_before_verify":       "2026-08-28",
    "r_time_based_delete":          "2026-08-28",
    "r_catastrophic":               "2026-08-28",
    "r_secret_exposure":            "2026-08-28",
    "r_git_safety":                 "2026-08-28",
    "r_config_guard":               "2026-08-28",
    "r_package_install":            "2026-08-28",
    "r_measurement_silenced":       "2026-08-30",
    "r_arbitrary_row_from_listing": "2026-09-02",
    "r_guessed_unit_candidates":    "2026-09-02",
    "r_empty_grep_as_absence":      "2026-09-02",
}
DAY_ONE = [r for r, d in RULE_BORN.items() if d == INSTALL_DATE]


def load_rules():
    path = os.path.join(REPO, "hooks", "bash-guard.py")
    spec = importlib.util.spec_from_file_location("bash_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RULES


def commands():
    """Yield (date, command, cwd, is_meta) for every Bash tool call on this machine."""
    files = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    for f in files:
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                content = (rec.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                ts = (rec.get("timestamp") or "")[:10]
                cwd = rec.get("cwd") or ""
                if not ts:
                    continue
                for block in content:
                    if (isinstance(block, dict) and block.get("type") == "tool_use"
                            and block.get("name") == "Bash"):
                        cmd = (block.get("input") or {}).get("command")
                        if not cmd:
                            continue
                        # Building the guards means typing trigger strings on purpose:
                        # test cases, README examples, edits to the hooks themselves.
                        # Those are not ordinary work and would flatter or spoil both
                        # periods depending on the rule, so they are counted apart.
                        meta = ("oops-repo" in cwd or "oops-repo" in cmd
                                or "oops-i-did-it-again" in cmd
                                or ".claude/hooks" in cmd
                                or "oops-ledger" in cmd)
                        yield ts, cmd, cwd, meta


def main():
    rules = load_rules()
    per_day_total = Counter()
    per_day_hits = Counter()
    per_day_meta = Counter()
    per_rule = defaultdict(Counter)          # rule -> {"before": n, "after": n}
    per_rule_days = defaultdict(Counter)     # rule -> date -> n
    period_total = Counter()

    day_totals_for_rule = defaultdict(Counter)   # rule -> {"before": n, "after": n} commands

    for date, cmd, cwd, meta in commands():
        if meta:
            per_day_meta[date] += 1
            continue
        period = "before" if date < INSTALL_DATE else "after"
        per_day_total[date] += 1
        period_total[period] += 1
        # Denominator per rule: only the commands written on the correct side of THAT
        # rule's own birth date count towards its rate.
        for name, born in RULE_BORN.items():
            day_totals_for_rule[name]["before" if date < born else "after"] += 1
        fired = False
        for rule in rules:
            try:
                got = rule(cmd)
            except Exception:
                continue
            if not got:
                continue
            name = rule.__name__
            born = RULE_BORN.get(name, INSTALL_DATE)
            per_rule[name]["before" if date < born else "after"] += 1
            per_rule_days[name][date] += 1
            if name in DAY_ONE:
                fired = True          # headline counts only the ten day-one rules
        if fired:
            per_day_hits[date] += 1

    days = sorted(per_day_total)
    out = {
        "install_date": INSTALL_DATE,
        "generated_from": "~/.claude/projects/*/*.jsonl",
        "totals": {
            "commands": sum(per_day_total.values()),
            "commands_excluded_as_meta": sum(per_day_meta.values()),
            "days": len(days),
            "first_day": days[0] if days else None,
            "last_day": days[-1] if days else None,
        },
        "period_totals": dict(period_total),
        "headline": {
            "rules_counted": sorted(DAY_ONE),
            "note": "only the ten rules that existed on the install date, so the metric "
                    "does not change shape mid-series",
            "before_commands": period_total["before"],
            "after_commands": period_total["after"],
            "before_flagged": sum(n for d, n in per_day_hits.items() if d < INSTALL_DATE),
            "after_flagged": sum(n for d, n in per_day_hits.items() if d >= INSTALL_DATE),
        },
        "daily": [
            {"date": d, "commands": per_day_total[d], "flagged_commands": per_day_hits[d],
             "rate_per_100": round(100.0 * per_day_hits[d] / per_day_total[d], 2)}
            for d in days
        ],
        "per_rule": {
            r: {
                "born": RULE_BORN.get(r),
                "before": per_rule[r]["before"],
                "after": per_rule[r]["after"],
                "before_commands": day_totals_for_rule[r]["before"],
                "after_commands": day_totals_for_rule[r]["after"],
                "before_per_100": round(
                    100.0 * per_rule[r]["before"] / day_totals_for_rule[r]["before"], 3)
                if day_totals_for_rule[r]["before"] else None,
                "after_per_100": round(
                    100.0 * per_rule[r]["after"] / day_totals_for_rule[r]["after"], 3)
                if day_totals_for_rule[r]["after"] else None,
            }
            for r in sorted(per_rule)
        },
        "per_rule_daily": {r: dict(per_rule_days[r]) for r in sorted(per_rule_days)},
    }
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")

    t = out["totals"]
    b, a = period_total["before"], period_total["after"]
    fb = out["headline"]["before_flagged"]
    fa = out["headline"]["after_flagged"]
    sys.stderr.write(
        "commands=%d (excluded as meta: %d) over %d days, %s..%s\n"
        "before %s: %d commands, %d flagged (%.2f per 100)\n"
        "after  %s: %d commands, %d flagged (%.2f per 100)\n"
        % (t["commands"], t["commands_excluded_as_meta"], t["days"], t["first_day"],
           t["last_day"],
           INSTALL_DATE, b, fb, 100.0 * fb / b if b else 0,
           INSTALL_DATE, a, fa, 100.0 * fa / a if a else 0))


if __name__ == "__main__":
    main()
