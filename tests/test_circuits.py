"""The circuit definition (sql/crrt_circuits.sql) on hand-built stays.

Each test builds one or more synthetic ICU stays whose correct circuits are
obvious by construction, then checks the SQL agrees. No MIMIC data is read,
so these run anywhere. Times are hours after an arbitrary origin; windows and
thresholds come from config/config.yaml, so a scenario is written relative to
them where it sits near a boundary.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.circuits import SQL_PATH, bind, build

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
C = CFG["circuits"]
ORIGIN = datetime(2150, 1, 1)
BLOOD_FLOW = C["machine_itemids"][0]
INTEGRITY = C["system_integrity_itemid"]
REASON = C["filter_change_reason_itemid"]


class Stays:
    """Accumulates synthetic rows, then loads them into a fresh DuckDB."""

    def __init__(self):
        self.chart: list[tuple] = []
        self.stays: dict[int, dict] = {}

    def stay(self, stay_id: int, death_h: float | None = None, out_h: float | None = None):
        self.stays[stay_id] = {"death_h": death_h, "out_h": out_h}
        return self

    def machine(self, stay_id: int, start_h: float, end_h: float, valuenum: float | None = 150.0):
        """Hourly blood-flow charting from start_h to end_h inclusive."""
        h = start_h
        while h <= end_h:
            self.chart.append((stay_id, h, BLOOD_FLOW, str(valuenum), valuenum))
            h += 1
        return self

    def integrity(self, stay_id: int, h: float, value: str):
        self.chart.append((stay_id, h, INTEGRITY, value, None))
        return self

    def reason(self, stay_id: int, h: float, value: str):
        self.chart.append((stay_id, h, REASON, value, None))
        return self

    def run(self) -> list[dict]:
        con = duckdb.connect()
        con.execute(
            "CREATE TABLE chartevents (subject_id INTEGER, hadm_id INTEGER, stay_id INTEGER, "
            "charttime TIMESTAMP, itemid INTEGER, value VARCHAR, valuenum DOUBLE)"
        )
        con.execute(
            "CREATE TABLE icustays (subject_id INTEGER, hadm_id INTEGER, stay_id INTEGER, "
            "intime TIMESTAMP, outtime TIMESTAMP)"
        )
        con.execute("CREATE TABLE admissions (hadm_id INTEGER, deathtime TIMESTAMP)")
        at = lambda h: ORIGIN + timedelta(hours=h)  # noqa: E731
        con.executemany(
            "INSERT INTO chartevents VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(s, s, s, at(h), item, v, vn) for s, h, item, v, vn in self.chart],
        )
        for s, info in self.stays.items():
            # Unless a test says otherwise the patient leaves the ICU alive,
            # long after CRRT, so neither end rule can fire by accident.
            out = at(info["out_h"]) if info["out_h"] is not None else at(10_000)
            death = at(info["death_h"]) if info["death_h"] is not None else None
            con.execute("INSERT INTO icustays VALUES (?, ?, ?, ?, ?)", [s, s, s, ORIGIN, out])
            con.execute("INSERT INTO admissions VALUES (?, ?)", [s, death])
        build(con, CFG)
        cur = con.execute("SELECT * FROM crrt_circuits ORDER BY stay_id, circuit_no")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def by_stay(rows: list[dict], stay_id: int) -> list[dict]:
    return [r for r in rows if r["stay_id"] == stay_id]


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    """getvariable() of an unset name returns NULL silently, and a NULL
    window makes every BETWEEN false: a dropped config key would quietly
    reclassify circuits instead of failing. Bind, then check each one."""
    used = set(re.findall(r"getvariable\('(\w+)'\)", SQL_PATH.read_text()))
    con = duckdb.connect()
    bind(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Comments are
    allowed to cite numbers; code may only use the unit INTERVAL '1 hour'."""
    code = "\n".join(line.split("--")[0] for line in SQL_PATH.read_text().splitlines())
    code = code.replace("INTERVAL '1 hour'", "")
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


# ── Circuit boundaries ────────────────────────────────────────────────────


def test_single_uninterrupted_run_is_one_circuit_that_ends_crrt():
    rows = Stays().stay(1).machine(1, 0, 10).run()
    assert len(rows) == 1
    (c,) = rows
    assert c["start_reason"] == "first_of_stay"
    assert c["duration_hours"] == 10
    assert c["termination_class"] == "crrt_ended"


def test_new_filter_mid_segment_splits_the_circuit():
    rows = Stays().stay(2).machine(2, 0, 20).integrity(2, 10, "New Filter").run()
    assert [(c["circuit_start"], c["circuit_end"]) for c in rows] == [
        (ORIGIN, ORIGIN + timedelta(hours=9)),
        (ORIGIN + timedelta(hours=10), ORIGIN + timedelta(hours=20)),
    ]
    assert rows[1]["start_reason"] == "new_filter"


def test_new_filter_in_first_hour_documents_the_starting_filter():
    """58% of New Filter events fall in a segment's first hour (feasibility
    §2.2); they describe the filter the segment began on, not a second one."""
    early = C["new_filter_min_hours_after_segment_start"] / 2
    rows = Stays().stay(3).machine(3, 0, 10).integrity(3, early, "New Filter").run()
    assert len(rows) == 1
    assert rows[0]["starts_new_filter"]


def test_short_gap_without_new_filter_is_downtime_on_the_same_filter():
    gap = CFG["sessionization"]["gap_hours"] + 1
    assert gap < C["max_downtime_hours"]
    rows = Stays().stay(4).machine(4, 0, 5).machine(4, 5 + gap, 15).run()
    assert len(rows) == 1
    (c,) = rows
    assert c["n_pieces"] == 2
    assert c["duration_hours"] == 15
    assert c["running_hours"] == 15 - gap


def test_gap_longer_than_max_downtime_starts_a_new_circuit():
    gap = C["max_downtime_hours"] + 2
    rows = Stays().stay(5).machine(5, 0, 5).machine(5, 5 + gap, 20).run()
    assert [c["start_reason"] for c in rows] == ["first_of_stay", "after_long_gap"]
    assert rows[0]["termination_class"] == "undocumented"


def test_short_gap_after_clotted_is_still_a_new_circuit():
    """A filter that clotted is gone, however soon the next one starts."""
    gap = CFG["sessionization"]["gap_hours"] + 1
    rows = (
        Stays().stay(6)
        .machine(6, 0, 5).integrity(6, 5.5, "Clotted")
        .machine(6, 5 + gap, 15)
        .run()
    )
    assert [c["start_reason"] for c in rows] == ["first_of_stay", "after_clotted"]
    assert rows[0]["termination_class"] == "clotted"


def test_new_filter_with_no_machine_charting_produces_no_circuit():
    rows = (
        Stays().stay(7)
        .machine(7, 0, 5)
        .integrity(7, 5.5, "New Filter")
        .integrity(7, 5.8, "New Filter")
        .machine(7, 6, 12)
        .run()
    )
    # 5.5 never ran (nothing charted before 5.8), so circuits are [0,5] and
    # [5.8, 12].
    assert len(rows) == 2
    assert rows[1]["circuit_start"] == ORIGIN + timedelta(hours=5.8)


def test_machine_rows_without_a_number_do_not_extend_a_circuit():
    rows = Stays().stay(8).machine(8, 0, 10).machine(8, 11, 30, valuenum=None).run()
    assert len(rows) == 1
    assert rows[0]["duration_hours"] == 10


# ── Termination class ─────────────────────────────────────────────────────


def test_clotted_outranks_death():
    rows = Stays().stay(9, death_h=11).machine(9, 0, 10).integrity(9, 10.5, "Clotted").run()
    assert rows[0]["end_death"] and rows[0]["end_clotted"]
    assert rows[0]["termination_class"] == "clotted"


def test_reason_clotted_counts_as_clotted():
    rows = Stays().stay(10).machine(10, 0, 10).reason(10, 11, "Clotted").run()
    assert rows[0]["termination_class"] == "clotted"


def test_clotted_outside_the_end_window_is_not_a_clot_termination():
    before, _ = C["windows_hours"]["clotted_at_end"]
    rows = Stays().stay(11).machine(11, 0, 20).integrity(11, 20 - before - 1, "Clotted").run()
    assert rows[0]["termination_class"] == "crrt_ended"


def test_clots_increasing_at_end():
    rows = Stays().stay(12).machine(12, 0, 10).integrity(12, 9, "Clots Increasing").run()
    assert rows[0]["termination_class"] == "clots_increasing"


def test_death_after_the_end():
    rows = Stays().stay(13, death_h=15).machine(13, 0, 10).run()
    assert rows[0]["termination_class"] == "death"


def test_long_circuit_reached_the_scheduled_limit():
    limit = C["reached_limit_hours"]
    rows = (
        Stays().stay(14)
        .machine(14, 0, limit + 1)
        .integrity(14, limit + 2, "New Filter")
        .machine(14, limit + 2, limit + 10)
        .run()
    )
    assert rows[0]["termination_class"] == "reached_limit"


def test_icu_discharge_after_the_end():
    rows = Stays().stay(15, out_h=12).machine(15, 0, 10).run()
    assert rows[0]["termination_class"] == "icu_discharge"


def test_stopped_then_restarted():
    gap = C["max_downtime_hours"] + 2
    rows = (
        Stays().stay(16)
        .machine(16, 0, 10).integrity(16, 10.5, "Discontinued")
        .machine(16, 10 + gap, 20)
        .run()
    )
    assert [c["termination_class"] for c in rows] == ["stopped_then_restarted", "crrt_ended"]


def test_stays_are_independent():
    """Circuit numbering and stitching never cross a stay boundary."""
    rows = Stays().stay(17).stay(18).machine(17, 0, 10).machine(18, 3, 10).run()
    assert [(c["stay_id"], c["circuit_no"], c["start_reason"]) for c in rows] == [
        (17, 1, "first_of_stay"),
        (18, 1, "first_of_stay"),
    ]


# ── Outcome config names real classes ─────────────────────────────────────


def termination_classes() -> set[str]:
    sql = SQL_PATH.read_text()
    case = sql[sql.index("-- Hierarchical"):sql.index("END AS termination_class")]
    return set(re.findall(r"THEN '(\w+)'", case)) | set(re.findall(r"ELSE '(\w+)'", case))


def test_outcome_classes_exist_and_do_not_overlap():
    """A misspelt class in config would silently empty the event set."""
    cf = CFG["outcomes"]["circuit_failure"]
    groups = {
        "event_primary": set(cf["event_classes_primary"]),
        "event_sensitivity": set(cf["event_classes_sensitivity"]),
        "competing_risk": set(cf["competing_risk_classes"]),
        "unclear": set(cf["unclear_classes"]),
    }
    known = termination_classes()
    assert len(known) == 9
    for name, classes in groups.items():
        assert classes and classes <= known, f"{name}: unknown {sorted(classes - known)}"
    assert groups["event_primary"] <= groups["event_sensitivity"]
    others = groups["competing_risk"] | groups["unclear"]
    assert not groups["event_sensitivity"] & others
    assert not groups["competing_risk"] & groups["unclear"]
