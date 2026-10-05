"""The coagulation/hematology and chemistry features (sql/lab_features.sql)
on hand-built circuits.

Each test draws a few results whose correct features are obvious by
construction. No MIMIC data is read. Times are hours after an arbitrary
origin; the lookback and the bounds come from config/config.yaml, so
scenarios are written relative to them. The rules are the calcium labs'
in anticoag_features; these tests hold lab_features to them.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.features import LAB_FEATURES_SQL, bind_lab_features, build_lab_features

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
F = CFG["features"]
LAB = {name: itemid for group in F["lab_groups"].values() for name, itemid in group.items()}
BOUNDS = F["plausibility_bounds"]
LOOKBACK = F["lab_lookback_hours"]
STEP = CFG["prediction"]["step_hours"]
ORIGIN = datetime(2150, 1, 1)

# An in-bound platelet count, used throughout.
PLT = sum(BOUNDS[LAB["platelets"]]) / 2


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class Chart:
    """Synthetic crrt_circuits, circuit_failure_labels and labevents rows.
    Every circuit is on subject 1 unless given another."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.labs: list[tuple] = []

    def circuit(self, cid: int, start_h: float, end_h: float, subject: int = 1):
        self.circuits.append((cid, subject, start_h, end_h))
        return self

    def lab(self, name: str, h: float, v: float, stored_h: float | None = None, subject: int = 1):
        self.labs.append((subject, at(h), at(h if stored_h is None else stored_h), LAB[name], v))
        return self

    def run(self, cfg=CFG) -> dict[tuple[int, float], dict]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, subject_id INTEGER, "
                    "circuit_start TIMESTAMP, circuit_end TIMESTAMP)")
        con.execute("CREATE TABLE circuit_failure_labels (circuit_id INTEGER, pred_time TIMESTAMP)")
        con.execute("CREATE TABLE labevents (subject_id INTEGER, charttime TIMESTAMP, "
                    "storetime TIMESTAMP, itemid INTEGER, valuenum DOUBLE)")
        for cid, subject, start_h, end_h in self.circuits:
            con.execute("INSERT INTO crrt_circuits VALUES (?, ?, ?, ?)",
                        [cid, subject, at(start_h), at(end_h)])
            h = start_h
            while h <= end_h:
                con.execute("INSERT INTO circuit_failure_labels VALUES (?, ?)", [cid, at(h)])
                h += STEP
        if self.labs:
            con.executemany("INSERT INTO labevents VALUES (?, ?, ?, ?, ?)", self.labs)
        build_lab_features(con, cfg)
        cur = con.execute("SELECT * FROM lab_features")
        cols = [d[0] for d in cur.description]
        out = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out[(r["circuit_id"], (r["pred_time"] - ORIGIN) / timedelta(hours=1))] = r
        return out


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    used = set(re.findall(r"getvariable\('(\w+)'\)", LAB_FEATURES_SQL.read_text()))
    con = duckdb.connect()
    bind_lab_features(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Allowed: the unit
    INTERVAL '1 hour', and the 2, [1] and [2] that pick a lab's last and
    previous result."""
    code = "\n".join(line.split("--")[0] for line in LAB_FEATURES_SQL.read_text().splitlines())
    for allowed in ("INTERVAL '1 hour'", ", 2)", "[1]", "[2]"):
        code = code.replace(allowed, "")
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


# ── Rows and columns ──────────────────────────────────────────────────────


def test_one_row_per_prediction_row_and_every_column_without_data():
    rows = Chart().circuit(1, 0, 4).run()
    assert sorted(rows) == [(1, k * STEP) for k in range(int(4 / STEP) + 1)]
    assert set(rows[(1, 4)]) == {"circuit_id", "pred_time"} | {
        f"{s}_{c}" for s in LAB for c in ("last", "hours_since_last", "delta", "delta_hours")}
    assert all(v is None for k, v in rows[(1, 4)].items() if k not in ("circuit_id", "pred_time"))


def test_every_lab_is_read_from_its_own_itemid():
    c = Chart().circuit(1, 0, 2)
    for k, name in enumerate(LAB):
        low, high = BOUNDS[LAB[name]]
        c.lab(name, 1, low + (high - low) * (k + 1) / (len(LAB) + 1))
    row = c.run()[(1, 2)]
    for k, name in enumerate(LAB):
        low, high = BOUNDS[LAB[name]]
        assert row[f"{name}_last"] == pytest.approx(low + (high - low) * (k + 1) / (len(LAB) + 1))


# ── Availability ──────────────────────────────────────────────────────────


def test_lab_counts_only_once_stored():
    rows = Chart().circuit(1, 0, 4).lab("platelets", 1, PLT, stored_h=2.5).run()
    assert rows[(1, 2)]["platelets_last"] is None
    assert rows[(1, 3)]["platelets_last"] == PLT
    assert rows[(1, 3)]["platelets_hours_since_last"] == 2


def test_lab_before_the_circuit_counts_back_to_the_lookback():
    """A lab is the patient's, not the filter's: a draw before circuit_start
    counts, back to exactly the lookback and no further."""
    rows = Chart().circuit(1, LOOKBACK + 1, LOOKBACK + 3).lab("platelets", 1, PLT).run()
    assert rows[(1, LOOKBACK + 1)]["platelets_last"] == PLT
    assert rows[(1, LOOKBACK + 1)]["platelets_hours_since_last"] == LOOKBACK
    assert rows[(1, LOOKBACK + 2)]["platelets_last"] is None


def test_lab_counts_on_the_next_circuit_of_the_patient():
    rows = (Chart().circuit(1, 0, 2).circuit(2, 3, 5)
            .lab("platelets", 1, PLT).run())
    assert rows[(2, 3)]["platelets_last"] == PLT


def test_other_patients_labs_never_count():
    rows = Chart().circuit(1, 0, 4).lab("platelets", 1, PLT, subject=2).run()
    assert rows[(1, 4)]["platelets_last"] is None


def test_latest_draw_wins_and_hours_since_is_from_its_charttime():
    rows = (Chart().circuit(1, 0, 6)
            .lab("platelets", 1, PLT - 10).lab("platelets", 3, PLT + 10).run())
    assert rows[(1, 2)]["platelets_last"] == PLT - 10
    assert rows[(1, 6)]["platelets_last"] == PLT + 10
    assert rows[(1, 6)]["platelets_hours_since_last"] == 3


def test_an_earlier_draw_stored_later_does_not_replace_the_latest():
    rows = (Chart().circuit(1, 0, 6)
            .lab("platelets", 1, PLT - 10, stored_h=4.5)
            .lab("platelets", 2, PLT + 10).run())
    assert rows[(1, 5)]["platelets_last"] == PLT + 10


# ── Change from the previous result ───────────────────────────────────────


def test_delta_is_last_minus_previous_with_the_hours_between():
    rows = (Chart().circuit(1, 0, 6)
            .lab("platelets", 1, PLT).lab("platelets", 4, PLT - 30).run())
    assert rows[(1, 3)]["platelets_delta"] is None
    assert rows[(1, 3)]["platelets_delta_hours"] is None
    assert rows[(1, 6)]["platelets_delta"] == -30
    assert rows[(1, 6)]["platelets_delta_hours"] == 3


def test_delta_needs_the_previous_result_inside_the_lookback():
    rows = (Chart().circuit(1, LOOKBACK, LOOKBACK + 3)
            .lab("platelets", 1, PLT).lab("platelets", LOOKBACK, PLT - 30).run())
    assert rows[(1, LOOKBACK + 1)]["platelets_delta"] == -30
    assert rows[(1, LOOKBACK + 2)]["platelets_delta"] is None
    assert rows[(1, LOOKBACK + 2)]["platelets_last"] == PLT - 30


def test_delta_skips_a_result_not_yet_stored():
    """The previous result is the one before the last among results already
    stored, so a draw still in the lab is skipped, not waited for."""
    rows = (Chart().circuit(1, 0, 6)
            .lab("platelets", 1, PLT)
            .lab("platelets", 2, PLT - 10, stored_h=5.5)
            .lab("platelets", 3, PLT - 30).run())
    assert rows[(1, 4)]["platelets_delta"] == -30
    assert rows[(1, 4)]["platelets_delta_hours"] == 2
    assert rows[(1, 6)]["platelets_delta"] == -20
    assert rows[(1, 6)]["platelets_delta_hours"] == 1


# ── Cleaning ──────────────────────────────────────────────────────────────


def test_out_of_bound_lab_is_missing_and_bounds_are_inclusive():
    low, high = BOUNDS[LAB["glucose"]]
    rows = (Chart().circuit(1, 0, 6)
            .lab("glucose", 1, low).lab("glucose", 2, low - 1)
            .lab("glucose", 3, high).lab("glucose", 4, high + 1).run())
    assert rows[(1, 2)]["glucose_last"] == low
    assert rows[(1, 3)]["glucose_last"] == high
    assert rows[(1, 6)]["glucose_last"] == high


def test_results_at_one_charttime_are_averaged_and_wait_for_the_later():
    rows = (Chart().circuit(1, 0, 4)
            .lab("potassium", 1, 4.0)
            .lab("potassium", 1, 5.0, stored_h=2.5).run())
    assert rows[(1, 2)]["potassium_last"] is None
    assert rows[(1, 3)]["potassium_last"] == pytest.approx(4.5)
