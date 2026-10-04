"""The machine features (sql/machine_features.sql) on hand-built circuits.

Each test charts a few values whose correct features are obvious by
construction. No MIMIC data is read. Times are hours after an arbitrary
origin; windows, bounds and the trend minimum come from config/config.yaml,
so scenarios are written relative to them.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.features import MACHINE_FEATURES_SQL, bind_machine_features, build_machine_features

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
F = CFG["features"]
SIG = F["machine_signals"]
BOUNDS = F["plausibility_bounds"]
MARGIN = F["pressure_clip_margin_mmhg"]
WINDOWS = F["window_hours"]
SHORT, LONG = min(WINDOWS), max(WINDOWS)
MIN_POINTS = F["min_points_for_trend"]
STEP = CFG["prediction"]["step_hours"]
MODE = F["crrt_mode_itemid"]
ORIGIN = datetime(2150, 1, 1)
DERIVED = ["pressure_drop", "tmp", "uf_rate", "pressure_drop_per_blood_flow", "tmp_per_uf_rate"]


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class Chart:
    """Synthetic crrt_circuits, circuit_failure_labels and chartevents rows.
    Every circuit is on stay 1 unless given another."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.chart: list[tuple] = []

    def circuit(self, cid: int, start_h: float, end_h: float, stay: int = 1):
        self.circuits.append((cid, stay, start_h, end_h))
        return self

    def value(self, name: str, h: float, v: float, stored_h: float | None = None, stay: int = 1):
        """Chart signal `name` at hour `h`, stored at `stored_h` (default: at `h`)."""
        self.chart.append((stay, at(h), at(h if stored_h is None else stored_h), SIG[name], None, v))
        return self

    def mode(self, h: float, v: str, stored_h: float | None = None, stay: int = 1):
        self.chart.append((stay, at(h), at(h if stored_h is None else stored_h), MODE, v, None))
        return self

    def run(self, cfg=CFG) -> dict[tuple[int, float], dict]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, stay_id INTEGER, "
                    "circuit_start TIMESTAMP, circuit_end TIMESTAMP)")
        con.execute("CREATE TABLE circuit_failure_labels (circuit_id INTEGER, pred_time TIMESTAMP)")
        con.execute("CREATE TABLE chartevents (stay_id INTEGER, charttime TIMESTAMP, "
                    "storetime TIMESTAMP, itemid INTEGER, value VARCHAR, valuenum DOUBLE)")
        for cid, stay, start_h, end_h in self.circuits:
            con.execute("INSERT INTO crrt_circuits VALUES (?, ?, ?, ?)", [cid, stay, at(start_h), at(end_h)])
            h = start_h
            while h <= end_h:
                con.execute("INSERT INTO circuit_failure_labels VALUES (?, ?)", [cid, at(h)])
                h += STEP
        if self.chart:
            con.executemany("INSERT INTO chartevents VALUES (?, ?, ?, ?, ?, ?)", self.chart)
        build_machine_features(con, cfg)
        cur = con.execute("SELECT * FROM machine_features")
        cols = [d[0] for d in cur.description]
        out = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out[(r["circuit_id"], (r["pred_time"] - ORIGIN) / timedelta(hours=1))] = r
        return out


def pressures(c: Chart, h: float, f: float, r: float, e: float, stored_h: float | None = None) -> Chart:
    return (c.value("filter_pressure", h, f, stored_h)
             .value("return_pressure", h, r, stored_h)
             .value("effluent_pressure", h, e, stored_h))


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    """An unset getvariable() is NULL, and a NULL bound or window silently
    empties every feature instead of failing."""
    used = set(re.findall(r"getvariable\('(\w+)'\)", MACHINE_FEATURES_SQL.read_text()))
    con = duckdb.connect()
    bind_machine_features(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Code may only use
    the unit INTERVAL '1 hour' and a bare 0, which is not a threshold: it is
    the count of an empty window and the guard against dividing by a zero
    ultrafiltration rate."""
    code = "\n".join(line.split("--")[0] for line in MACHINE_FEATURES_SQL.read_text().splitlines())
    code = code.replace("INTERVAL '1 hour'", "")
    assert not re.findall(r"\b(?!0(?![.\d]))\d+(?:\.\d+)?\b", code)


# ── Rows and columns ──────────────────────────────────────────────────────


def test_one_row_per_prediction_row_and_every_column_without_data():
    rows = Chart().circuit(1, 0, 4).run()
    assert sorted(rows) == [(1, k * STEP) for k in range(int(4 / STEP) + 1)]
    row = rows[(1, 4)]
    for s in list(SIG) + DERIVED:
        assert row[f"{s}_last"] is None and row[f"{s}_hours_since_last"] is None
        for w in WINDOWS:
            assert row[f"{s}_{w}h_n"] == 0
            for stat in ("mean", "min", "max", "slope", "var"):
                assert row[f"{s}_{w}h_{stat}"] is None
    assert row["crrt_mode_last"] is None
    assert row["circuit_hours"] == 4


# ── What counts at time t ─────────────────────────────────────────────────


def test_a_value_counts_only_once_stored():
    """Charted at 1 h, stored at 2.5 h: invisible at 1 h and 2 h, visible from 3 h."""
    rows = Chart().circuit(1, 0, 4).value("blood_flow", 1, 150, stored_h=2.5).run()
    assert rows[(1, 1)]["blood_flow_last"] is None
    assert rows[(1, 2)]["blood_flow_last"] is None
    assert rows[(1, 3)]["blood_flow_last"] == 150
    assert rows[(1, 3)]["blood_flow_hours_since_last"] == 2


def test_a_value_charted_after_t_never_counts_even_if_stored_before():
    """storetime < charttime happens (charting ahead to the hour). Charttime
    still bounds what is known."""
    rows = Chart().circuit(1, 0, 4).value("blood_flow", 3, 150, stored_h=2.5).run()
    assert rows[(1, 2)]["blood_flow_last"] is None
    assert rows[(1, 3)]["blood_flow_last"] == 150


def test_values_from_an_earlier_filter_never_count():
    rows = (Chart().circuit(1, 0, 5).circuit(2, 6, 10)
            .value("blood_flow", 5, 100).value("blood_flow", 7, 200).run())
    assert rows[(2, 6)]["blood_flow_last"] is None
    assert rows[(2, 6)][f"blood_flow_{LONG}h_n"] == 0
    assert rows[(2, 7)]["blood_flow_last"] == 200


def test_other_stays_never_count():
    rows = Chart().circuit(1, 0, 4).value("blood_flow", 1, 150, stay=2).run()
    assert rows[(1, 4)]["blood_flow_last"] is None


# ── Plausibility bounds ───────────────────────────────────────────────────


def test_out_of_bound_values_are_missing():
    low, high = BOUNDS[SIG["blood_flow"]]
    rows = (Chart().circuit(1, 0, 4)
            .value("blood_flow", 1, high + 1).value("blood_flow", 2, low - 1).run())
    assert rows[(1, 4)][f"blood_flow_{LONG}h_n"] == 0


def test_bounds_are_inclusive():
    low, high = BOUNDS[SIG["blood_flow"]]
    rows = Chart().circuit(1, 0, 4).value("blood_flow", 1, low).value("blood_flow", 2, high).run()
    assert rows[(1, 4)][f"blood_flow_{LONG}h_min"] == low
    assert rows[(1, 4)][f"blood_flow_{LONG}h_max"] == high


def test_pressures_just_past_a_bound_are_set_to_it():
    low, high = BOUNDS[SIG["filter_pressure"]]
    rows = (Chart().circuit(1, 0, 4)
            .value("filter_pressure", 1, high + MARGIN)
            .value("filter_pressure", 2, low - MARGIN).run())
    row = rows[(1, 4)]
    assert row[f"filter_pressure_{LONG}h_n"] == 2
    assert row[f"filter_pressure_{LONG}h_max"] == high
    assert row[f"filter_pressure_{LONG}h_min"] == low


def test_pressures_far_past_a_bound_are_missing():
    _, high = BOUNDS[SIG["filter_pressure"]]
    rows = Chart().circuit(1, 0, 4).value("filter_pressure", 1, high + MARGIN + 1).run()
    assert rows[(1, 4)][f"filter_pressure_{LONG}h_n"] == 0


def test_only_raw_pressures_are_clipped():
    _, high = BOUNDS[SIG["dialysate_rate"]]
    rows = Chart().circuit(1, 0, 4).value("dialysate_rate", 1, high + 1).run()
    assert rows[(1, 4)][f"dialysate_rate_{LONG}h_n"] == 0


# ── Windows ───────────────────────────────────────────────────────────────


def test_window_includes_its_start_and_nothing_earlier():
    t = LONG + 2
    rows = (Chart().circuit(1, 0, t)
            .value("blood_flow", t - SHORT, 100)
            .value("blood_flow", t - SHORT - 0.5, 200).run())
    row = rows[(1, t)]
    assert row[f"blood_flow_{SHORT}h_n"] == 1 and row[f"blood_flow_{SHORT}h_mean"] == 100
    assert row[f"blood_flow_{LONG}h_n"] == 2 and row[f"blood_flow_{LONG}h_mean"] == 150


def test_slope_is_per_hour_and_variance_is_sample():
    c = Chart().circuit(1, 0, SHORT)
    for k in range(SHORT + 1):
        c.value("filter_pressure", k, 100 + 5 * k)
    row = c.run()[(1, SHORT)]
    vals = [100 + 5 * k for k in range(SHORT + 1)]
    mean = sum(vals) / len(vals)
    assert row[f"filter_pressure_{SHORT}h_slope"] == pytest.approx(5)
    assert row[f"filter_pressure_{SHORT}h_var"] == pytest.approx(
        sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
    assert row[f"filter_pressure_{SHORT}h_min"] == 100
    assert row[f"filter_pressure_{SHORT}h_max"] == 100 + 5 * SHORT


def test_trend_needs_the_minimum_number_of_points():
    c = Chart().circuit(1, 0, LONG)
    for k in range(MIN_POINTS - 1):
        c.value("filter_pressure", LONG - k, 100 + k)
    row = c.run()[(1, LONG)]
    assert row[f"filter_pressure_{LONG}h_n"] == MIN_POINTS - 1
    assert row[f"filter_pressure_{LONG}h_slope"] is None
    assert row[f"filter_pressure_{LONG}h_var"] is None
    assert row[f"filter_pressure_{LONG}h_mean"] is not None


def test_last_is_the_latest_charted_in_the_longest_window():
    t = LONG + 3
    rows = (Chart().circuit(1, 0, t)
            .value("blood_flow", 1, 100).value("blood_flow", 2, 200).run())
    assert rows[(1, 2)]["blood_flow_last"] == 200
    assert rows[(1, 2 + LONG)]["blood_flow_last"] == 200
    assert rows[(1, 2 + LONG)]["blood_flow_hours_since_last"] == LONG
    assert rows[(1, t)]["blood_flow_last"] is None


# ── Derived signals ───────────────────────────────────────────────────────


def test_derived_pressures_use_the_manual_formulas():
    c = pressures(Chart().circuit(1, 0, 2), 1, f=200, r=100, e=-20).value("blood_flow", 1, 150)
    row = c.run()[(1, 2)]
    assert row["pressure_drop_last"] == 100
    assert row["tmp_last"] == 170
    assert row["pressure_drop_per_blood_flow_last"] == pytest.approx(100 / 150)


def test_uf_rate_and_tmp_per_uf_rate():
    c = (pressures(Chart().circuit(1, 0, 2), 1, f=200, r=100, e=-20)
         .value("pbp_rate", 1, 1000).value("replacement_rate", 1, 800)
         .value("fluid_removal_rate", 1, 200))
    row = c.run()[(1, 2)]
    assert row["uf_rate_last"] == 2000
    assert row["tmp_per_uf_rate_last"] == pytest.approx(170 / 2000)


def test_tmp_per_uf_rate_is_missing_when_uf_rate_is_zero():
    c = (pressures(Chart().circuit(1, 0, 2), 1, f=200, r=100, e=-20)
         .value("pbp_rate", 1, 0).value("replacement_rate", 1, 0)
         .value("fluid_removal_rate", 1, 0))
    row = c.run()[(1, 2)]
    assert row["uf_rate_last"] == 0
    assert row["tmp_per_uf_rate_last"] is None


def test_derived_signal_needs_every_component_at_the_same_charttime():
    c = (Chart().circuit(1, 0, 3)
         .value("filter_pressure", 1, 200).value("return_pressure", 2, 100))
    assert c.run()[(1, 3)]["pressure_drop_last"] is None


def test_derived_signal_waits_for_its_last_component():
    c = (Chart().circuit(1, 0, 3)
         .value("filter_pressure", 1, 200).value("return_pressure", 1, 100, stored_h=2.5))
    rows = c.run()
    assert rows[(1, 2)]["filter_pressure_last"] == 200
    assert rows[(1, 2)]["pressure_drop_last"] is None
    assert rows[(1, 3)]["pressure_drop_last"] == 100


def test_derived_signals_use_bounded_pressures():
    low, high = BOUNDS[SIG["filter_pressure"]]
    c = pressures(Chart().circuit(1, 0, 2), 1, f=high + MARGIN, r=100, e=0)
    assert c.run()[(1, 2)]["pressure_drop_last"] == high - 100


# ── CRRT mode ─────────────────────────────────────────────────────────────


def test_crrt_mode_is_the_latest_stored():
    rows = (Chart().circuit(1, 0, 4)
            .mode(1, "CVVHDF").mode(2, "CVVH", stored_h=3.5).run())
    assert rows[(1, 0)]["crrt_mode_last"] is None
    assert rows[(1, 3)]["crrt_mode_last"] == "CVVHDF"
    assert rows[(1, 4)]["crrt_mode_last"] == "CVVH"
