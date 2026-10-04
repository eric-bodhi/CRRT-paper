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
  uv run python -m crrt.adjudication_viewer export
      Build, then pack the pages with empty verdict sheets into
      adjudication_pages_<sample>.zip, for handing to a credentialed
      adjudicator in person (docs/decisions.md 2026-10-04, "Hand the pages
      to a credentialed adjudicator"). This machine's verdicts and notes
      are never in it.
  uv run python -m crrt.adjudication_viewer serve
      What the desktop launcher runs (crrt.adjudication_setup). Serves the
      pages on 127.0.0.1 and opens the browser. Each verdict button saves to
      the sheet at once, so a revisited page shows its verdict; once every
      circuit has one, the file to send is written. A page opened from disk
      cannot write a file, which is why this is a server; it uses only the
      standard library.
  uv run python -m crrt.adjudication_viewer check
      Validates verdicts.csv. Once every circuit has a verdict, writes the
      file to send back: review_order and verdict only. The notes column
      stays on this machine, because a note can quote a charted value.

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

import csv
import io
import json
import math
import os
import subprocess
import sys
import threading
import urllib.request
import webbrowser
import zipfile
from collections import defaultdict
from datetime import datetime
from functools import partial
from html import escape
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import duckdb

from crrt import config
from crrt.adjudication import fingerprint

SHEET = "verdicts.csv"
PRACTICE_SHEET = "practice_verdicts.csv"
# Page kind: (sheet, its key column).
SHEETS = {"sample": (SHEET, "review_order"), "practice": (PRACTICE_SHEET, "practice_order")}
# What /api/ping answers, so a second double-click can tell this app from
# another program on the port.
APP = "crrt-adjudication"
PING_SECONDS = 2

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
        'Read docs/adjudication_guide.md first. Practice circuits for the training session: '
        '<a href="practice/index.html">practice</a>.', cfg), encoding="utf-8")
    (out / "practice" / "index.html").write_text(index(
        practice, "Practice circuits", 'For the calibration session. These verdicts are not counted. '
        '<a href="../index.html">Back to the circuits to adjudicate</a>.', cfg), encoding="utf-8")
    for kind, group in (("sample", sample), ("practice", practice)):
        sheet, key = SHEETS[kind]
        if not (out / sheet).exists():
            write_sheet(out / sheet, key, {p["n"]: ["", ""] for p in group})
    print(f"wrote {len(sample)} circuit pages and {len(practice)} practice pages to {out}")
    print("start the app with: uv run python -m crrt.adjudication_viewer serve")


def read_sheet(path: Path) -> dict[int, list[str]]:
    """{order: [verdict, note]}. Empty if the sheet does not exist yet."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r[0]): [r[1], r[2]] for r in list(csv.reader(f))[1:]}


def sheet_text(key: str, rows: dict[int, list[str]]) -> str:
    text = io.StringIO()
    w = csv.writer(text)
    w.writerow([key, "verdict", "note"])
    w.writerows([n, verdict, note] for n, (verdict, note) in sorted(rows.items()))
    return text.getvalue()


def write_sheet(path: Path, key: str, rows: dict[int, list[str]]) -> None:
    """Write the whole sheet to a temporary file, then swap it in, so a
    crash never leaves half a sheet."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(sheet_text(key, rows), encoding="utf-8", newline="")
    os.replace(tmp, path)


def package_name(cfg: dict[str, Any]) -> str:
    """The export's file name. It names the sample, so setup on the
    adjudicator's machine accepts only the package for its own config."""
    return f"adjudication_pages_{cfg['outcomes']['circuit_failure']['adjudication_sample_sha256'][:12]}.zip"


def export(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], out: Path) -> Path:
    """Build the pages, then pack them for a credentialed adjudicator
    (docs/decisions.md 2026-10-04, "Hand the pages to a credentialed
    adjudicator"). The package holds every page and empty verdict sheets,
    never this machine's verdicts or notes. It is written next to `out`,
    inside the gitignored data/."""
    build(con, cfg, out)
    package = out.parent / package_name(cfg)
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
        for page in sorted(out.rglob("*.html")):
            z.write(page, page.relative_to(out).as_posix())
        for sheet, key in SHEETS.values():
            z.writestr(sheet, sheet_text(key, {n: ["", ""] for n in read_sheet(out / sheet)}))
    print(f"wrote {package}\nCopy it to an encrypted USB drive and hand it over in person. "
          "Never by email, cloud storage or chat (docs/adjudication_guide.md).")
    return package


def sample_size(cfg: dict[str, Any]) -> int:
    return sum(s["circuits"] for s in cfg["outcomes"]["circuit_failure"]["adjudication_strata"].values())


def send_file(cfg: dict[str, Any], out: Path) -> Path:
    """The one file that goes back to the team."""
    return out / f"verdicts_send_{cfg['outcomes']['circuit_failure']['adjudication_sample_sha256'][:12]}.csv"


def check(cfg: dict[str, Any], out: Path, n_expected: int) -> Path | None:
    """Validate the sheet. Returns the file to send once it is complete."""
    allowed = set(cfg["outcomes"]["circuit_failure"]["adjudication_verdicts"])
    with (out / SHEET).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    orders = [r["review_order"] for r in rows]
    expected = [str(k) for k in range(1, n_expected + 1)]
    if sorted(orders, key=int) != expected:
        raise ValueError(f"{SHEET} must have review_order 1 to {n_expected}, each once")
    bad = [r["review_order"] for r in rows if r["verdict"].strip() and r["verdict"].strip() not in allowed]
    if bad:
        raise ValueError(f"not one of {sorted(allowed)} at review_order {', '.join(bad)}")
    done = sum(bool(r["verdict"].strip()) for r in rows)
    print(f"{done} of {n_expected} circuits have a verdict")
    if done < n_expected:
        return None
    send = send_file(cfg, out)
    with send.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["review_order", "verdict"])
        w.writerows(sorted(((int(r["review_order"]), r["verdict"].strip()) for r in rows)))
    print(f"wrote {send}: review_order and verdict only, no notes")
    return send


def reveal(path: Path) -> None:
    """Show `path` in the file manager, selected where the platform can."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


class Handler(SimpleHTTPRequestHandler):
    """Serves the pages under `out` and saves verdicts to the sheets.

    The server listens on 127.0.0.1, so nothing outside this computer can
    reach it. A web page open in another tab still could, so a request
    naming any other host (DNS rebinding, which would let it read pages) is
    refused, and so is a POST from any other origin or not sent as JSON
    (which would let it change verdicts)."""

    def __init__(self, *args: Any, cfg: dict[str, Any], out: Path, **kwargs: Any):
        self.cfg, self.out = cfg, out
        super().__init__(*args, directory=str(out), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # The launcher window is for the adjudicator, not a request log.

    def local(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def reply(self, status: HTTPStatus, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_head(self):  # Every static GET and HEAD passes through here.
        if self.headers.get("Host") not in self.local():
            self.send_error(HTTPStatus.FORBIDDEN)
            return None
        return super().send_head()

    def do_GET(self) -> None:
        if not self.path.startswith("/api/"):
            return super().do_GET()
        if self.headers.get("Host") not in self.local():
            return self.reply(HTTPStatus.FORBIDDEN, {"error": "refused"})
        if self.path == "/api/ping":
            return self.reply(HTTPStatus.OK, {"app": APP})
        if self.path == "/api/verdicts":
            body: dict[str, Any] = {
                kind: {str(n): {"verdict": v, "note": note} for n, (v, note) in read_sheet(self.out / sheet).items()}
                for kind, (sheet, _) in SHEETS.items()}
            send = send_file(self.cfg, self.out)
            body["send"] = send.name if send.exists() else None
            return self.reply(HTTPStatus.OK, body)
        self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        local = self.local()
        if (self.headers.get("Host") not in local
                or self.headers.get("Origin") not in {f"http://{h}" for h in local}
                or self.headers.get_content_type() != "application/json"):
            return self.reply(HTTPStatus.FORBIDDEN, {"error": "refused"})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self.reply(HTTPStatus.BAD_REQUEST, {"error": "the request could not be read"})
        if self.path == "/api/verdict":
            return self.save(data)
        if self.path == "/api/reveal":
            send = send_file(self.cfg, self.out)
            reveal(send if send.exists() else self.out)
            return self.reply(HTTPStatus.OK, {})
        self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def save(self, data: Any) -> None:
        """Set the verdict and/or note of one circuit, from {kind, n,
        verdict?, note?}, and rewrite its sheet."""
        allowed = self.cfg["outcomes"]["circuit_failure"]["adjudication_verdicts"]
        if not isinstance(data, dict) or data.get("kind") not in SHEETS:
            return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that page was not recognised"})
        sheet, key = SHEETS[data["kind"]]
        with self.server.lock:
            rows = read_sheet(self.out / sheet)
            n = data.get("n")
            if type(n) is not int or n not in rows:
                return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that circuit was not recognised"})
            if "verdict" in data and data["verdict"] not in allowed:
                return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that answer was not recognised"})
            if "note" in data and not isinstance(data["note"], str):
                return self.reply(HTTPStatus.BAD_REQUEST, {"error": "that note was not recognised"})
            rows[n] = [data.get("verdict", rows[n][0]), data.get("note", rows[n][1])]
            try:
                write_sheet(self.out / sheet, key, rows)
            except PermissionError:
                return self.reply(HTTPStatus.CONFLICT, {
                    "error": f"{sheet} is open in another program, probably Excel. Close it, then click again"})
            if data["kind"] == "sample":
                check(self.cfg, self.out, sample_size(self.cfg))
        self.reply(HTTPStatus.OK, {})


class LocalServer(ThreadingHTTPServer):
    """Threads, not one request at a time: browsers open spare connections
    that a single-threaded server would wait on. Writes take `lock`."""

    # On Windows SO_REUSEADDR lets a second server bind a port that is in
    # use, so a second double-click would start a second server instead of
    # finding the first.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, port: int, handler: Any):
        super().__init__(("127.0.0.1", port), handler)
        self.lock = threading.Lock()


def make_server(cfg: dict[str, Any], out: Path, port: int) -> LocalServer:
    return LocalServer(port, partial(Handler, cfg=cfg, out=out))


def running(port: int) -> bool:
    """Whether this app already answers on `port`."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=PING_SECONDS) as r:
            return json.load(r).get("app") == APP
    except (OSError, ValueError):
        return False


def serve(cfg: dict[str, Any], out: Path, port: int) -> None:
    if not (out / "index.html").exists():
        raise SystemExit(f"No circuit pages in {out}. Run setup first (adjudicate.bat or adjudicate.sh).")
    url = f"http://127.0.0.1:{port}/index.html"
    try:
        server = make_server(cfg, out, port)
    except OSError:
        if not running(port):
            raise SystemExit(f"Another program is using port {port}, so adjudication cannot start. "
                             "Tell the study team.")
        print("Adjudication is already open. Opening it in your browser again.")
        webbrowser.open(url)
        return
    print("Adjudication is open in your web browser.\n\n"
          "Keep this window open while you work.\n"
          "Close it when you stop: every click is already saved.\n\n"
          f"If the browser did not open, go to {url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main() -> None:
    cfg = config.load()
    out = config.path(cfg, "adjudication_dir")
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in ("build", "export"):
        con = duckdb.connect(str(config.path(cfg, "duckdb")), read_only=True)
        (build if command == "build" else export)(con, cfg, out)
        con.close()
    elif command == "serve":
        serve(cfg, out, cfg["outcomes"]["circuit_failure"]["adjudication_port"])
    elif command == "check":
        check(cfg, out, sample_size(cfg))
    else:
        raise SystemExit("usage: python -m crrt.adjudication_viewer build|export|serve|check")


if __name__ == "__main__":
    main()
