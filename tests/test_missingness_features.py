"""The missingness features (sql/missingness_features.sql) on hand-built
circuits.

Each test draws a few results whose correct features are obvious by
construction. No MIMIC data is read. Times are hours after an arbitrary
origin; the lookback and the bounds come from config/config.yaml, so
scenarios are written relative to them. lab_features is built for real
from the same labevents, so the draw counts are held to the rows its
<name>_last chooses from. The other four groups are stubs: their keys,
plus any column a test sets.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.features import (MISSINGNESS_FEATURES_SQL, bind_missingness_features,
                           build_lab_features, build_missingness_features)

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
F = CFG["features"]
LAB_GROUPS = {name: itemid for group in F["lab_groups"].values() for name, itemid in group.items()}
LAB = {**LAB_GROUPS, **F["calcium_labs"], **F["hemodynamic_labs"]}
BOUNDS = F["plausibility_bounds"]
LOOKBACK = F["lab_lookback_hours"]
STEP = CFG["prediction"]["step_hours"]
ORIGIN = datetime(2150, 1, 1)
STUBS = ("machine_features", "anticoag_features", "access_features", "hemodynamic_features")

# An in-bound platelet count, used throughout.
PLT = sum(BOUNDS[LAB["platelets"]]) / 2


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


def mid(name: str) -> float:
    return sum(BOUNDS[LAB[name]]) / 2


def n(name: str) -> str:
    return f"{name}_{LOOKBACK}h_n"


class Chart:
    """Synthetic crrt_circuits, circuit_failure_labels, labevents and stub
    feature tables. Every circuit is on subject 1 unless given another."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.labs: list[tuple] = []
        self.stubs: dict[str, dict[str, dict[tuple[int, float], float]]] = {t: {} for t in STUBS}

    def circuit(self, cid: int, start_h: float, end_h: float, subject: int = 1):
        self.circuits.append((cid, subject, start_h, end_h))
        return self

    def lab(self, name: str, h: float, v: float, stored_h: float | None = None, subject: int = 1):
        self.labs.append((subject, at(h), at(h if stored_h is None else stored_h), LAB[name], v))
        return self

    def stub(self, table: str, column: str, values: dict[tuple[int, float], float]):
        """Set `column` of a stub feature table: `values` at those rows, null
        at every other."""
        self.stubs[table][column] = values
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
        for table, columns in self.stubs.items():
            con.execute(f"CREATE TABLE {table} AS SELECT circuit_id, pred_time "
                        "FROM circuit_failure_labels")
            for column, values in columns.items():
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} DOUBLE")
                for (cid, h), v in values.items():
                    con.execute(f"UPDATE {table} SET {column} = ? "
                                "WHERE circuit_id = ? AND pred_time = ?", [v, cid, at(h)])
        build_missingness_features(con, cfg)
        out = {}
        for table in ("lab_features", "missingness_features"):
            cur = con.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                out.setdefault((r["circuit_id"], (r["pred_time"] - ORIGIN) / timedelta(hours=1)),
                               {}).update(r)
        return out


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    used = set(re.findall(r"getvariable\('(\w+)'\)", MISSINGNESS_FEATURES_SQL.read_text()))
    con = duckdb.connect()
    bind_missingness_features(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Allowed: the
    regex back-reference \\1 that names each flag."""
    code = "\n".join(line.split("--")[0] for line in MISSINGNESS_FEATURES_SQL.read_text().splitlines())
    code = code.replace("'\\1_measured'", "")
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


def test_every_lab_item_has_a_bound():
    assert all(itemid in BOUNDS for itemid in LAB.values())


# ── Rows and columns ──────────────────────────────────────────────────────


def test_one_row_per_prediction_row_and_every_column_without_data():
    rows = Chart().circuit(1, 0, 4).stub("machine_features", "blood_flow_hours_since_last", {}).run()
    assert sorted(rows) == [(1, k * STEP) for k in range(int(4 / STEP) + 1)]
    flags = {f"{s}_measured" for s in [*LAB_GROUPS, "blood_flow"]}
    counts = {n(s) for s in LAB}
    row = rows[(1, 4)]
    assert flags | counts <= set(row)
    assert all(row[c] is False for c in flags)
    assert all(row[c] == 0 for c in counts)


def test_a_flag_for_every_hours_since_last_column_of_every_group():
    c = Chart().circuit(1, 0, 2)
    for t in STUBS:
        c.stub(t, f"{t}_signal_hours_since_last", {(1, 1): 0.5})
    row = c.run()[(1, 1)]
    assert all(row[f"{t}_signal_measured"] is True for t in STUBS)


def test_flag_is_true_exactly_when_hours_since_last_is_not_null():
    rows = (Chart().circuit(1, 0, 3)
            .stub("machine_features", "tmp_hours_since_last", {(1, 1): 0.0, (1, 3): 2.0})
            .stub("machine_features", "tmp_last", {(1, 1): 100.0, (1, 3): 100.0}).run())
    assert [rows[(1, h)]["tmp_measured"] for h in (0, 1, 2, 3)] == [False, True, False, True]
    assert "tmp_last_measured" not in rows[(1, 1)]


# ── Draw counts ───────────────────────────────────────────────────────────


def test_every_lab_item_is_counted_under_its_own_name():
    c = Chart().circuit(1, 0, 2)
    for k, name in enumerate(LAB):
        for j in range(k + 1):
            c.lab(name, j / (k + 2), mid(name))
    row = c.run()[(1, 2)]
    assert [row[n(name)] for name in LAB] == list(range(1, len(LAB) + 1))


def test_draw_counts_only_once_stored():
    rows = Chart().circuit(1, 0, 4).lab("platelets", 1, PLT, stored_h=2.5).run()
    assert rows[(1, 2)][n("platelets")] == 0
    assert rows[(1, 3)][n("platelets")] == 1


def test_draws_count_back_to_exactly_the_lookback():
    rows = (Chart().circuit(1, LOOKBACK + 1, LOOKBACK + 3)
            .lab("platelets", 1, PLT).lab("platelets", LOOKBACK, PLT).run())
    assert rows[(1, LOOKBACK + 1)][n("platelets")] == 2
    assert rows[(1, LOOKBACK + 2)][n("platelets")] == 1


def test_draws_on_another_circuit_count_and_other_patients_never():
    rows = (Chart().circuit(1, 0, 2).circuit(2, 3, 5)
            .lab("platelets", 1, PLT).lab("platelets", 4, PLT, subject=2).run())
    assert rows[(2, 5)][n("platelets")] == 1


def test_out_of_bound_results_are_not_draws_and_bounds_are_inclusive():
    low, high = BOUNDS[LAB["glucose"]]
    rows = (Chart().circuit(1, 0, 6)
            .lab("glucose", 1, low).lab("glucose", 2, low - 1)
            .lab("glucose", 3, high).lab("glucose", 4, high + 1).run())
    assert rows[(1, 6)][n("glucose")] == 2


def test_results_at_one_charttime_are_one_draw_and_wait_for_the_later():
    rows = (Chart().circuit(1, 0, 4)
            .lab("potassium", 1, 4.0)
            .lab("potassium", 1, 5.0, stored_h=2.5).run())
    assert rows[(1, 2)][n("potassium")] == 0
    assert rows[(1, 3)][n("potassium")] == 1


def test_count_is_zero_exactly_when_the_lab_is_not_measured():
    """The count is over the rows <name>_last chooses from, so it agrees
    with the flag on every row, whatever the timing of the draws."""
    rows = (Chart().circuit(1, 0, LOOKBACK + 4)
            .lab("platelets", 1, PLT, stored_h=3.5)
            .lab("platelets", 2, PLT + 1)
            .lab("inr", 0, mid("inr"), stored_h=LOOKBACK + 2).run())
    for r in rows.values():
        for name in ("platelets", "inr"):
            assert (r[n(name)] > 0) == r[f"{name}_measured"] == (r[f"{name}_last"] is not None)
