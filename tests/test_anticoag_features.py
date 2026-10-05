"""The anticoagulation features (sql/anticoag_features.sql) on hand-built
circuits.

Each test charts a few values whose correct features are obvious by
construction. No MIMIC data is read. Times are hours after an arbitrary
origin; windows, bounds and the pairing window come from config/config.yaml,
so scenarios are written relative to them. The windowing rules are shared
with machine_features and tested in depth there; these tests cover what
differs.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.features import ANTICOAG_FEATURES_SQL, bind_anticoag_features, build_anticoag_features

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
F = CFG["features"]
SIG = F["anticoag_signals"]
LAB = F["calcium_labs"]
BOUNDS = F["plausibility_bounds"]
WINDOWS = F["window_hours"]
SHORT, LONG = min(WINDOWS), max(WINDOWS)
STEP = CFG["prediction"]["step_hours"]
PAIR_H = F["calcium_pair_minutes"] / 60
LOOKBACK = F["lab_lookback_hours"]
MG_PER_MMOL = F["calcium_mg_dl_per_mmol_l"]
ORIGIN = datetime(2150, 1, 1)

# In-bound values used throughout.
ICA = sum(BOUNDS[LAB["ionized_calcium"]]) / 2
TCA = sum(BOUNDS[LAB["total_calcium"]]) / 2


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class Chart:
    """Synthetic crrt_circuits, circuit_failure_labels, chartevents and
    labevents rows. Every circuit is on stay 1 of subject 1 unless given
    another."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.chart: list[tuple] = []
        self.labs: list[tuple] = []

    def circuit(self, cid: int, start_h: float, end_h: float, stay: int = 1, subject: int = 1):
        self.circuits.append((cid, subject, stay, start_h, end_h))
        return self

    def value(self, name: str, h: float, v: float, stored_h: float | None = None, stay: int = 1):
        self.chart.append((stay, at(h), at(h if stored_h is None else stored_h), SIG[name], v))
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
        build_anticoag_features(con, cfg)
        cur = con.execute("SELECT * FROM anticoag_features")
        cols = [d[0] for d in cur.description]
        out = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out[(r["circuit_id"], (r["pred_time"] - ORIGIN) / timedelta(hours=1))] = r
        return out


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    used = set(re.findall(r"getvariable\('(\w+)'\)", ANTICOAG_FEATURES_SQL.read_text()))
    con = duckdb.connect()
    bind_anticoag_features(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Allowed: the unit
    INTERVAL '1 hour', a bare 0 (an empty window's count, citrate or heparin
    off), the 1 that picks the nearest ionized calcium, and the 2, [1] and
    [2] that pick a lab's last and previous result."""
    code = "\n".join(line.split("--")[0] for line in ANTICOAG_FEATURES_SQL.read_text().splitlines())
    for allowed in ("INTERVAL '1 hour'", ") = 1", ", 2)", "[1]", "[2]"):
        code = code.replace(allowed, "")
    assert not re.findall(r"\b(?!0(?![.\d]))\d+(?:\.\d+)?\b", code)


# ── Rows and columns ──────────────────────────────────────────────────────


def test_one_row_per_prediction_row_and_every_column_without_data():
    rows = Chart().circuit(1, 0, 4).run()
    assert sorted(rows) == [(1, k * STEP) for k in range(int(4 / STEP) + 1)]
    row = rows[(1, 4)]
    for s in list(SIG) + list(LAB) + ["calcium_ratio"]:
        assert row[f"{s}_last"] is None and row[f"{s}_hours_since_last"] is None
    for s in list(LAB) + ["calcium_ratio"]:
        assert row[f"{s}_delta"] is None and row[f"{s}_delta_hours"] is None
    for s in SIG:
        for w in WINDOWS:
            assert row[f"{s}_{w}h_n"] == 0
        assert f"{s}_delta" not in row
    assert row["anticoag_class"] is None


# ── Hourly signals ────────────────────────────────────────────────────────


def test_hourly_signal_counts_once_stored_and_only_on_its_filter():
    rows = (Chart().circuit(1, 0, 5).circuit(2, 6, 10)
            .value("citrate_rate", 1, 180, stored_h=2.5)
            .value("citrate_rate", 5, 150).run())
    assert rows[(1, 2)]["citrate_rate_last"] is None
    assert rows[(1, 3)]["citrate_rate_last"] == 180
    assert rows[(2, 6)]["citrate_rate_last"] is None


def test_hourly_signal_has_window_statistics():
    c = Chart().circuit(1, 0, SHORT)
    for k in range(SHORT + 1):
        c.value("heparin_dose", k, 500 + 100 * k)
    row = c.run()[(1, SHORT)]
    assert row[f"heparin_dose_{SHORT}h_n"] == SHORT + 1
    assert row[f"heparin_dose_{SHORT}h_slope"] == pytest.approx(100)
    assert row["heparin_dose_last"] == 500 + 100 * SHORT


def test_zero_is_a_value_and_out_of_bound_is_missing():
    _, high = BOUNDS[SIG["citrate_rate"]]
    rows = (Chart().circuit(1, 0, 4)
            .value("citrate_rate", 1, 0).value("citrate_rate", 2, high + 1).run())
    assert rows[(1, 4)][f"citrate_rate_{LONG}h_n"] == 1
    assert rows[(1, 4)]["citrate_rate_last"] == 0


# ── Anticoagulation class ─────────────────────────────────────────────────


@pytest.mark.parametrize("citrate, heparin, expected", [
    (180, 1000, "citrate_heparin"),
    (180, 0, "citrate"),
    (180, None, "citrate"),
    (0, 1000, "heparin"),
    (None, 1000, "heparin"),
    (0, 0, "none"),
    (0, None, "none"),
    (None, 0, None),
])
def test_anticoag_class(citrate, heparin, expected):
    c = Chart().circuit(1, 0, 2)
    if citrate is not None:
        c.value("citrate_rate", 1, citrate)
    if heparin is not None:
        c.value("heparin_dose", 1, heparin)
    assert c.run()[(1, 2)]["anticoag_class"] == expected


def test_class_follows_the_latest_value():
    rows = (Chart().circuit(1, 0, 4)
            .value("citrate_rate", 1, 180).value("citrate_rate", 3, 0).run())
    assert rows[(1, 2)]["anticoag_class"] == "citrate"
    assert rows[(1, 3)]["anticoag_class"] == "none"


# ── Calcium labs ──────────────────────────────────────────────────────────


def test_lab_counts_only_once_stored():
    rows = Chart().circuit(1, 0, 4).lab("ionized_calcium", 1, ICA, stored_h=2.5).run()
    assert rows[(1, 2)]["ionized_calcium_last"] is None
    assert rows[(1, 3)]["ionized_calcium_last"] == ICA
    assert rows[(1, 3)]["ionized_calcium_hours_since_last"] == 2


def test_lab_before_the_circuit_counts_within_the_lab_lookback():
    """A lab is the patient's, not the filter's: a draw before circuit_start
    still counts, back to features.lab_lookback_hours, not the longest
    window."""
    rows = (Chart().circuit(1, LOOKBACK, LOOKBACK + 2)
            .lab("ionized_calcium", 0.5, ICA).lab("total_calcium", 1, TCA).run())
    assert LOOKBACK > LONG
    assert rows[(1, LOOKBACK)]["total_calcium_last"] == TCA
    assert rows[(1, LOOKBACK)]["ionized_calcium_last"] == ICA
    assert rows[(1, LOOKBACK + 1)]["ionized_calcium_last"] is None
    assert rows[(1, LOOKBACK + 1)]["total_calcium_last"] == TCA


def test_other_patients_labs_never_count():
    rows = Chart().circuit(1, 0, 4).lab("ionized_calcium", 1, ICA, subject=2).run()
    assert rows[(1, 4)]["ionized_calcium_last"] is None


def test_out_of_bound_lab_is_missing_and_bounds_are_inclusive():
    low, high = BOUNDS[LAB["ionized_calcium"]]
    rows = (Chart().circuit(1, 0, 4)
            .lab("ionized_calcium", 1, low).lab("ionized_calcium", 2, low - 0.01).run())
    assert rows[(1, 2)]["ionized_calcium_last"] == low
    assert rows[(1, 4)]["ionized_calcium_last"] == low


def test_results_at_one_charttime_are_averaged_and_wait_for_the_later():
    rows = (Chart().circuit(1, 0, 4)
            .lab("total_calcium", 1, TCA - 1)
            .lab("total_calcium", 1, TCA + 1, stored_h=2.5).run())
    assert rows[(1, 2)]["total_calcium_last"] is None
    assert rows[(1, 3)]["total_calcium_last"] == pytest.approx(TCA)


def test_lab_delta_is_last_minus_previous():
    rows = (Chart().circuit(1, 0, 6)
            .lab("ionized_calcium", 1, ICA).lab("ionized_calcium", 4, ICA - 0.1).run())
    assert rows[(1, 3)]["ionized_calcium_delta"] is None
    assert rows[(1, 6)]["ionized_calcium_delta"] == pytest.approx(-0.1)
    assert rows[(1, 6)]["ionized_calcium_delta_hours"] == 3


# ── Total:ionized ratio ───────────────────────────────────────────────────


def test_ratio_is_total_in_mmol_over_ionized():
    rows = (Chart().circuit(1, 0, 3)
            .lab("total_calcium", 1, TCA).lab("ionized_calcium", 1 + PAIR_H, ICA).run())
    assert rows[(1, 3)]["calcium_ratio_last"] == pytest.approx(TCA / MG_PER_MMOL / ICA)
    assert rows[(1, 3)]["calcium_ratio_hours_since_last"] == 2


def test_ratio_needs_a_pair_within_the_window():
    rows = (Chart().circuit(1, 0, 4)
            .lab("total_calcium", 1, TCA).lab("ionized_calcium", 1 + PAIR_H + 0.25, ICA).run())
    assert rows[(1, 4)]["calcium_ratio_last"] is None


def test_ratio_uses_the_nearest_ionized_and_the_earlier_on_a_tie():
    rows = (Chart().circuit(1, 0, 4)
            .lab("total_calcium", 2, TCA)
            .lab("ionized_calcium", 2 - PAIR_H / 2, 1.0)
            .lab("ionized_calcium", 2 + PAIR_H / 2, 1.2)
            .lab("ionized_calcium", 2 + PAIR_H, 0.9).run())
    assert rows[(1, 4)]["calcium_ratio_last"] == pytest.approx(TCA / MG_PER_MMOL / 1.0)


def test_ratio_waits_for_both_results():
    rows = (Chart().circuit(1, 0, 4)
            .lab("total_calcium", 1, TCA, stored_h=2.5).lab("ionized_calcium", 1, ICA).run())
    assert rows[(1, 2)]["ionized_calcium_last"] == ICA
    assert rows[(1, 2)]["calcium_ratio_last"] is None
    assert rows[(1, 3)]["calcium_ratio_last"] is not None


def test_ratio_delta_is_between_successive_pairs():
    first = TCA / MG_PER_MMOL / ICA
    second = (TCA + 1) / MG_PER_MMOL / ICA
    rows = (Chart().circuit(1, 0, 6)
            .lab("total_calcium", 1, TCA).lab("ionized_calcium", 1, ICA)
            .lab("total_calcium", 4, TCA + 1).lab("ionized_calcium", 4, ICA).run())
    assert rows[(1, 6)]["calcium_ratio_delta"] == pytest.approx(second - first)
    assert rows[(1, 6)]["calcium_ratio_delta_hours"] == 3
