"""The static features (sql/static_features.sql) on hand-built stays.

Each test charts a few rows whose correct features are obvious by
construction. No MIMIC data is read. Times are hours after an arbitrary
origin; items, units, bounds and groups come from config/config.yaml, so
scenarios are written relative to them. mimiciv_derived.sofa and
mimiciv_derived.sepsis3 are stand-ins with only the columns the SQL reads.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.features import STATIC_FEATURES_SQL, bind_static_features, build_static_features

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
F = CFG["features"]
BOUNDS = F["plausibility_bounds"]
STEP = CFG["prediction"]["step_hours"]
ORIGIN = datetime(2150, 1, 1)

ADMISSION_KG = next(i for i, u in F["weight_items"].items() if u == "kg")
DAILY_KG = [i for i, u in F["weight_items"].items() if u == "kg"][-1]
LB = next(i for i, u in F["weight_items"].items() if u == "lb")
CM = next(i for i, u in F["height_items"].items() if u == "cm")
INCH = next(i for i, u in F["height_items"].items() if u == "in")
ADMISSION_TYPE, ADMISSION_GROUP = next(iter(F["admission_type_groups"].items()))
SERVICE, SERVICE_GROUP = next(iter(F["service_groups"].items()))
OTHER_SERVICE, OTHER_GROUP = next((s, g) for s, g in F["service_groups"].items() if g != SERVICE_GROUP)

WEIGHT = 80.0     # kg, in bound
HEIGHT = 175.0    # cm, in bound


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class Chart:
    """Synthetic source tables. A stay is its own subject and admission
    (stay_id = subject_id = hadm_id); every circuit is included unless
    stated."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.chart: list[tuple] = []
        self.services: list[tuple] = []
        self.sofa: list[tuple] = []
        self.sepsis: list[tuple] = []
        self.admission_type = ADMISSION_TYPE

    def circuit(self, cid: int, start_h: float, end_h: float, stay: int = 1, included: bool = True):
        self.circuits.append((cid, stay, start_h, end_h, included))
        return self

    def value(self, itemid: int, h: float, v: float, stored_h: float | None = None, stay: int = 1):
        self.chart.append((stay, at(h), at(h if stored_h is None else stored_h), itemid, v))
        return self

    def service(self, h: float, code: str, stay: int = 1):
        self.services.append((stay, at(h), code))
        return self

    def sofa_hour(self, end_h: float, resp=0, coag=0, liver=0, cns=0, renal=0, cv=0, stay: int = 1):
        self.sofa.append((stay, at(end_h), resp, coag, liver, cns, renal, cv))
        return self

    def sepsis3(self, antibiotic_h: float, culture_h: float, sofa_h: float, stay: int = 1):
        self.sepsis.append((stay, at(antibiotic_h), at(culture_h), at(sofa_h), True))
        return self

    def run(self, cfg=CFG) -> dict[int, dict]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, subject_id INTEGER, "
                    "hadm_id INTEGER, stay_id INTEGER, circuit_start TIMESTAMP, circuit_end TIMESTAMP)")
        con.execute("CREATE TABLE crrt_cohort (circuit_id INTEGER, age_years INTEGER, included BOOLEAN)")
        con.execute("CREATE TABLE circuit_failure_labels (circuit_id INTEGER, pred_time TIMESTAMP)")
        con.execute("CREATE TABLE patients (subject_id INTEGER, gender VARCHAR)")
        con.execute("CREATE TABLE admissions (hadm_id INTEGER, admission_type VARCHAR)")
        con.execute("CREATE TABLE services (hadm_id INTEGER, transfertime TIMESTAMP, curr_service VARCHAR)")
        con.execute("CREATE TABLE chartevents (stay_id INTEGER, charttime TIMESTAMP, "
                    "storetime TIMESTAMP, itemid INTEGER, valuenum DOUBLE)")
        con.execute("CREATE SCHEMA mimiciv_derived")
        con.execute("CREATE TABLE mimiciv_derived.sofa (stay_id INTEGER, endtime TIMESTAMP, "
                    "respiration_24hours INTEGER, coagulation_24hours INTEGER, liver_24hours INTEGER, "
                    "cns_24hours INTEGER, renal_24hours INTEGER, cardiovascular_24hours INTEGER)")
        con.execute("CREATE TABLE mimiciv_derived.sepsis3 (stay_id INTEGER, antibiotic_time TIMESTAMP, "
                    "culture_time TIMESTAMP, sofa_time TIMESTAMP, sepsis3 BOOLEAN)")
        for cid, stay, start_h, end_h, included in self.circuits:
            con.execute("INSERT INTO crrt_circuits VALUES (?, ?, ?, ?, ?, ?)",
                        [cid, stay, stay, stay, at(start_h), at(end_h)])
            con.execute("INSERT INTO crrt_cohort VALUES (?, ?, ?)", [cid, 60 + stay, included])
            h = start_h
            while included and h <= end_h:
                con.execute("INSERT INTO circuit_failure_labels VALUES (?, ?)", [cid, at(h)])
                h += STEP
        for stay in {c[1] for c in self.circuits}:
            con.execute("INSERT INTO patients VALUES (?, ?)", [stay, "F" if stay % 2 else "M"])
            con.execute("INSERT INTO admissions VALUES (?, ?)", [stay, self.admission_type])
        for table, rows in (("chartevents", self.chart), ("services", self.services),
                            ("mimiciv_derived.sofa", self.sofa), ("mimiciv_derived.sepsis3", self.sepsis)):
            if rows:
                con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(rows[0]))})", rows)
        build_static_features(con, cfg)
        cur = con.execute("SELECT * FROM static_features")
        cols = [d[0] for d in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    used = set(re.findall(r"getvariable\('(\w+)'\)", STATIC_FEATURES_SQL.read_text()))
    con = duckdb.connect()
    bind_static_features(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug."""
    code = "\n".join(line.split("--")[0] for line in STATIC_FEATURES_SQL.read_text().splitlines())
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


def test_every_body_size_item_has_a_bound():
    assert set(F["weight_items"]) | set(F["height_items"]) <= set(BOUNDS)


# ── Rows and the CRRT start anchor ────────────────────────────────────────


def test_one_row_per_circuit_and_every_column_without_data():
    rows = Chart().circuit(1, 0, 4).circuit(2, 6, 9).run()
    assert sorted(rows) == [1, 2]
    assert set(rows[1]) == {"circuit_id", "age_years", "sex", "weight_kg", "height_cm", "bmi",
                            "admission_type", "service", "sofa_no_cv", "sepsis3"}
    assert rows[1]["age_years"] == 61 and rows[1]["sex"] == "F"
    assert rows[1]["admission_type"] == ADMISSION_GROUP
    assert all(rows[1][k] is None for k in ("weight_kg", "height_cm", "bmi", "service", "sofa_no_cv"))
    assert rows[1]["sepsis3"] is False


def test_circuits_of_a_stay_share_values_known_at_crrt_start():
    """A weight stored after CRRT start but before the second circuit counts
    for neither: every value is the stay's at CRRT start."""
    rows = (Chart().circuit(1, 0, 4).circuit(2, 6, 9)
            .value(ADMISSION_KG, -2, WEIGHT, stored_h=5).run())
    assert rows[1]["weight_kg"] is None and rows[2]["weight_kg"] is None


def test_crrt_start_is_the_first_included_circuit():
    """A circuit outside the cohort (e.g. under the duration floor) has no
    prediction rows and does not move CRRT start."""
    rows = (Chart().circuit(1, 0, 1, included=False).circuit(2, 5, 12)
            .value(ADMISSION_KG, -1, WEIGHT, stored_h=3).run())
    assert sorted(rows) == [2]
    assert rows[2]["weight_kg"] == WEIGHT


def test_other_stays_never_count():
    rows = (Chart().circuit(1, 0, 4).circuit(2, 0, 4, stay=2)
            .value(ADMISSION_KG, -1, WEIGHT, stay=2).service(-1, SERVICE, stay=2)
            .sofa_hour(0, renal=4, stay=2).sepsis3(-3, -4, -1, stay=2).run())
    assert rows[1]["weight_kg"] is None and rows[1]["service"] is None
    assert rows[1]["sofa_no_cv"] is None and rows[1]["sepsis3"] is False
    assert rows[2]["weight_kg"] == WEIGHT and rows[2]["sepsis3"] is True


# ── Body size ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("charted_h, stored_h, counts", [
    (-1, -1, True),
    (-1, 0, True),      # stored at CRRT start exactly
    (-1, 0.5, False),   # charted before, stored after
    (0.5, 0.5, False),  # charted after
])
def test_weight_counts_only_if_charted_and_stored_by_crrt_start(charted_h, stored_h, counts):
    rows = Chart().circuit(1, 0, 4).value(ADMISSION_KG, charted_h, WEIGHT, stored_h=stored_h).run()
    assert rows[1]["weight_kg"] == (WEIGHT if counts else None)


def test_the_earliest_weight_wins():
    """The baseline weight, before CRRT-era fluid gain: an admission weight
    at ICU admission beats a later, heavier daily weight."""
    rows = (Chart().circuit(1, 24, 30)
            .value(ADMISSION_KG, 0, WEIGHT).value(DAILY_KG, 20, WEIGHT + 9).run())
    assert rows[1]["weight_kg"] == WEIGHT


def test_a_later_weight_stands_in_when_the_earliest_is_stored_late():
    """Admission weight is backdated to ICU admission and can be stored days
    later. Until it is, the pounds copy or a daily weight is used."""
    rows = (Chart().circuit(1, 24, 30)
            .value(ADMISSION_KG, 0, WEIGHT, stored_h=48)
            .value(LB, 6, WEIGHT * F["lb_per_kg"]).value(DAILY_KG, 20, WEIGHT + 9).run())
    assert rows[1]["weight_kg"] == pytest.approx(WEIGHT)


def test_out_of_bound_weight_is_ignored_and_bounds_are_inclusive():
    low, high = BOUNDS[DAILY_KG]
    assert Chart().circuit(1, 0, 4).value(DAILY_KG, -2, low - 1).value(DAILY_KG, -1, low).run()[1][
        "weight_kg"] == low
    assert Chart().circuit(1, 0, 4).value(DAILY_KG, -2, high + 1).value(DAILY_KG, -1, high).run()[1][
        "weight_kg"] == high
    lb_low = BOUNDS[LB][0]
    assert Chart().circuit(1, 0, 4).value(LB, -1, lb_low - 1).run()[1]["weight_kg"] is None


def test_values_at_one_charttime_are_averaged_and_wait_for_the_later():
    rows = (Chart().circuit(1, 0, 4)
            .value(ADMISSION_KG, -2, WEIGHT, stored_h=-2)
            .value(LB, -2, (WEIGHT + 2) * F["lb_per_kg"], stored_h=1).run())
    assert rows[1]["weight_kg"] is None
    rows = (Chart().circuit(1, 0, 4)
            .value(ADMISSION_KG, -2, WEIGHT, stored_h=-2)
            .value(LB, -2, (WEIGHT + 2) * F["lb_per_kg"], stored_h=-1).run())
    assert rows[1]["weight_kg"] == pytest.approx(WEIGHT + 1)


def test_height_from_inches_and_bmi():
    rows = (Chart().circuit(1, 0, 4).value(ADMISSION_KG, -1, WEIGHT)
            .value(INCH, -1, HEIGHT / F["cm_per_inch"]).run())
    assert rows[1]["height_cm"] == pytest.approx(HEIGHT)
    assert rows[1]["bmi"] == pytest.approx(WEIGHT / (HEIGHT / F["cm_per_m"]) ** 2)


def test_bmi_needs_both_weight_and_height():
    rows = Chart().circuit(1, 0, 4).value(CM, -1, HEIGHT).run()
    assert rows[1]["height_cm"] == HEIGHT
    assert rows[1]["weight_kg"] is None and rows[1]["bmi"] is None


def test_height_follows_the_weight_rules():
    low, high = BOUNDS[CM]
    rows = (Chart().circuit(1, 0, 4)
            .value(CM, -3, low - 1).value(CM, -2, HEIGHT, stored_h=1).value(CM, -1, high).run())
    assert rows[1]["height_cm"] == high


# ── Admission type and service ────────────────────────────────────────────


def test_every_admission_type_and_service_maps_to_its_group():
    for value, group in F["admission_type_groups"].items():
        c = Chart().circuit(1, 0, 4)
        c.admission_type = value
        assert c.run()[1]["admission_type"] == group
    for value, group in F["service_groups"].items():
        assert Chart().circuit(1, 0, 4).service(-1, value).run()[1]["service"] == group


def test_a_value_without_a_group_is_null():
    c = Chart().circuit(1, 0, 4).service(-1, "NOT A SERVICE")
    c.admission_type = "NOT A TYPE"
    row = c.run()[1]
    assert row["admission_type"] is None and row["service"] is None


def test_service_is_the_last_transfer_at_or_before_crrt_start():
    rows = (Chart().circuit(1, 10, 14)
            .service(0, OTHER_SERVICE).service(10, SERVICE).service(11, OTHER_SERVICE).run())
    assert rows[1]["service"] == SERVICE_GROUP


# ── Scores ────────────────────────────────────────────────────────────────


def test_sofa_is_the_last_hour_at_or_before_crrt_start_without_cardiovascular():
    rows = (Chart().circuit(1, 10.5, 14)
            .sofa_hour(9, resp=4, renal=4)
            .sofa_hour(10, resp=1, coag=2, liver=3, cns=1, renal=4, cv=4)
            .sofa_hour(11, resp=4, coag=4, liver=4, cns=4, renal=4, cv=4).run())
    assert rows[1]["sofa_no_cv"] == 1 + 2 + 3 + 1 + 4


def test_sofa_is_null_without_an_hour_by_crrt_start():
    """E.g. CRRT charted before the stay's first heart rate, where
    mimic-code's hourly grid begins."""
    rows = Chart().circuit(1, 10, 14).sofa_hour(11, renal=4).run()
    assert rows[1]["sofa_no_cv"] is None


@pytest.mark.parametrize("antibiotic_h, culture_h, sofa_h, sepsis", [
    (-3, -5, -1, True),
    (-3, -5, 0, True),     # every time at CRRT start or before
    (2, -5, -1, False),    # culture before, antibiotic after: not yet suspected
    (-3, 2, -1, False),    # antibiotic before, culture after
    (-3, -5, 2, False),    # SOFA >= 2 only after CRRT start
])
def test_sepsis3_needs_every_time_by_crrt_start(antibiotic_h, culture_h, sofa_h, sepsis):
    rows = Chart().circuit(1, 0, 4).sepsis3(antibiotic_h, culture_h, sofa_h).run()
    assert rows[1]["sepsis3"] is sepsis
