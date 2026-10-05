"""The adjudication viewer and verdict sheet (Part 5.1 step 4).

The pages are built from a credentialed copy of MIMIC-IV. A team member
builds and exports them, and the adjudicator, who holds their own
credential, gets them in person on an encrypted drive (docs/decisions.md
2026-10-04, "Hand the pages to a credentialed adjudicator"; before that,
"Adjudication viewer"). Everything is written under
`paths.adjudication_dir`, inside the gitignored data/.

  uv run python -m crrt.adjudication_viewer build
      One static HTML page per sampled circuit, in `review_order`, plus the
      practice circuits and two verdict sheets (verdicts.csv,
      practice_verdicts.csv). Refuses to run unless the sample matches
      `adjudication_sample_sha256`. An existing sheet is never overwritten.
      Also writes what makes the folder run on its own: crrt.adjudication_app,
      its manifest.json, a launcher per platform and the guide.
  uv run python -m crrt.adjudication_viewer export
      Build, then pack that folder, without its verdict sheets, into
      adjudication_pages_<sample>.zip, for handing to a credentialed
      adjudicator in person (docs/decisions.md 2026-10-04, "Hand the pages
      to a credentialed adjudicator"). This machine's verdicts and notes
      are never in it.
  uv run python -m crrt.adjudication_viewer serve | check
      crrt.adjudication_app on this machine's pages: serve them and save each
      verdict click, or validate verdicts.csv and, once it is complete,
      write the file to send back.

A page shows the circuit as charted, from its start (at most
`adjudication_view_hours.before_end` back) to `after_end` past its end:
System Integrity, the filter change reason, CRRT mode, the machine signals,
citrate and heparin from chartevents, calcium from labevents, and death or
ICU discharge inside the window. Times are hours relative to the circuit's
end. A page never shows the stratum, the termination_class, an identifier,
an absolute timestamp, or any model output: the adjudicator is blind to all
of them.

Pressure lines use the first four slots of the dataviz reference
categorical palette, validated for light and dark surfaces. Two light-mode
slots are under 3:1 against the surface, so every line is direct-labelled
and every value is also in the table below the chart.
"""

import hashlib
import json
import math
import shutil
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import duckdb

from crrt import adjudication_app as app
from crrt import config
from crrt.adjudication import fingerprint

GUIDE = "Adjudication guide.txt"
# Double-click launchers for the pages folder, one per platform. On Windows
# it runs the Python that export packs in (python\), so nothing is installed;
# a folder built without it falls back to an installed Python. On a Mac or
# Linux it runs python3 (docs/adjudication_guide.md).
LAUNCHERS = {
    "Adjudicate.bat": ('@echo off\r\ncd /d "%~dp0"\r\n'
                       'if exist "python\\python.exe" goto packed\r\n'
                       "where py >nul 2>nul\r\n"
                       "if %errorlevel%==0 (py -3 adjudication_app.py) else (python adjudication_app.py)\r\n"
                       "goto done\r\n:packed\r\npython\\python.exe adjudication_app.py\r\n:done\r\npause\r\n"),
    "Adjudicate.command": '#!/bin/bash\ncd "$(dirname "$0")" || exit 1\nexec python3 adjudication_app.py\n',
    "Adjudicate.sh": '#!/bin/bash\ncd "$(dirname "$0")" || exit 1\nexec python3 adjudication_app.py\n',
}
# Everything in an exported package besides the pages and the packed Python.
# A list of what goes in, not of what stays out, so nothing else can leak.
PACKAGE_FILES = (app.MANIFEST, "adjudication_app.py", GUIDE, *LAUNCHERS)

# Chart geometry, in px.
W, H = 880, 260
LEFT, RIGHT, TOP, BOTTOM = 52, 150, 12, 30
LABEL_GAP = 14
X_TICK_STEPS = (1, 2, 3, 6, 12, 24)
MAX_X_TICKS = 13
Y_TICKS = 5
NICE_STEPS = (1, 2, 5, 10)
CHART_MIN_WIDTH = 720

CSS = """
:root { --surface:#fcfcfb; --ink:#1f1f1e; --ink-2:#5f5e58; --rule:#e4e3dd;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --bad:#b3261e; --bad-ink:#b3261e; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --surface:#1a1a19; --ink:#ffffff;
  --ink-2:#c3c2b7; --rule:#3a3a37; --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --s4:#c98500; --bad:#b3261e; --bad-ink:#ff8a80; color-scheme: dark; } }
body { background:var(--surface); color:var(--ink); font:15px/1.45 system-ui, sans-serif;
  margin:0 auto; padding:16px 16px 150px; max-width:1600px; }
h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:16px; margin:24px 0 8px; }
.meta, .muted { color:var(--ink-2); }
nav { display:flex; gap:16px; margin:8px 0 16px; }
a { color:var(--s1); }
.legend { display:flex; flex-wrap:wrap; gap:16px; margin:4px 0; color:var(--ink-2); }
.sw { display:inline-block; width:18px; height:2px; vertical-align:middle; margin-right:6px; }
.chart { max-width:1100px; }
svg text { fill:var(--ink-2); font-size:12px; }
.grid { stroke:var(--rule); stroke-width:1; }
.end { stroke:var(--ink); stroke-width:1; }
.event { stroke:var(--ink-2); stroke-width:1; stroke-dasharray:4 3; }
.hit { fill:transparent; }
.tablewrap { overflow-x:auto; }
table { border-collapse:collapse; font-size:13px; }
th, td { border-bottom:1px solid var(--rule); padding:3px 8px; text-align:right; white-space:nowrap; }
th:first-child, td:first-child { position:sticky; left:0; background:var(--surface); }
td.text { text-align:left; }
tr.after td { background:color-mix(in srgb, var(--rule) 45%, transparent); }
/* The flowsheet fits the page width: headers and text wrap, and the header
   row stays in view while the page scrolls. */
.flow { width:100%; min-width:960px; table-layout:fixed; }
.flow col.t { width:4.5em; } .flow col.txt { width:8.5em; }
.flow th { position:sticky; top:0; z-index:1; background:var(--surface); font-size:12px; vertical-align:bottom;
  white-space:normal; hyphens:auto; overflow-wrap:anywhere; padding:3px 4px;
  box-shadow:inset 0 -1px var(--rule); }
.flow th:first-child { z-index:2; }
.flow td { white-space:normal; padding:3px 4px; }
.flow tbody tr:hover td { background:color-mix(in srgb, var(--s1) 14%, var(--surface)); }
/* The verdict bar, always at the bottom of the window. */
.bar { position:fixed; left:0; right:0; bottom:0; z-index:3; background:var(--surface);
  border-top:1px solid var(--rule); box-shadow:0 -2px 10px rgb(0 0 0 / 0.12); }
.bar-in { max-width:1600px; margin:0 auto; padding:10px 16px; display:flex; flex-wrap:wrap;
  align-items:center; gap:8px 12px; }
.ask { font-weight:600; }
.choices { display:flex; flex-wrap:wrap; gap:8px; }
.bar button, .cta, .finished button { font:inherit; font-size:16px; padding:9px 16px;
  border-radius:8px; border:2px solid var(--ink-2); background:var(--surface);
  color:var(--ink); cursor:pointer; }
.bar button[aria-pressed="true"] { background:var(--ink); border-color:var(--ink);
  color:var(--surface); font-weight:600; }
.status { font-weight:600; min-width:6em; } .status.bad { color:var(--bad-ink); }
.bar nav { margin:0 0 0 auto; align-items:center; }
.bar a.next, .cta { border-color:var(--s1); color:var(--s1); font-weight:600;
  text-decoration:none; padding:9px 16px; border-radius:8px; border:2px solid var(--s1); }
#note { flex-basis:100%; font:inherit; padding:6px 8px; border:1px solid var(--rule);
  border-radius:6px; background:var(--surface); color:var(--ink); resize:vertical; }
.banner { position:sticky; top:0; z-index:4; background:var(--bad); color:#fff;
  padding:12px 16px; border-radius:8px; font-weight:600; margin-bottom:12px; }
.track { height:10px; border-radius:5px; background:var(--rule); overflow:hidden; max-width:480px; }
#fill { height:100%; width:0; background:var(--s3); }
.cta { display:inline-block; margin:12px 0; }
.finished { border:2px solid var(--s3); border-radius:8px; padding:4px 16px 16px; max-width:640px;
  margin:12px 0; }
.mark { color:var(--ink-2); margin-left:8px; }
[hidden] { display:none !important; }
"""

# Runs on every page. A circuit page shows its saved verdict and saves each
# click; a list page shows progress. Opened without the server (from disk, or
# after the launcher window is closed), it says so instead of failing quietly.
SCRIPT = """
(() => {
  const d = document.body.dataset, labels = JSON.parse(d.labels);
  const banner = document.getElementById("banner");
  async function api(path, data) {
    let r;
    try {
      r = await fetch(path, data && {method: "POST", keepalive: true,
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
    } catch (e) {
      banner.hidden = false;
      throw new Error("the Adjudicate window is closed");
    }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  if (d.kind) circuit(); else list();

  function circuit() {
    const status = document.getElementById("status"), note = document.getElementById("note");
    const buttons = [...document.querySelectorAll("button[data-verdict]")];
    const show = v => buttons.forEach(b => b.setAttribute("aria-pressed", String(b.dataset.verdict === v)));
    const say = (text, bad) => { status.textContent = text; status.classList.toggle("bad", !!bad); };
    let savedNote = "";
    async function save(fields) {
      say("Saving…");
      try {
        await api("/api/verdict", {kind: d.kind, n: Number(d.n), ...fields});
        say("Saved ✓");
        return true;
      } catch (e) {
        say("Not saved: " + e.message, true);
        return false;
      }
    }
    api("/api/verdicts").then(all => {
      const row = all[d.kind][d.n] || {};
      show(row.verdict);
      note.value = savedNote = row.note || "";
      if (row.verdict) say("Saved ✓");
    }).catch(e => say("Not saved: " + e.message, true));
    buttons.forEach(b => b.addEventListener("click", async () => {
      if (await save({verdict: b.dataset.verdict})) show(b.dataset.verdict);
    }));
    async function saveNote() {
      const text = note.value;
      if (text !== savedNote && await save({note: text})) savedNote = text;
    }
    note.addEventListener("change", saveNote);
    addEventListener("pagehide", saveNote);
  }

  function list() {
    const items = [...document.querySelectorAll("li[data-n]")];
    api("/api/verdicts").then(all => {
      const rows = all[d.list];
      let done = 0, next = null;
      for (const li of items) {
        const v = (rows[li.dataset.n] || {}).verdict;
        li.querySelector(".mark").textContent = v ? "✓ " + labels[v] : "";
        if (v) done++; else if (!next) next = li;
      }
      document.getElementById("count").textContent = `${done} of ${items.length} done`;
      document.getElementById("fill").style.width = `${100 * done / items.length}%`;
      const go = document.getElementById("continue");
      if (next) go.href = next.querySelector("a").getAttribute("href"); else go.hidden = true;
      const finished = document.getElementById("finished");
      if (finished && !next && all.send) {
        document.getElementById("sendname").textContent = all.send;
        finished.hidden = false;
      }
    }).catch(() => {});
    const reveal = document.getElementById("reveal");
    if (reveal) reveal.addEventListener("click", () =>
      api("/api/reveal", {}).catch(e => alert("Could not open the folder: " + e.message)));
  }
})();
"""

BANNER = ('<div id="banner" class="banner" hidden>Answers can\'t be saved here. Close this '
          'page and double-click <b>Adjudicate</b> on your desktop.</div>')

SERIES_VARS = ("--s1", "--s2", "--s3", "--s4")


def columns(cfg: dict[str, Any]) -> list[tuple[str, int, bool]]:
    """(label, chartevents itemid, is text), in display order."""
    c, f = cfg["circuits"], cfg["features"]
    cols = [("System Integrity", c["system_integrity_itemid"], True),
            ("Filter change reason", c["filter_change_reason_itemid"], True),
            ("CRRT mode", f["crrt_mode_itemid"], True)]
    for group in (f["machine_signals"], f["anticoag_signals"]):
        cols += [(name.replace("_", " ").capitalize(), itemid, False)
                 for name, itemid in group.items()]
    return cols


def pressure_itemids(cfg: dict[str, Any]) -> list[tuple[str, int]]:
    return [(name.replace("_", " ").capitalize(), itemid)
            for name, itemid in cfg["features"]["machine_signals"].items()
            if name.endswith("_pressure")]


def hours(t: datetime, end: datetime) -> float:
    return (t - end).total_seconds() / 3600


def clock(h: float) -> str:
    """Hours as hours:minutes, signed: −12:30, 0:00, +1:15."""
    minutes = round(h * 60)
    sign = "−" if minutes < 0 else ("+" if minutes > 0 else "")
    hh, mm = divmod(abs(minutes), 60)
    return f"{sign}{hh}:{mm:02d}"


def rel(t: datetime, end: datetime) -> str:
    """A time relative to the circuit end."""
    return clock(hours(t, end))


def fmt(v: float) -> str:
    return f"{v:.0f}" if abs(v) >= 100 else f"{v:.2f}".rstrip("0").rstrip(".")


def gather(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> list[dict]:
    """One dict per page, sample then practice, with everything it shows."""
    cf = cfg["outcomes"]["circuit_failure"]
    view = cf["adjudication_view_hours"]
    con.execute(
        "CREATE OR REPLACE TEMP TABLE viewer_windows AS "
        "SELECT 'sample' AS kind, s.review_order AS n, c.stay_id, c.subject_id, c.hadm_id, "
        "       c.circuit_start, c.circuit_end, c.duration_hours "
        "FROM adjudication_sample AS s JOIN crrt_circuits AS c USING (circuit_id) "
        "UNION ALL "
        "SELECT 'practice', p.practice_order, c.stay_id, c.subject_id, c.hadm_id, "
        "       c.circuit_start, c.circuit_end, c.duration_hours "
        "FROM adjudication_practice AS p JOIN crrt_circuits AS c USING (circuit_id)"
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE viewer_windows2 AS SELECT *, "
        "  greatest(circuit_start, circuit_end - to_hours(?::BIGINT)) AS lo, "
        "  circuit_end + to_hours(?::BIGINT) AS hi FROM viewer_windows",
        [view["before_end"], view["after_end"]],
    )
    pages = {(k, n): dict(kind=k, n=n, start=s, end=e, duration=d, lo=lo, hi=hi,
                          chart=[], labs=[], events=[])
             for k, n, s, e, d, lo, hi in con.execute(
                 "SELECT kind, n, circuit_start, circuit_end, duration_hours, lo, hi "
                 "FROM viewer_windows2").fetchall()}

    itemids = [i for _, i, _ in columns(cfg)]
    for k, n, t, itemid, value, valuenum, uom in con.execute(
        "SELECT w.kind, w.n, c.charttime, c.itemid, c.value, c.valuenum, c.valueuom "
        "FROM chartevents AS c JOIN viewer_windows2 AS w "
        "  ON c.stay_id = w.stay_id AND c.charttime BETWEEN w.lo AND w.hi "
        "WHERE list_contains(?, c.itemid) ORDER BY c.charttime",
        [itemids],
    ).fetchall():
        pages[(k, n)]["chart"].append((t, itemid, value, valuenum, uom))

    labs = cfg["features"]["calcium_labs"]
    names = {itemid: name.replace("_", " ").capitalize() for name, itemid in labs.items()}
    for k, n, t, itemid, valuenum, uom in con.execute(
        "SELECT w.kind, w.n, l.charttime, l.itemid, l.valuenum, l.valueuom "
        "FROM labevents AS l JOIN viewer_windows2 AS w "
        "  ON l.subject_id = w.subject_id AND l.charttime BETWEEN w.lo AND w.hi "
        "WHERE list_contains(?, l.itemid) AND l.valuenum IS NOT NULL ORDER BY l.charttime",
        [list(labs.values())],
    ).fetchall():
        pages[(k, n)]["labs"].append((t, names[itemid], valuenum, uom))

    for k, n, death, out in con.execute(
        "SELECT w.kind, w.n, a.deathtime, i.outtime FROM viewer_windows2 AS w "
        "LEFT JOIN admissions AS a ON a.hadm_id = w.hadm_id "
        "LEFT JOIN icustays AS i ON i.stay_id = w.stay_id"
    ).fetchall():
        p = pages[(k, n)]
        for label, t in (("Death", death), ("ICU discharge", out)):
            if t is not None and p["lo"] <= t <= p["hi"]:
                p["events"].append((t, label))
    return sorted(pages.values(), key=lambda p: (p["kind"] != "sample", p["n"]))


def chart_svg(page: dict, cfg: dict[str, Any]) -> str:
    end = page["end"]
    series = []
    for (label, itemid), var in zip(pressure_itemids(cfg), SERIES_VARS):
        pts = [(hours(t, end), v) for t, i, _, v, _ in page["chart"] if i == itemid and v is not None]
        series.append((label, var, pts))
    values = [v for _, _, pts in series for _, v in pts]
    if not values:
        return '<p class="muted">No pressures charted in this window.</p>'
    x0, x1 = hours(page["lo"], end), hours(page["hi"], end)
    # Round tick steps (1, 2 or 5 times a power of ten), axis snapped to them.
    raw = (max(values) - min(values)) / Y_TICKS or 1
    mag = 10 ** math.floor(math.log10(raw))
    ystep = next(k * mag for k in NICE_STEPS if k * mag >= raw)
    y0 = math.floor(min(values) / ystep) * ystep
    y1 = math.ceil(max(values) / ystep) * ystep
    if y1 == y0:
        y1 = y0 + ystep

    def X(h): return LEFT + (h - x0) / (x1 - x0) * (W - LEFT - RIGHT)
    def Y(v): return TOP + (y1 - v) / (y1 - y0) * (H - TOP - BOTTOM)

    out = [f'<div class="tablewrap chart"><svg viewBox="0 0 {W} {H}" width="100%" '
           f'style="min-width:{CHART_MIN_WIDTH}px" role="img" '
           'aria-label="Circuit pressures in mmHg against hours from the circuit end">']
    for k in range(round((y1 - y0) / ystep) + 1):
        v = y0 + k * ystep
        out.append(f'<line class="grid" x1="{LEFT}" x2="{W - RIGHT}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text x="{LEFT - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:.0f}</text>')
    step = next((s for s in X_TICK_STEPS if (x1 - x0) / s < MAX_X_TICKS), X_TICK_STEPS[-1])
    tick = math.ceil(x0 / step) * step
    while tick <= x1:
        label = f"{tick:+.0f} h" if tick else "end"
        out.append(f'<text x="{X(tick):.1f}" y="{H - 8}" text-anchor="middle">{label}</text>')
        tick += step
    out.append(f'<line class="end" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{TOP}" y2="{H - BOTTOM}"/>')
    for t, label in page["events"]:
        x = X(hours(t, end))
        out.append(f'<line class="event" x1="{x:.1f}" x2="{x:.1f}" y1="{TOP}" y2="{H - BOTTOM}"/>'
                   f'<text x="{x + 4:.1f}" y="{TOP + 12}">{escape(label)}</text>')
    ends = []
    for label, var, pts in series:
        if not pts:
            continue
        line = " ".join(f"{X(h):.1f},{Y(v):.1f}" for h, v in pts)
        out.append(f'<polyline points="{line}" fill="none" stroke="var({var})" stroke-width="2" '
                   'stroke-linejoin="round" stroke-linecap="round"/>')
        for h, v in pts:
            out.append(f'<circle class="hit" cx="{X(h):.1f}" cy="{Y(v):.1f}" r="6">'
                       f'<title>{escape(label)} {fmt(v)} mmHg at {clock(h)}</title></circle>')
        ends.append([Y(pts[-1][1]), label, var, pts[-1][1]])
    # Direct labels at the right margin, nudged apart so none overlap.
    ends.sort()
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + LABEL_GAP)
    for y, label, var, v in ends:
        x = W - RIGHT + 8
        out.append(f'<line x1="{x}" x2="{x + 14}" y1="{y:.1f}" y2="{y:.1f}" stroke="var({var})" stroke-width="2"/>'
                   f'<text x="{x + 18}" y="{y + 4:.1f}">{escape(label)} {fmt(v)}</text>')
    out.append("</svg></div>")
    return "".join(out)


def flowsheet(page: dict, cfg: dict[str, Any]) -> str:
    cols = columns(cfg)
    units: dict[int, str] = {}
    rows: dict[datetime, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for t, itemid, value, valuenum, uom in page["chart"]:
        shown = fmt(valuenum) if valuenum is not None else (value or "")
        if shown:
            rows[t][itemid].append(shown)
        if uom and itemid not in units:
            units[itemid] = uom
    present = [c for c in cols if any(c[1] in r for r in rows.values())]
    widths = '<col class="t">' + "".join('<col class="txt">' if text else "<col>" for _, _, text in present)
    head = "".join(f"<th>{escape(label)}" + (f"<br><span class=muted>{escape(units[i])}</span>" if i in units else "")
                   + "</th>" for label, i, _ in present)
    body = []
    for t in sorted(rows):
        cls = ' class="after"' if t > page["end"] else ""
        cells = "".join(f'<td{" class=text" if text else ""}>{escape(" / ".join(rows[t].get(i, [])))}</td>'
                        for _, i, text in present)
        body.append(f"<tr{cls}><td>{rel(t, page['end'])}</td>{cells}</tr>")
    return (f'<table class="flow"><colgroup>{widths}</colgroup><thead><tr><th>Time</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def labs_table(page: dict) -> str:
    if not page["labs"]:
        return '<p class="muted">No calcium results in this window.</p>'
    rows = "".join(f"<tr><td>{rel(t, page['end'])}</td><td class=text>{escape(name)}</td>"
                   f"<td>{fmt(v)}</td><td class=text>{escape(uom or '')}</td></tr>"
                   for t, name, v, uom in page["labs"])
    return f"<table><thead><tr><th>Time</th><th>Test</th><th>Value</th><th>Unit</th></tr></thead><tbody>{rows}</tbody></table>"


def name_of(page: dict) -> str:
    return f"Circuit {page['n']}" if page["kind"] == "sample" else f"Practice {page['n']}"


def file_of(page: dict) -> str:
    return f"circuit_{page['n']:03d}.html" if page["kind"] == "sample" else f"practice_{page['n']}.html"


def verdict_labels(cfg: dict[str, Any]) -> dict[str, str]:
    """What each verdict's button says: clotting -> Clotting."""
    return {v: v.replace("_", " ").capitalize()
            for v in cfg["outcomes"]["circuit_failure"]["adjudication_verdicts"]}


def html_page(title: str, body: str, cfg: dict[str, Any], **data: Any) -> str:
    """A page; `data` become the body's data- attributes, read by SCRIPT."""
    data["labels"] = json.dumps(verdict_labels(cfg))
    attrs = "".join(f' data-{k}="{escape(str(v))}"' for k, v in data.items())
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head>"
            f"<body{attrs}>{BANNER}{body}<script>{SCRIPT}</script></body></html>")


def verdict_bar(page: dict, prev: dict | None, nxt: dict | None, cfg: dict[str, Any]) -> str:
    """The buttons, the save status, the note and Previous / Next, fixed to
    the bottom of the window. SCRIPT marks the saved verdict."""
    buttons = "".join(f'<button type="button" data-verdict="{v}" aria-pressed="false">{escape(label)}</button>'
                      for v, label in verdict_labels(cfg).items())
    links = [f'<a href="{file_of(prev)}">← {name_of(prev)}</a>'] if prev else []
    links.append(f'<a class="next" href="{file_of(nxt)}">{name_of(nxt)} →</a>' if nxt
                 else '<a class="next" href="index.html">Back to the list</a>')
    practice = '<span class="muted">Practice: not counted</span>' if page["kind"] == "practice" else ""
    return f"""
<div class="bar"><div class="bar-in">
<span class="ask">Why did it stop?</span>
<span class="choices" role="group" aria-label="Why did it stop?">{buttons}</span>
<span id="status" class="status" role="status"></span>{practice}
<nav>{''.join(links)}</nav>
<textarea id="note" rows="1" aria-label="Note" placeholder="Note (optional). It stays on this computer."></textarea>
</div></div>"""


def render(page: dict, prev: dict | None, nxt: dict | None, total: int, cfg: dict[str, Any]) -> str:
    end = page["end"]
    shown_from = hours(page["lo"], end)
    nav = ['<a href="index.html">All circuits</a>']
    if prev:
        nav.append(f'<a href="{file_of(prev)}">← {name_of(prev)}</a>')
    if nxt:
        nav.append(f'<a href="{file_of(nxt)}">{name_of(nxt)} →</a>')
    of = f" of {total}" if page["kind"] == "sample" else " (not counted)"
    events = ("".join(f"<li>{escape(label)} at {rel(t, end)}</li>" for t, label in page["events"])
              or "<li>No death or ICU discharge in this window.</li>")
    legend = "".join(f'<span><span class="sw" style="background:var({var})"></span>{escape(label)}</span>'
                     for (label, _), var in zip(pressure_itemids(cfg), SERIES_VARS))
    body = f"""
<nav>{''.join(nav)}</nav>
<h1>{name_of(page)}{of}</h1>
<p class="meta">The circuit ran {page['duration']:.1f} h. Times are hours:minutes from the
circuit's end (0:00), shown from {clock(shown_from)} to {clock(hours(page['hi'], end))}.
Shaded rows are after the end.</p>
<h2>After the end</h2><ul>{events}</ul>
<h2>Pressures (mmHg)</h2><div class="legend">{legend}</div>
{chart_svg(page, cfg)}
<h2>Flowsheet</h2>
{flowsheet(page, cfg)}
<h2>Calcium</h2>
{labs_table(page)}
{verdict_bar(page, prev, nxt, cfg)}"""
    return html_page(name_of(page), body, cfg, kind=page["kind"], n=page["n"])


def index(pages: list[dict], heading: str, note: str, cfg: dict[str, Any]) -> str:
    """A list page. SCRIPT fills in progress, ticks and where to continue."""
    kind = pages[0]["kind"]
    links = "".join(f'<li data-n="{p["n"]}"><a href="{file_of(p)}">{name_of(p)}</a><span class="mark"></span></li>'
                    for p in pages)
    finished = ('<div id="finished" class="finished" hidden><p><b>All done. Thank you.</b> Send this '
                'one file to the study team: <code id="sendname"></code></p>'
                '<button type="button" id="reveal">Show me the file</button></div>') if kind == "sample" else ""
    body = (f'<h1>{escape(heading)}</h1><p class=meta>{note}</p>'
            f'<p><b id="count"></b></p><div class="track"><div id="fill"></div></div>'
            f'<a id="continue" class="cta" href="{file_of(pages[0])}">Continue where I left off</a>'
            f"{finished}<ol>{links}</ol>")
    return html_page(heading, body, cfg, list=kind)


def build(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], out: Path) -> None:
    frozen = cfg["outcomes"]["circuit_failure"]["adjudication_sample_sha256"]
    if fingerprint(con) != frozen:
        raise SystemExit("adjudication_sample does not match adjudication_sample_sha256: "
                         "rerun stage 3b and check the circuits and cohort before adjudicating.")
    pages = gather(con, cfg)
    sample = [p for p in pages if p["kind"] == "sample"]
    practice = [p for p in pages if p["kind"] == "practice"]
    (out / "practice").mkdir(parents=True, exist_ok=True)
    for group, folder in ((sample, out), (practice, out / "practice")):
        for k, p in enumerate(group):
            prev = group[k - 1] if k else None
            nxt = group[k + 1] if k + 1 < len(group) else None
            # UTF-8 stated: the pages hold − and →, which Windows' default
            # encoding cannot write.
            (folder / file_of(p)).write_text(render(p, prev, nxt, len(sample), cfg), encoding="utf-8")
    (out / "index.html").write_text(index(
        sample, "Circuits to adjudicate",
        f'Read the guide first: "{GUIDE}", in this folder. Practice circuits for the training session: '
        '<a href="practice/index.html">practice</a>.', cfg), encoding="utf-8")
    (out / "practice" / "index.html").write_text(index(
        practice, "Practice circuits", 'For the calibration session. These verdicts are not counted. '
        '<a href="../index.html">Back to the circuits to adjudicate</a>.', cfg), encoding="utf-8")
    # The rest of a runnable folder: the app, its settings, the launchers and
    # the guide, so the folder runs anywhere Python does.
    settings = manifest(cfg, len(practice))
    (out / app.MANIFEST).write_text(json.dumps(settings, indent=2), encoding="utf-8")
    app.ensure_sheets(settings, out)
    shutil.copyfile(app.__file__, out / "adjudication_app.py")
    shutil.copyfile(config.REPO_ROOT / "docs" / "adjudication_guide.md", out / GUIDE)
    for name, text in LAUNCHERS.items():
        (out / name).write_text(text, encoding="utf-8", newline="")
        if not name.endswith(".bat"):
            (out / name).chmod(0o755)
    print(f"wrote {len(sample)} circuit pages and {len(practice)} practice pages to {out}")
    print(f"open them by double-clicking Adjudicate in {out}")


def manifest(cfg: dict[str, Any], practice_size: int) -> dict[str, Any]:
    """The settings the app reads instead of config/config.yaml."""
    cf = cfg["outcomes"]["circuit_failure"]
    return {"sample_sha256": cf["adjudication_sample_sha256"], "sample_size": sample_size(cfg),
            "practice_size": practice_size, "verdicts": cf["adjudication_verdicts"],
            "port": cf["adjudication_port"]}


def package_name(cfg: dict[str, Any]) -> str:
    """The export's file name. It names the sample, so the package cannot be
    mistaken for one built from another sample."""
    return f"adjudication_pages_{cfg['outcomes']['circuit_failure']['adjudication_sample_sha256'][:12]}.zip"


def windows_python(cfg: dict[str, Any], folder: Path) -> Path:
    """python.org's embeddable Python for Windows
    (`adjudication_windows_python`), downloaded once into `folder` and
    checked against its pinned SHA-256 on every export."""
    py = cfg["outcomes"]["circuit_failure"]["adjudication_windows_python"]
    path = folder / py["url"].rsplit("/", 1)[1]
    if not path.exists():
        part = path.with_name(path.name + ".part")
        urllib.request.urlretrieve(py["url"], part)
        part.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != py["sha256"]:
        path.unlink()
        raise SystemExit(f"{path.name} does not match its pinned SHA-256 and was deleted. Run export again.")
    return path


def export(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], out: Path) -> Path:
    """Build the pages, then pack the runnable folder for a credentialed
    adjudicator (docs/decisions.md 2026-10-04, "Hand the pages to a
    credentialed adjudicator"). The package holds the pages,
    `PACKAGE_FILES` and, under python/, the Windows Python, so a Windows
    adjudicator installs nothing. It holds no verdict sheet: never this machine's
    verdicts or notes, and nothing that could overwrite the adjudicator's
    when a newer package is unzipped over their folder; the app creates the
    sheets empty. It is written next to `out`, inside the gitignored data/."""
    build(con, cfg, out)
    package = out.parent / package_name(cfg)
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
        for page in sorted(out.rglob("*.html")):
            z.write(page, page.relative_to(out).as_posix())
        for name in PACKAGE_FILES:
            z.write(out / name, name)  # Keeps the launchers' executable bit.
        with zipfile.ZipFile(windows_python(cfg, out.parent)) as py:
            for member in py.namelist():
                z.writestr(f"python/{member}", py.read(member))
    print(f"wrote {package}\nCopy it to an encrypted USB drive and hand it over in person. "
          "Never by email, cloud storage or chat (docs/adjudication_guide.md).")
    return package


def sample_size(cfg: dict[str, Any]) -> int:
    return sum(s["circuits"] for s in cfg["outcomes"]["circuit_failure"]["adjudication_strata"].values())


def main() -> None:
    cfg = config.load()
    out = config.path(cfg, "adjudication_dir")
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in ("build", "export"):
        con = duckdb.connect(str(config.path(cfg, "duckdb")), read_only=True)
        (build if command == "build" else export)(con, cfg, out)
        con.close()
    elif command == "serve":
        app.serve(out)
    elif command == "check":
        app.check(app.settings(out), out)
    else:
        raise SystemExit("usage: python -m crrt.adjudication_viewer build|export|serve|check")


if __name__ == "__main__":
    main()
