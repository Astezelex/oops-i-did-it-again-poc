#!/usr/bin/env python3
"""gen_charts.py - render the measurement as static SVG, one file per chart.

    python3 analysis/measure.py > analysis/data.json
    python3 analysis/ledger_stats.py > analysis/ledger.json
    python3 analysis/gen_charts.py

Writes analysis/charts/<name>.svg. No dependencies, and no number typed by hand: everything
comes from the JSON files.

Each file carries BOTH themes and picks one itself:

  - every drawn element gets its light colour as a presentation attribute, so the chart is
    correct and readable even where the stylesheet inside the file is stripped,
  - a `<style>` block with `@media (prefers-color-scheme: dark)` overrides those colours by
    class, and CSS beats presentation attributes, so a dark viewer gets the dark chart.

One file per chart, not a light/dark pair behind `<picture>`: a `<source srcset="...">` with
a relative path is not reliably resolved when a README is rendered, and a chart that
silently does not appear is exactly the failure class this repo is about. A plain
`![alt](path)` has nothing in it to go wrong.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "charts")

# Light values are written into the file as attributes; dark values are the CSS override.
LIGHT = {"bg": "#fcfcfb", "ink": "#0b0b0b", "muted": "#52514e", "grid": "#e3e2df",
         "before": "#8b8a85", "after": "#2a78d6", "up": "#e34948", "band": "#f2f1ee"}
DARK = {"bg": "#1a1a19", "ink": "#ffffff", "muted": "#c3c2b7", "grid": "#3a3a38",
        "before": "#8b8a85", "after": "#3987e5", "up": "#e66767", "band": "#232322"}

FONT = ("ui-sans-serif, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', "
        "Arial, sans-serif")

ROLES = tuple(LIGHT)


def style_block():
    fills = "\n".join("    .f-%s { fill: %s; }" % (r, DARK[r]) for r in ROLES)
    strokes = "\n".join("    .s-%s { stroke: %s; }" % (r, DARK[r]) for r in ROLES)
    return ("<style>\n  @media (prefers-color-scheme: dark) {\n%s\n%s\n  }\n</style>"
            % (fills, strokes))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=12, role="ink", anchor="start", weight=400):
    return ('<text class="f-%s" x="%.1f" y="%.1f" font-family="%s" font-size="%d" '
            'fill="%s" text-anchor="%s" font-weight="%d">%s</text>'
            % (role, x, y, FONT, size, LIGHT[role], anchor, weight, esc(s)))


def rect(x, y, w, h, role, rx=None):
    return ('<rect class="f-%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"%s fill="%s"/>'
            % (role, x, y, w, h, ' rx="%d"' % rx if rx else "", LIGHT[role]))


def line(x1, y1, x2, y2, role, width=1, dash=None, opacity=None):
    return ('<line class="s-%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-width="%s"%s%s/>'
            % (role, x1, y1, x2, y2, LIGHT[role], width,
               ' stroke-dasharray="%s"' % dash if dash else "",
               ' opacity="%s"' % opacity if opacity else ""))


def dot(x, y, r, role, ring="bg", width=2):
    return ('<circle class="f-%s s-%s" cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" '
            'stroke-width="%d"/>' % (role, ring, x, y, r, LIGHT[role], LIGHT[ring], width))


def svg(w, h, body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d" role="img">\n%s\n%s\n%s\n</svg>\n'
            % (w, h, w, h, style_block(), rect(0, 0, w, h, "bg"), body))


def write(name, content):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "%s.svg" % name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# ---------------------------------------------------------------- chart 1: over time

def chart_rate(data):
    days = data["daily"]
    install = data["install_date"]
    W, H = 900, 340
    L, R, T, B = 52, 24, 56, 54
    pw, ph = W - L - R, H - T - B
    ymax = (int(max(d["rate_per_100"] for d in days) / 5) + 1) * 5
    n = len(days)
    step = pw / float(n - 1)
    X = lambda i: L + i * step
    Y = lambda v: T + ph - (v / float(ymax)) * ph

    p = [text(L, 26, "Commands carrying a guarded shape, per 100 issued", 15, "ink", weight=600),
         text(L, 44, "one point per day, %s to %s, %d commands"
              % (days[0]["date"], days[-1]["date"], data["totals"]["commands"]), 12, "muted")]

    for k in range(0, ymax + 1, 5):
        p.append(line(L, Y(k), W - R, Y(k), "grid"))
        p.append(text(L - 8, Y(k) + 4, k, 11, "muted", "end"))

    idx = [i for i, d in enumerate(days) if d["date"] >= install]
    if idx:
        xi = X(idx[0])
        p.append(rect(xi, T, W - R - xi, ph, "band"))
        p.append(line(xi, T - 6, xi, T + ph, "after", 2, dash="4 3"))
        p.append(text(xi + 6, T - 10, "guards go live", 12, "after", weight=600))

    for key, role in (("before", "before"), ("after", "after")):
        pts = [(X(i), Y(d["rate_per_100"])) for i, d in enumerate(days)
               if (d["date"] < install) == (key == "before")]
        if key == "after" and idx and idx[0] > 0:
            pts.insert(0, (X(idx[0] - 1), Y(days[idx[0] - 1]["rate_per_100"])))
        if len(pts) > 1:
            p.append('<polyline class="s-%s" fill="none" stroke="%s" stroke-width="2" '
                     'stroke-linejoin="round" points="%s"/>'
                     % (role, LIGHT[role], " ".join("%.1f,%.1f" % q for q in pts)))
        for x, y in pts:
            p.append(dot(x, y, 3.5, role))

    for i, d in enumerate(days):
        if i % 3 == 0 or i == n - 1:
            p.append(text(X(i), T + ph + 18, d["date"][5:], 10, "muted", "middle"))

    h = data["headline"]
    b = 100.0 * h["before_flagged"] / h["before_commands"]
    a = 100.0 * h["after_flagged"] / h["after_commands"]
    p.append(text(L, H - 18, "mean before %.2f per 100, mean after %.2f per 100 (%+.0f%%)"
                  % (b, a, 100 * (a - b) / b), 12, "muted"))
    p.append(text(W - R, H - 18, "same rules applied to both periods", 11, "muted", "end"))
    return svg(W, H, "\n".join(p))


# ---------------------------------------------------------------- chart 2: per rule

def chart_rules(data):
    rules = [(k, v) for k, v in data["per_rule"].items() if (v["before"] + v["after"]) >= 10]
    rules.sort(key=lambda kv: -(kv[1]["before_per_100"] or 0))
    W, row = 900, 30
    T, B, L, R = 78, 62, 250, 90
    H = T + row * len(rules) + B
    xmax = max(1.0, max(max(v["before_per_100"] or 0, v["after_per_100"] or 0)
                        for _, v in rules) * 1.08)
    pw = W - L - R
    X = lambda v: L + (v / xmax) * pw

    p = [text(24, 28, "Each rule, before and after it went live", 15, "ink", weight=600),
         text(24, 46, "rate per 100 commands, measured against that rule's own start date",
              12, "muted"),
         text(L, 66, "● before", 11, "before", weight=600),
         text(L + 70, 66, "● after", 11, "after", weight=600),
         text(L + 140, 66, "● after, higher than before", 11, "up", weight=600)]

    for i, (name, v) in enumerate(rules):
        y = T + i * row + row / 2
        b, a = v["before_per_100"] or 0, v["after_per_100"] or 0
        role = "up" if a > b else "after"
        p.append(line(X(b), y, X(a), y, role, 2, opacity="0.55"))
        p.append(dot(X(b), y, 5, "before"))
        p.append(dot(X(a), y, 5, role))
        p.append(text(L - 12, y + 4, name[2:] if name.startswith("r_") else name, 12,
                      "ink", "end"))
        p.append(text(W - R + 12, y + 4, ("%+.0f%%" % (100 * (a - b) / b)) if b else "new",
                      12, role, weight=600))
        p.append(text(W - R + 12, y + 16, "n=%d to %d" % (v["before"], v["after"]), 9, "muted"))

    left_out = sorted(k[2:] for k, v in data["per_rule"].items()
                      if (v["before"] + v["after"]) < 10)
    p.append(text(24, H - 34, "Left out, fewer than 10 hits in total, where one command moves "
                              "the rate: " + ", ".join(left_out) + ".", 11, "muted"))
    p.append(text(24, H - 18, "A rise is not a rule failing. A WARN does not block, and the "
                              "task mix changed between periods.", 11, "muted"))
    return svg(W, H, "\n".join(p))


# ---------------------------------------------------------------- chart 3: the ledger

CLASS_NAME = {
    "A": "asserted from memory", "B": "silent failure", "C": "measured the wrong thing",
    "D": "estimated, not measured", "E": "destroyed before verifying",
    "F": "assumed a tool contract", "G": "knob without dependents",
    "H": "state under duress", "I": "long job in the foreground",
    "J": "rule acknowledged, then broken", "K": "derived artefact carried its source",
}


def chart_ledger(ledger):
    items = sorted(ledger["by_class"].items(), key=lambda kv: -kv[1])
    W, row = 900, 34
    T, B, L, R = 76, 60, 290, 60
    H = T + row * len(items) + B
    xmax = max(v for _, v in items)
    pw = W - L - R

    p = [text(24, 28, "What the ledger caught, by class", 15, "ink", weight=600),
         text(24, 46, "%d entries, %s to %s, one line per logged mistake"
              % (ledger["entries"], ledger["first"], ledger["last"]), 12, "muted")]

    for i, (cls, n) in enumerate(items):
        y = T + i * row
        w = max((n / float(xmax)) * pw, 2)
        p.append(rect(L, y, w, 18, "after", rx=4))
        p.append(text(L - 12, y + 14, "%s  %s" % (cls, CLASS_NAME.get(cls, "")), 12, "ink", "end"))
        p.append(text(L + w + 8, y + 14, n, 12, "muted", weight=600))

    p.append(text(24, H - 32, "The ledger starts on the day the skill was written, so it holds "
                              "no before-and-after.", 11, "muted"))
    caught = ledger["by_caught_by"]
    p.append(text(24, H - 16, "Caught by " + ", ".join(
        "%s %d" % (k, v) for k, v in sorted(caught.items(), key=lambda kv: -kv[1])),
        11, "muted"))
    return svg(W, H, "\n".join(p))


def main():
    with open(os.path.join(HERE, "data.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    with open(os.path.join(HERE, "ledger.json"), encoding="utf-8") as fh:
        ledger = json.load(fh)
    for path in (write("rate-over-time", chart_rate(data)),
                 write("per-rule", chart_rules(data)),
                 write("ledger-classes", chart_ledger(ledger))):
        print(os.path.relpath(path, os.path.dirname(HERE)))


if __name__ == "__main__":
    main()
