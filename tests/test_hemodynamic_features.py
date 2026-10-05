"""The hemodynamic features (sql/hemodynamic_features.sql) on hand-built
circuits.

Each test charts a few values whose correct features are obvious by
construction. No MIMIC data is read. Times are hours after an arbitrary
origin; windows, bounds and the lookback come from config/config.yaml, so
scenarios are written relative to them. The window statistics are
machine_features' and the lactate columns lab_features', both tested in
depth there; these tests cover what differs: vitals are the stay's, not the
circuit's, several items make one signal, and temperature changes unit.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.features import (HEMODYNAMIC_FEATURES_SQL, bind_hemodynamic_features,
                           build_hemodynamic_features)

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
F = CFG["features"]
SIG = F["hemodynamic_signals"]
LAB = F["hemodynamic_labs"]
BOUNDS = F["plausibility_bounds"]
WINDOWS = F["window_hours"]
SHORT, LONG = min(WINDOWS), max(WINDOWS)
STEP = CFG["prediction"]["step_hours"]
LOOKBACK = F["lab_lookback_hours"]
ORIGIN = datetime(2150, 1, 1)

CELSIUS, FAHRENHEIT = (next(i for i in SIG["temperature"] if (i in F["fahrenheit_itemids"]) == f)
                       for f in (False, True))


def to_fahrenheit(c: float) -> float:
    return c * F["fahrenheit_per_celsius"] + F["fahrenheit_freezing_point"]


# In-bound values used throughout.
MAP = sum(BOUNDS[SIG["map"][0]]) / 2
LACTATE = sum(BOUNDS[LAB["lactate"]]) / 2


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class Chart:
    """Synthetic crrt_circuits, circuit_failure_labels, chartevents and
    labevents rows. Every circuit is on stay 1 of subject 1 unless given
    another. A vital is charted on the signal's first item unless given
    one."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.chart: list[tuple] = []
        self.labs: list[tuple] = []

    def circuit(self, cid: int, start_h: float, end_h: float, stay: int = 1, subject: int = 1):
        self.circuits.append((cid, subject, stay, start_h, end_h))
        return self

    def vital(self, name: str, h: float, v: float, stored_h: float | None = None,
              stay: int = 1, itemid: int | None = None):
        self.chart.append((stay, at(h), at(h if stored_h is None else stored_h),
                           itemid or SIG[name][0], v))
        return self

    def lab(self, name: str, h: float, v: float, stored_h: float | None = None, subject: int = 1):
        self.labs.append((subject, at(h), at(h if stored_h is None else stored_h), LAB[name], v))
        return self

    def run(self, cfg=CFG) -> dict[tuple[int, float], dict]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, subject_id INTEGER, "
                    "stay_id INTEGER, circuit_start TIMESTAMP, circuit_end TIMESTAMP)")
        con.execute("CREATE TABLE circuit_failure_labels (circuit_id INTEGER, pred_time TIMESTAMP)")
        con.execute("CREATE TABLE chartevents (stay_id INTEGER, charttime TIMESTAMP, "
                    "storetime TIMESTAMP, itemid INTEGER, valuenum DOUBLE)")
        con.execute("CREATE TABLE labevents (subject_id INTEGER, charttime TIMESTAMP, "
                    "storetime TIMESTAMP, itemid INTEGER, valuenum DOUBLE)")
        for cid, subject, stay, start_h, end_h in self.circuits:
            con.execute("INSERT INTO crrt_circuits VALUES (?, ?, ?, ?, ?)",
                        [cid, subject, stay, at(start_h), at(end_h)])
            h = start_h
            while h <= end_h:
                con.execute("INSERT INTO circuit_failure_labels VALUES (?, ?)", [cid, at(h)])
                h += STEP
        if self.chart:
            con.executemany("INSERT INTO chartevents VALUES (?, ?, ?, ?, ?)", self.chart)
        if self.labs:
            con.executemany("INSERT INTO labevents VALUES (?, ?, ?, ?, ?)", self.labs)
        build_hemodynamic_features(con, cfg)
        cur = con.execute("SELECT * FROM hemodynamic_features")
        cols = [d[0] for d in cur.description]
        out = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out[(r["circuit_id"], (r["pred_time"] - ORIGIN) / timedelta(hours=1))] = r
        return out


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    used = set(re.findall(r"getvariable\('(\w+)'\)", HEMODYNAMIC_FEATURES_SQL.read_text()))
    con = duckdb.connect()
    bind_hemodynamic_features(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Allowed: the unit
    INTERVAL '1 hour', a bare 0 (an empty window's count), and the 2, [1]
    and [2] that pick a lab's last and previous result."""
    code = "\n".join(line.split("--")[0]
                     for line in HEMODYNAMIC_FEATURES_SQL.read_text().splitlines())
    for allowed in ("INTERVAL '1 hour'", ", 2)", "[1]", "[2]"):
        code = code.replace(allowed, "")
    assert not re.findall(r"\b(?!0(?![.\d]))\d+(?:\.\d+)?\b", code)


def test_every_item_has_a_bound():
    for itemid in [i for items in SIG.values() for i in items] + list(LAB.values()):
        assert itemid in BOUNDS


# ── Rows and columns ──────────────────────────────────────────────────────


def test_one_row_per_prediction_row_and_every_column_without_data():
    rows = Chart().circuit(1, 0, 4).run()
    assert sorted(rows) == [(1, k * STEP) for k in range(int(4 / STEP) + 1)]
    row = rows[(1, 4)]
    stats = ("n", "mean", "min", "max", "slope", "var")
    assert set(row) == (
        {"circuit_id", "pred_time"}
        | {f"{s}_{c}" for s in [*SIG, *LAB] for c in ("last", "hours_since_last")}
        | {f"{s}_{w}h_{c}" for s in SIG for w in WINDOWS for c in stats}
        | {f"{s}_{c}" for s in LAB for c in ("delta", "delta_hours")})
    for s in SIG:
        for w in WINDOWS:
            assert row[f"{s}_{w}h_n"] == 0
    assert all(v is None for k, v in row.items()
               if k not in ("circuit_id", "pred_time") and not k.endswith("_n"))


# ── Vitals ────────────────────────────────────────────────────────────────


def test_vital_counts_only_once_stored():
    rows = Chart().circuit(1, 0, 4).vital("map", 1, MAP, stored_h=2.5).run()
    assert rows[(1, 2)]["map_last"] is None
    assert rows[(1, 2)][f"map_{LONG}h_n"] == 0
    assert rows[(1, 3)]["map_last"] == MAP
    assert rows[(1, 3)]["map_hours_since_last"] == 2


def test_vital_before_the_circuit_counts_back_to_the_longest_window():
    """A vital is the patient's, not the filter's: a value charted before
    circuit_start counts, back to exactly the longest window."""
    rows = Chart().circuit(1, LONG + 1, LONG + 3).vital("map", 1, MAP).run()
    assert rows[(1, LONG + 1)]["map_last"] == MAP
    assert rows[(1, LONG + 1)]["map_hours_since_last"] == LONG
    assert rows[(1, LONG + 1)][f"map_{LONG}h_n"] == 1
    assert rows[(1, LONG + 1)][f"map_{SHORT}h_n"] == 0
    assert rows[(1, LONG + 2)]["map_last"] is None


def test_vital_from_the_previous_filter_of_the_stay_counts():
    rows = Chart().circuit(1, 0, 2).circuit(2, 3, 5).vital("heart_rate", 1, 90).run()
    assert rows[(2, 3)]["heart_rate_last"] == 90


def test_other_stays_vitals_never_count():
    rows = Chart().circuit(1, 0, 4).vital("map", 1, MAP, stay=2).run()
    assert rows[(1, 4)]["map_last"] is None


def test_vital_has_window_statistics():
    c = Chart().circuit(1, 0, SHORT)
    for k in range(SHORT + 1):
        c.vital("heart_rate", k, 80 + 2 * k)
    row = c.run()[(1, SHORT)]
    assert row[f"heart_rate_{SHORT}h_n"] == SHORT + 1
    assert row[f"heart_rate_{SHORT}h_mean"] == pytest.approx(80 + SHORT)
    assert row[f"heart_rate_{SHORT}h_min"] == 80
    assert row[f"heart_rate_{SHORT}h_max"] == 80 + 2 * SHORT
    assert row[f"heart_rate_{SHORT}h_slope"] == pytest.approx(2)
    assert row["heart_rate_last"] == 80 + 2 * SHORT


def test_every_map_item_is_read():
    for itemid in SIG["map"]:
        rows = Chart().circuit(1, 0, 2).vital("map", 1, MAP, itemid=itemid).run()
        assert rows[(1, 2)]["map_last"] == MAP


def test_items_at_one_charttime_are_averaged_and_wait_for_the_later():
    arterial, *_, noninvasive = SIG["map"]
    rows = (Chart().circuit(1, 0, 4)
            .vital("map", 1, MAP - 10, itemid=arterial)
            .vital("map", 1, MAP + 20, stored_h=2.5, itemid=noninvasive).run())
    assert rows[(1, 2)]["map_last"] is None
    assert rows[(1, 3)]["map_last"] == pytest.approx(MAP + 5)
    assert rows[(1, 3)][f"map_{LONG}h_n"] == 1


def test_fahrenheit_is_put_in_celsius_before_averaging():
    rows = (Chart().circuit(1, 0, 4)
            .vital("temperature", 1, to_fahrenheit(38), itemid=FAHRENHEIT)
            .vital("temperature", 2, 36, itemid=CELSIUS)
            .vital("temperature", 2, to_fahrenheit(37), itemid=FAHRENHEIT).run())
    assert rows[(1, 1)]["temperature_last"] == pytest.approx(38)
    assert rows[(1, 4)]["temperature_last"] == pytest.approx(36.5)


def test_out_of_bound_vital_is_missing_and_bounds_are_inclusive():
    low, high = BOUNDS[SIG["heart_rate"][0]]
    rows = (Chart().circuit(1, 0, 6)
            .vital("heart_rate", 1, low).vital("heart_rate", 2, low - 1)
            .vital("heart_rate", 3, high).vital("heart_rate", 4, high + 1).run())
    assert rows[(1, 2)]["heart_rate_last"] == low
    assert rows[(1, 3)]["heart_rate_last"] == high
    assert rows[(1, 6)]["heart_rate_last"] == high
    assert rows[(1, 6)][f"heart_rate_{LONG}h_n"] == 2


def test_temperature_bound_is_in_the_items_own_unit():
    """A Celsius value charted in the Fahrenheit item (37 for 98.6) is out of
    that item's bound and missing, not read as 37 degF."""
    rows = (Chart().circuit(1, 0, 2)
            .vital("temperature", 1, 37, itemid=FAHRENHEIT).run())
    assert rows[(1, 2)]["temperature_last"] is None


# ── Lactate ───────────────────────────────────────────────────────────────


def test_lactate_has_lab_columns_and_counts_back_to_the_lookback():
    rows = (Chart().circuit(1, LOOKBACK, LOOKBACK + 3)
            .lab("lactate", 1, LACTATE).lab("lactate", LOOKBACK, LACTATE + 1, stored_h=LOOKBACK + 0.5)
            .run())
    assert rows[(1, LOOKBACK)]["lactate_last"] == LACTATE
    assert rows[(1, LOOKBACK)]["lactate_hours_since_last"] == LOOKBACK - 1
    assert rows[(1, LOOKBACK)]["lactate_delta"] is None
    assert rows[(1, LOOKBACK + 1)]["lactate_last"] == LACTATE + 1
    assert rows[(1, LOOKBACK + 1)]["lactate_delta"] == pytest.approx(1)
    assert rows[(1, LOOKBACK + 1)]["lactate_delta_hours"] == LOOKBACK - 1
    assert rows[(1, LOOKBACK + 2)]["lactate_delta"] is None


def test_out_of_bound_lactate_is_missing():
    low, high = BOUNDS[LAB["lactate"]]
    rows = (Chart().circuit(1, 0, 4)
            .lab("lactate", 1, high).lab("lactate", 2, high + 1).run())
    assert rows[(1, 4)]["lactate_last"] == high
