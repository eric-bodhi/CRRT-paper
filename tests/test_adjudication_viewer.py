"""The adjudication viewer (crrt.adjudication_viewer) on hand-built circuits.

Every circuit runs `DUR` hours with hourly pressures, one System Integrity
entry after its end, rows just outside its window, and one calcium result.
Identifiers are large and distinctive so a leak into a page is detectable.
No MIMIC data is read. Window lengths, strata and verdicts come from
config/config.yaml. The app's server runs on a free port on 127.0.0.1.
"""

import copy
import csv
import json
import re
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta

import pytest

from crrt import adjudication_viewer, config
from crrt.adjudication import draw, fingerprint
from crrt.adjudication_viewer import (PRACTICE_SHEET, SHEET, build, check, clock, export, make_server,
                                      package_name, send_file)

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
O = CFG["outcomes"]["circuit_failure"]
STRATA = O["adjudication_strata"]
VIEW = O["adjudication_view_hours"]
N_SAMPLE = sum(s["circuits"] for s in STRATA.values())
F = CFG["features"]
PRESSURE = F["machine_signals"]["filter_pressure"]
INTEGRITY = CFG["circuits"]["system_integrity_itemid"]
ICA = F["calcium_labs"]["ionized_calcium"]
ORIGIN = datetime(2150, 1, 1)
DUR = 30
SUBJECT, STAY, HADM, CIRCUIT = 7_100_000, 7_200_000, 7_300_000, 7_400_000


def world() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE crrt_circuits (circuit_id BIGINT, subject_id INTEGER, "
                "hadm_id INTEGER, stay_id INTEGER, circuit_start TIMESTAMP, "
                "circuit_end TIMESTAMP, duration_hours DOUBLE, termination_class VARCHAR)")
    con.execute("CREATE TABLE crrt_cohort (circuit_id BIGINT, included BOOLEAN)")
    con.execute("CREATE TABLE chartevents (stay_id INTEGER, charttime TIMESTAMP, "
                "itemid INTEGER, value VARCHAR, valuenum DOUBLE, valueuom VARCHAR)")
    con.execute("CREATE TABLE labevents (subject_id INTEGER, charttime TIMESTAMP, "
                "itemid INTEGER, valuenum DOUBLE, valueuom VARCHAR)")
    con.execute("CREATE TABLE admissions (hadm_id INTEGER, deathtime TIMESTAMP)")
    con.execute("CREATE TABLE icustays (stay_id INTEGER, outtime TIMESTAMP)")
    circuits, chart, labs, adm, icu = [], [], [], [], []
    k = 0
    for s in STRATA.values():
        for j in range(s["circuits"] + O["adjudication_practice_per_stratum"] + 1):
            k += 1
            start = ORIGIN + timedelta(days=4 * k)
            end = start + timedelta(hours=DUR)
            circuits.append((CIRCUIT + k, SUBJECT + k, HADM + k, STAY + k, start, end,
                             float(DUR), s["classes"][j % len(s["classes"])]))
            for h in range(DUR + 1):
                chart.append((STAY + k, start + timedelta(hours=h), PRESSURE, None, 100.0 + h, "mmHg"))
            # Just outside the window on both sides: never shown.
            chart.append((STAY + k, start - timedelta(hours=1), PRESSURE, None, 999.0, "mmHg"))
            chart.append((STAY + k, end + timedelta(hours=VIEW["after_end"] + 1), PRESSURE, None, 888.0, "mmHg"))
            chart.append((STAY + k, end + timedelta(hours=1), INTEGRITY, "New Filter", None, None))
            labs.append((SUBJECT + k, end - timedelta(hours=2, minutes=30), ICA, 1.11, "mmol/L"))
            # Death inside the window for even circuits, far outside for odd.
            adm.append((HADM + k, end + timedelta(hours=2 if k % 2 == 0 else VIEW["after_end"] + 50)))
            icu.append((STAY + k, None))
    for name, rows in (("crrt_circuits", circuits), ("chartevents", chart), ("labevents", labs),
                       ("admissions", adm), ("icustays", icu)):
        marks = ", ".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO {name} VALUES ({marks})", rows)
    con.executemany("INSERT INTO crrt_cohort VALUES (?, true)", [(c[0],) for c in circuits])
    draw(con, CFG)
    return con


@pytest.fixture
def built(tmp_path):
    con = world()
    cfg = copy.deepcopy(CFG)
    cfg["outcomes"]["circuit_failure"]["adjudication_sample_sha256"] = fingerprint(con)
    build(con, cfg, tmp_path)
    return con, cfg, tmp_path


def pages(out):
    return sorted(out.glob("circuit_*.html")) + sorted((out / "practice").glob("practice_*.html"))


def test_build_refuses_a_sample_that_is_not_the_frozen_one(tmp_path):
    with pytest.raises(SystemExit, match="does not match"):
        build(world(), CFG, tmp_path)


def test_one_page_per_sampled_and_practice_circuit(built):
    _, _, out = built
    practice = O["adjudication_practice_per_stratum"] * len(STRATA)
    assert len(list(out.glob("circuit_*.html"))) == N_SAMPLE
    assert len(list((out / "practice").glob("practice_*.html"))) == practice
    assert (out / "index.html").exists() and (out / "practice" / "index.html").exists()


def test_no_page_reveals_identifiers_dates_strata_or_classes(built):
    _, _, out = built
    hidden = [str(SUBJECT)[:3] + r"\d{4}", str(STAY)[:3] + r"\d{4}", str(HADM)[:3] + r"\d{4}",
              str(CIRCUIT)[:3] + r"\d{4}", r"\b21[56]\d-\d\d-\d\d", "stratum", "termination_class"]
    # Case-sensitive whole words: the charted value "Clotted" may appear, the
    # class name "clotted" may not.
    hidden += [rf"\b{re.escape(name)}\b" for name in STRATA]
    hidden += [rf"\b{re.escape(c)}\b" for s in STRATA.values() for c in s["classes"]]
    for page in pages(out) + [out / "index.html"]:
        text = page.read_text()
        for pattern in hidden:
            assert not re.search(pattern, text), f"{pattern} in {page.name}"


def test_rows_outside_the_window_are_not_shown(built):
    _, _, out = built
    for page in pages(out):
        text = page.read_text()
        assert "999" not in text and "888" not in text


def test_times_are_relative_to_the_circuit_end(built):
    _, _, out = built
    text = (out / "circuit_001.html").read_text()
    assert f"<td>{clock(-DUR)}</td>" in text      # the first pressure, at the start
    assert "<td>0:00</td>" in text                 # the last, at the end
    assert '<tr class="after"><td>+1:00</td>' in text and "New Filter" in text
    assert "<td>−2:30</td>" in text                # calcium, matched on the patient


def test_death_is_listed_only_inside_the_window(built):
    _, _, out = built
    texts = [p.read_text() for p in out.glob("circuit_*.html")]
    with_death = sum("Death at +2:00" in t for t in texts)
    assert 0 < with_death < len(texts)
    assert all("Death at +2:00" in t or "No death or ICU discharge" in t for t in texts)


def test_the_verdict_sheet_is_never_overwritten(built):
    con, cfg, out = built
    rows = list(csv.reader((out / SHEET).open()))
    assert rows[0] == ["review_order", "verdict", "note"]
    assert [int(r[0]) for r in rows[1:]] == list(range(1, N_SAMPLE + 1))
    rows[1][1] = O["adjudication_verdicts"][0]
    csv.writer((out / SHEET).open("w", newline="")).writerows(rows)
    build(con, cfg, out)
    assert list(csv.reader((out / SHEET).open()))[1][1] == O["adjudication_verdicts"][0]


def fill(out, verdict=None, note="charted 250 at -1:00", skip=None):
    v = verdict or O["adjudication_verdicts"][0]
    with (out / SHEET).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["review_order", "verdict", "note"])
        w.writerows([[k, "" if k == skip else v, note] for k in range(1, N_SAMPLE + 1)])


def test_check_rejects_a_verdict_outside_the_list(built):
    _, cfg, out = built
    fill(out, verdict="clot")
    with pytest.raises(ValueError, match="not one of"):
        check(cfg, out, N_SAMPLE)


def test_check_rejects_a_missing_circuit(built):
    _, cfg, out = built
    fill(out)
    rows = list(csv.reader((out / SHEET).open()))[:-1]
    csv.writer((out / SHEET).open("w", newline="")).writerows(rows)
    with pytest.raises(ValueError, match="each once"):
        check(cfg, out, N_SAMPLE)


def test_an_unfinished_sheet_writes_nothing_to_send(built):
    _, cfg, out = built
    fill(out, skip=3)
    assert check(cfg, out, N_SAMPLE) is None
    assert not list(out.glob("verdicts_send_*"))


def test_the_file_to_send_has_order_and_verdict_only(built):
    _, cfg, out = built
    fill(out)
    send = check(cfg, out, N_SAMPLE)
    rows = list(csv.reader(send.open()))
    assert rows[0] == ["review_order", "verdict"]
    assert all(len(r) == 2 for r in rows)
    assert "250" not in send.read_text()


def test_the_practice_sheet_is_made_and_kept_apart(built):
    con, cfg, out = built
    rows = list(csv.reader((out / PRACTICE_SHEET).open()))
    practice = O["adjudication_practice_per_stratum"] * len(STRATA)
    assert rows[0] == ["practice_order", "verdict", "note"]
    assert [int(r[0]) for r in rows[1:]] == list(range(1, practice + 1))


def test_pages_carry_the_buttons_the_warning_and_the_script(built):
    _, _, out = built
    for page in pages(out):
        text = page.read_text()
        for v in O["adjudication_verdicts"]:
            assert f'data-verdict="{v}"' in text, f"{v} button missing in {page.name}"
        assert 'id="banner"' in text and "double-click <b>Adjudicate</b>" in text
        assert "<script>" in text and 'id="note"' in text
    index = (out / "index.html").read_text()
    assert "Continue where I left off" in index and 'id="reveal"' in index
    assert "Continue where I left off" in (out / "practice" / "index.html").read_text()


def test_the_flowsheet_fits_the_page(built):
    _, _, out = built
    text = (out / "circuit_001.html").read_text()
    assert '<table class="flow"><colgroup><col class="t">' in text


@pytest.fixture
def app(built):
    _, cfg, out = built
    srv = make_server(cfg, out, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, cfg, out
    srv.shutdown()
    srv.server_close()


def call(srv, path, data=None, **headers):
    """(status, body) of one request, as the page makes it unless `headers`
    say otherwise."""
    port = srv.server_address[1]
    sent = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"} if data is not None else {}
    sent |= {k.replace("_", "-"): v for k, v in headers.items()}
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=sent)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def sheet(out, name=SHEET):
    return {int(r[0]): r[1:] for r in list(csv.reader((out / name).open()))[1:]}


def test_the_app_serves_the_pages(app):
    srv, _, _ = app
    assert call(srv, "/")[0] == 200
    status, body = call(srv, "/circuit_001.html")
    assert status == 200 and b'data-verdict="' in body


def test_a_click_is_saved_and_comes_back(app):
    srv, _, out = app
    v = O["adjudication_verdicts"][0]
    assert call(srv, "/api/verdict", {"kind": "sample", "n": 3, "verdict": v})[0] == 200
    assert sheet(out)[3] == [v, ""]
    assert all(row == ["", ""] for n, row in sheet(out).items() if n != 3)
    status, body = call(srv, "/api/verdicts")
    got = json.loads(body)
    assert status == 200 and got["sample"]["3"] == {"verdict": v, "note": ""} and got["send"] is None


def test_a_note_and_a_changed_verdict_keep_each_other(app):
    srv, _, out = app
    first, second = O["adjudication_verdicts"][:2]
    call(srv, "/api/verdict", {"kind": "sample", "n": 1, "verdict": first})
    call(srv, "/api/verdict", {"kind": "sample", "n": 1, "note": "pressures odd, ask"})
    call(srv, "/api/verdict", {"kind": "sample", "n": 1, "verdict": second})
    assert sheet(out)[1] == [second, "pressures odd, ask"]


@pytest.mark.parametrize("data", [
    {"kind": "sample", "n": 1, "verdict": "clot"},
    {"kind": "sample", "n": N_SAMPLE + 1, "verdict": O["adjudication_verdicts"][0]},
    {"kind": "sample", "n": "1", "verdict": O["adjudication_verdicts"][0]},
    {"kind": "stratum", "n": 1, "verdict": O["adjudication_verdicts"][0]},
    {"kind": "sample", "n": 1, "note": 5},
])
def test_a_bad_request_is_refused_and_changes_nothing(app, data):
    srv, _, out = app
    before = (out / SHEET).read_bytes()
    assert call(srv, "/api/verdict", data)[0] == 400
    assert (out / SHEET).read_bytes() == before


def test_other_hosts_and_sites_are_refused(app):
    srv, _, out = app
    before = (out / SHEET).read_bytes()
    v = {"kind": "sample", "n": 1, "verdict": O["adjudication_verdicts"][0]}
    # DNS rebinding names another host and could read pages and verdicts.
    assert call(srv, "/index.html", Host="evil.example")[0] == 403
    assert call(srv, "/api/verdicts", Host="evil.example")[0] == 403
    # Another site's page posting a form or a fetch.
    assert call(srv, "/api/verdict", v, Origin="http://evil.example")[0] == 403
    assert call(srv, "/api/verdict", v, Content_Type="text/plain")[0] == 403
    assert (out / SHEET).read_bytes() == before


def test_practice_verdicts_go_to_their_own_sheet(app):
    srv, _, out = app
    v = O["adjudication_verdicts"][0]
    before = (out / SHEET).read_bytes()
    assert call(srv, "/api/verdict", {"kind": "practice", "n": 1, "verdict": v})[0] == 200
    assert sheet(out, PRACTICE_SHEET)[1] == [v, ""]
    assert (out / SHEET).read_bytes() == before


def test_the_last_verdict_writes_the_file_to_send(app, monkeypatch):
    srv, cfg, out = app
    fill(out, skip=N_SAMPLE)
    assert not send_file(cfg, out).exists()
    v = O["adjudication_verdicts"][-1]
    assert call(srv, "/api/verdict", {"kind": "sample", "n": N_SAMPLE, "verdict": v})[0] == 200
    rows = list(csv.reader(send_file(cfg, out).open()))
    assert rows[0] == ["review_order", "verdict"] and rows[-1] == [str(N_SAMPLE), v]
    assert json.loads(call(srv, "/api/verdicts")[1])["send"] == send_file(cfg, out).name
    shown = []
    monkeypatch.setattr(adjudication_viewer, "reveal", shown.append)
    assert call(srv, "/api/reveal", {})[0] == 200
    assert shown == [send_file(cfg, out)]


def test_a_practice_run_never_writes_the_file_to_send(app):
    srv, cfg, out = app
    for n in sheet(out, PRACTICE_SHEET):
        call(srv, "/api/verdict", {"kind": "practice", "n": n, "verdict": O["adjudication_verdicts"][0]})
    assert not send_file(cfg, out).exists()


def test_the_export_holds_every_page_and_empty_sheets_only(built, tmp_path):
    con, cfg, out = built
    fill(out)                        # this machine's own answers and notes
    send = check(cfg, out, N_SAMPLE)
    exported = tmp_path / "export" / "adjudication"
    exported.mkdir(parents=True)
    for name in (SHEET, PRACTICE_SHEET):   # as if this machine had clicked too
        (exported / name).write_bytes((out / name).read_bytes())
    package = export(con, cfg, exported)
    assert package == exported.parent / package_name(cfg)
    with zipfile.ZipFile(package) as z:
        names = set(z.namelist())
        pages = {p.relative_to(exported).as_posix() for p in exported.rglob("*.html")}
        assert len(pages) > N_SAMPLE and pages == {n for n in names if n.endswith(".html")}
        assert {SHEET, PRACTICE_SHEET} <= names and send.name not in names
        for sheet in (SHEET, PRACTICE_SHEET):
            rows = list(csv.reader(z.read(sheet).decode().splitlines()))
            assert len(rows) > 1 and all(r[1:] == ["", ""] for r in rows[1:])
        assert not any(b"charted 250" in z.read(n) for n in names)


def test_the_export_refuses_a_sample_that_is_not_the_frozen_one(tmp_path):
    with pytest.raises(SystemExit, match="does not match"):
        export(world(), CFG, tmp_path / "adjudication")
    assert not list(tmp_path.glob("*.zip"))
