"""The cohort rules (sql/crrt_cohort.sql) on hand-built stays.

Each stay is one patient with one admission unless a test says otherwise, so
the correct flags are obvious by construction. No MIMIC data is read. Times
are hours after an arbitrary origin; thresholds come from
config/config.yaml.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.cohort import SQL_PATH, bind, build, render

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
COHORT = CFG["cohort"]
DIAL = COHORT["chronic_dialysis"]
MIN_H = COHORT["min_session_duration_hours"]
ADULT = COHORT["min_age_years"]
ORIGIN = datetime(2150, 1, 1)
YEAR = ORIGIN.year
TUNNELED_ITEM, TUNNELED_VALUE = next(iter(DIAL["tunneled_catheter_values"].items()))
ICD = DIAL["icd_codes"][0]


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class World:
    """Synthetic rows for every table the cohort SQL reads."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.patients: dict[int, int] = {}
        self.admissions: list[tuple] = []
        self.icd: list[tuple] = []
        self.chart: list[tuple] = []
        self.dates: list[tuple] = []

    def stay(self, stay_id: int, age: int = ADULT + 40, circuits=((0, MIN_H + 10),)):
        """A patient, admission and ICU stay all numbered `stay_id`, with
        circuits given as (start hour, duration hours)."""
        self.patients[stay_id] = age
        self.admissions.append((stay_id, stay_id, ORIGIN))
        for start, dur in circuits:
            self.circuits.append((stay_id, stay_id, stay_id, at(start), float(dur)))
        return self

    def chart_row(self, stay_id, h, itemid, value=None, valuenum=None):
        self.chart.append((stay_id, at(h), itemid, value, valuenum))
        return self

    def run(self) -> list[dict]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, subject_id INTEGER, "
                    "hadm_id INTEGER, stay_id INTEGER, circuit_start TIMESTAMP, "
                    "duration_hours DOUBLE)")
        con.execute("CREATE TABLE icustays (stay_id INTEGER, intime TIMESTAMP)")
        con.execute("CREATE TABLE patients (subject_id INTEGER, anchor_age INTEGER, "
                    "anchor_year INTEGER)")
        con.execute("CREATE TABLE admissions (hadm_id INTEGER, subject_id INTEGER, "
                    "admittime TIMESTAMP)")
        con.execute("CREATE TABLE diagnoses_icd (hadm_id INTEGER, icd_code VARCHAR)")
        con.execute("CREATE TABLE chartevents (stay_id INTEGER, charttime TIMESTAMP, "
                    "itemid INTEGER, value VARCHAR, valuenum DOUBLE)")
        con.execute("CREATE TABLE datetimeevents (stay_id INTEGER, itemid INTEGER, "
                    "value TIMESTAMP)")
        def insert(table: str, rows: list[tuple]) -> None:
            if rows:  # executemany rejects an empty list
                marks = ", ".join("?" * len(rows[0]))
                con.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)

        insert("crrt_circuits", [(i, *c) for i, c in enumerate(self.circuits)])
        insert("icustays", [(s, ORIGIN) for s in self.patients])
        insert("patients", [(s, age, YEAR) for s, age in self.patients.items()])
        insert("admissions", self.admissions)
        insert("diagnoses_icd", self.icd)
        insert("chartevents", self.chart)
        insert("datetimeevents", self.dates)
        build(con, CFG)
        cur = con.execute("SELECT * FROM crrt_cohort ORDER BY circuit_id")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def one(rows: list[dict], stay_id: int) -> dict:
    (r,) = [r for r in rows if r["stay_id"] == stay_id]
    return r


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    """getvariable() of an unset name is NULL, which silently makes every
    comparison false. Bind, then check each one."""
    used = set(re.findall(r"getvariable\('(\w+)'\)", SQL_PATH.read_text()))
    con = duckdb.connect()
    bind(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    code = "\n".join(line.split("--")[0] for line in SQL_PATH.read_text().splitlines())
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


# ── Exclusions ────────────────────────────────────────────────────────────


def test_exclusions_are_flagged_in_order_and_no_row_is_dropped():
    rows = (World()
            .stay(1)
            .stay(2, age=ADULT - 1)
            .stay(3, circuits=[(0, MIN_H - 1)])
            .stay(4, age=ADULT - 1, circuits=[(0, MIN_H - 1)])
            .run())
    assert len(rows) == 4
    assert one(rows, 1)["included"] and one(rows, 1)["exclusion_reason"] is None
    assert one(rows, 2)["exclusion_reason"] == "under_min_age"
    assert one(rows, 3)["exclusion_reason"] == "under_min_duration"
    # Both rules fail; the first in STROBE order is reported.
    assert one(rows, 4)["exclusion_reason"] == "under_min_age"
    assert not any(one(rows, s)["included"] for s in (2, 3, 4))


def test_circuit_of_exactly_the_minimum_duration_is_kept():
    assert World().stay(1, circuits=[(0, MIN_H)]).run()[0]["included"]


# ── Chronic dialysis flag ─────────────────────────────────────────────────


def test_no_evidence_means_no_flag():
    r = World().stay(1).run()[0]
    assert not r["chronic_dialysis"] and not r["chronic_dialysis_sensitivity"]


def test_admission_history_flags_whenever_charted():
    """It records pre-admission status, so its charttime does not matter."""
    w = World().stay(1).chart_row(1, 5, DIAL["admission_history_itemid"],
                                  valuenum=DIAL["admission_history_value"])
    w.stay(2).chart_row(2, 5, DIAL["admission_history_itemid"], valuenum=0.0)
    rows = w.run()
    assert one(rows, 1)["chronic_dialysis"] and one(rows, 1)["src_admission_history"]
    assert not one(rows, 2)["chronic_dialysis"]


def test_last_dialysis_counts_only_before_crrt_start():
    w = World().stay(1, circuits=[(10, MIN_H + 10)]).stay(2, circuits=[(10, MIN_H + 10)])
    w.dates += [(1, DIAL["last_dialysis_itemid"], at(-24)),
                (2, DIAL["last_dialysis_itemid"], at(12))]
    rows = w.run()
    assert one(rows, 1)["chronic_dialysis"]
    assert not one(rows, 2)["chronic_dialysis"]


def test_tunneled_catheter_counts_only_before_crrt_start():
    rows = (World()
            .stay(1, circuits=[(10, MIN_H + 10)]).chart_row(1, 5, TUNNELED_ITEM, TUNNELED_VALUE)
            .stay(2, circuits=[(10, MIN_H + 10)]).chart_row(2, 15, TUNNELED_ITEM, TUNNELED_VALUE)
            .stay(3, circuits=[(10, MIN_H + 10)]).chart_row(3, 5, TUNNELED_ITEM, "Temporary")
            .run())
    assert one(rows, 1)["src_tunneled_catheter"] and one(rows, 1)["chronic_dialysis"]
    assert not one(rows, 2)["chronic_dialysis"]
    assert not one(rows, 3)["chronic_dialysis"]


def test_crrt_start_is_the_first_circuit_long_enough_to_count():
    """A short artifact circuit before the real one does not move CRRT start
    earlier: a catheter charted between the two still counts."""
    rows = (World()
            .stay(1, circuits=[(0, MIN_H - 1), (20, MIN_H + 10)])
            .chart_row(1, 10, TUNNELED_ITEM, TUNNELED_VALUE)
            .run())
    assert all(r["chronic_dialysis"] for r in rows)


def test_icd_on_an_earlier_admission_is_primary_evidence():
    w = World().stay(1)
    w.admissions.append((100, 1, ORIGIN - timedelta(days=365)))
    w.icd.append((100, ICD))
    r = w.run()[0]
    assert r["src_prior_admission_icd"] and r["chronic_dialysis"]


def test_icd_on_a_later_admission_is_not_evidence():
    w = World().stay(1)
    w.admissions.append((100, 1, ORIGIN + timedelta(days=365)))
    w.icd.append((100, ICD))
    assert not w.run()[0]["chronic_dialysis"]


def test_same_admission_icd_flags_only_the_sensitivity_definition():
    """The point of the 2026-10-02 decision: a discharge code from this
    admission can record dialysis dependence that began during it."""
    w = World().stay(1)
    w.icd.append((1, ICD))
    r = w.run()[0]
    assert r["src_same_admission_icd"]
    assert r["chronic_dialysis"] is DIAL["same_admission_icd_primary"]
    assert r["chronic_dialysis_sensitivity"] is DIAL["same_admission_icd_sensitivity"]


def test_codes_outside_the_list_are_ignored():
    w = World().stay(1)
    w.admissions.append((100, 1, ORIGIN - timedelta(days=365)))
    w.icd.append((100, "N185"))  # CKD stage 5: deliberately not in the list
    assert "N185" not in DIAL["icd_codes"]
    assert not w.run()[0]["chronic_dialysis_sensitivity"]


# ── STROBE rendering ──────────────────────────────────────────────────────


def test_flow_refuses_a_step_that_would_disclose_a_small_cell_by_difference():
    small = CFG["reporting"]["small_cell_threshold"]
    boxes = [("Circuits", (100, 50, 40), None),
             ("Excluding: something", (100 - (small - 1), 50, 40), small - 1)]
    with pytest.raises(ValueError, match="small cell"):
        render(CFG, boxes)


def test_flow_allows_steps_that_remove_nothing_or_enough():
    small = CFG["reporting"]["small_cell_threshold"]
    boxes = [("Circuits", (100, 50, 40), None),
             ("Excluding: nothing", (100, 50, 40), 0),
             ("Excluding: plenty", (100 - small, 50 - small, 40 - small), small)]
    doc = render(CFG, boxes)
    assert "| Excluding: plenty |" in doc
