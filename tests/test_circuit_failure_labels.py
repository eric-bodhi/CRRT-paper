"""The circuit-failure prediction rows (sql/circuit_failure_labels.sql) on
hand-built circuits.

Each test builds one or more circuits whose correct rows and labels are
obvious by construction. No MIMIC data is read. Times are hours after an
arbitrary origin; the horizon, warm-up, blanking and windows come from
config/config.yaml, so scenarios are written relative to them.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.outcomes import CIRCUIT_FAILURE_SQL, bind_circuit_failure, build

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
P = CFG["prediction"]
O = CFG["outcomes"]["circuit_failure"]
C = CFG["circuits"]
ORIGIN = datetime(2150, 1, 1)
H = P["horizon_hours"]
WARMUP = P["warmup_hours"]
BLANK_H = P["blanking_minutes"] / 60
STEP = P["step_hours"]
GAP = CFG["sessionization"]["gap_hours"]
BLOOD_FLOW = C["machine_itemids"][0]
INTEGRITY = C["system_integrity_itemid"]


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class Circuits:
    """Synthetic crrt_circuits, crrt_cohort and chartevents rows."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.chart: list[tuple] = []

    def circuit(self, cid: int, end_h: float, cls: str, included: bool = True,
                charting: tuple[tuple[float, float], ...] | None = None):
        """Circuit `cid` (its own stay and patient) from hour 0 to `end_h`,
        with hourly blood flow over `charting` runs (default: the whole
        circuit)."""
        self.circuits.append((cid, end_h, cls, included))
        for start, stop in charting or ((0, end_h),):
            h = start
            while h <= stop:
                self.chart.append((cid, at(h), BLOOD_FLOW, None, 150.0))
                h += 1
        return self

    def integrity(self, cid: int, h: float, value: str):
        self.chart.append((cid, at(h), INTEGRITY, value, None))
        return self

    def run(self, cfg=CFG) -> dict[int, list[dict]]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, subject_id INTEGER, "
                    "stay_id INTEGER, circuit_start TIMESTAMP, circuit_end TIMESTAMP, "
                    "termination_class VARCHAR)")
        con.execute("CREATE TABLE crrt_cohort (circuit_id INTEGER, included BOOLEAN)")
        con.execute("CREATE TABLE chartevents (stay_id INTEGER, charttime TIMESTAMP, "
                    "itemid INTEGER, value VARCHAR, valuenum DOUBLE)")
        for cid, end_h, cls, included in self.circuits:
            con.execute("INSERT INTO crrt_circuits VALUES (?, ?, ?, ?, ?, ?)",
                        [cid, cid, cid, ORIGIN, at(end_h), cls])
            con.execute("INSERT INTO crrt_cohort VALUES (?, ?)", [cid, included])
        if self.chart:
            con.executemany("INSERT INTO chartevents VALUES (?, ?, ?, ?, ?)", self.chart)
        build(con, cfg)
        cur = con.execute("SELECT * FROM circuit_failure_labels ORDER BY circuit_id, pred_time")
        cols = [d[0] for d in cur.description]
        out: dict[int, list[dict]] = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out.setdefault(r["circuit_id"], []).append(r)
        return out


def by_hour(rows: list[dict]) -> dict[float, dict]:
    return {r["hours_since_start"]: r for r in rows}


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    """An unset getvariable() is NULL, and a NULL horizon makes every row a
    non-event instead of failing."""
    used = set(re.findall(r"getvariable\('(\w+)'\)", CIRCUIT_FAILURE_SQL.read_text()))
    con = duckdb.connect()
    bind_circuit_failure(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Code may only use
    the unit INTERVAL '1 hour'."""
    code = "\n".join(line.split("--")[0] for line in CIRCUIT_FAILURE_SQL.read_text().splitlines())
    code = code.replace("INTERVAL '1 hour'", "")
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


# ── Rows ──────────────────────────────────────────────────────────────────


def test_one_row_per_step_and_only_included_circuits():
    rows = Circuits().circuit(1, 10, "crrt_ended").circuit(2, 10, "crrt_ended", included=False).run()
    assert set(rows) == {1}
    assert [r["hours_since_start"] for r in rows[1]] == [k * STEP for k in range(int(10 / STEP) + 1)]


def test_warmup_rows_are_not_scored():
    rows = by_hour(Circuits().circuit(1, 20, "crrt_ended").run()[1])
    for h, r in rows.items():
        if h < WARMUP:
            assert r["not_scored_reason"] == "warmup" and r["label"] is None
    assert rows[WARMUP]["scored"]


# ── Labels ────────────────────────────────────────────────────────────────


def test_clotted_circuit_is_positive_within_the_horizon_of_its_end():
    end = 30
    rows = by_hour(Circuits().circuit(1, end, "clotted").run()[1])
    for h, r in rows.items():
        if h < WARMUP:
            continue
        if h + BLANK_H >= end:
            assert r["not_scored_reason"] == "blanking"
        elif end - h <= H:
            assert r["label"] is True, h
        else:
            assert r["label"] is False, h


def test_clot_charted_before_the_machine_stops_ends_the_filter_there():
    """113 clotted circuits chart `Clotted` more than 30 min before the last
    machine charting (2026-10-03 entry). Rows after it predict the present."""
    before, _ = C["windows_hours"]["clotted_at_end"]
    end = 30
    clot = end - before + 0.5
    assert end - clot > BLANK_H
    rows = Circuits().circuit(1, end, "clotted").integrity(1, clot, "Clotted").run()[1]
    assert rows[0]["end_time"] == at(clot)
    for r in by_hour(rows).values():
        if r["hours_since_start"] + BLANK_H >= clot:
            assert r["not_scored_reason"] == "blanking"


def test_documenting_entry_outside_the_class_window_is_ignored():
    before, _ = C["windows_hours"]["clotted_at_end"]
    end = 30
    rows = Circuits().circuit(1, end, "clotted").integrity(1, end - before - 2, "Clotted").run()[1]
    assert rows[0]["end_time"] == at(end)


def test_non_event_end_is_negative_and_blanked_the_same_way():
    """Blanking is applied at every end, so scoring cannot depend on the label."""
    end = 30
    rows = by_hour(Circuits().circuit(1, end, "reached_limit").run()[1])
    for h, r in rows.items():
        if h >= WARMUP:
            if h + BLANK_H >= end:
                assert r["not_scored_reason"] == "blanking"
            else:
                assert r["label"] is False


def test_death_censors_rows_whose_horizon_contains_it():
    end = 30
    rows = by_hour(Circuits().circuit(1, end, "death").run()[1])
    for h, r in rows.items():
        if not r["scored"]:
            continue
        if end - h <= H:
            assert r["label"] is None and r["censor_reason"] == "competing_risk"
        else:
            assert r["label"] is False and r["censor_reason"] is None


def test_unclear_handling():
    primary = Circuits().circuit(1, 30, "undocumented").run()[1]
    assert {r["label"] for r in primary if r["scored"]} == {False}

    cfg = {**CFG, "outcomes": {**CFG["outcomes"], "circuit_failure": {
        **O, "unclear_handling_primary": O["unclear_handling_sensitivity"]}}}
    excluded = Circuits().circuit(1, 30, "undocumented").run(cfg)[1]
    assert {r["not_scored_reason"] for r in excluded} == {"unclear_excluded"}


def test_clots_increasing_is_not_an_event_in_the_primary():
    rows = Circuits().circuit(1, 30, "clots_increasing").run()[1]
    assert {r["label"] for r in rows if r["scored"]} == {False}


# ── Downtime ──────────────────────────────────────────────────────────────


def test_rows_in_a_pause_longer_than_the_gap_are_not_scored():
    """Two runs on one filter with a pause: rows more than `gap_hours` after
    the last machine charting are downtime."""
    pause_from, pause_to = 10, 10 + GAP + 3
    rows = by_hour(Circuits().circuit(1, 30, "crrt_ended",
                                      charting=((0, pause_from), (pause_to, 30))).run()[1])
    for h, r in rows.items():
        if pause_from + GAP < h < pause_to:
            assert r["not_scored_reason"] == "downtime", h
        elif WARMUP <= h <= pause_from + GAP:
            assert r["scored"], h
    assert rows[pause_to]["scored"]
