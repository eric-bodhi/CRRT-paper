"""The hypophosphatemia prediction rows (sql/hypophos_labels.sql) on
hand-built patients.

Each test builds one patient with one circuit from hour 0 and a few
phosphate results, so the correct labels are obvious by construction. No
MIMIC data is read. Times are hours after an arbitrary origin; the
threshold, horizon and maximum result age come from config/config.yaml.
"""

import re
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.outcomes import HYPOPHOS_SQL, bind_hypophos, build_hypophos

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
HP = CFG["outcomes"]["hypophosphatemia"]
ORIGIN = datetime(2150, 1, 1)
THRESHOLD = HP["moderate_mg_dl"]
H = HP["horizon_hours"]
MAX_AGE = HP["known_value_max_age_hours"]
PHOS = HP["phosphate_itemid"]
ORDERS = HP["repletion_orders"]
IV_DRUG = next(d for d, routes in ORDERS.items() if "IV" in routes)
ORAL_DRUG = next(d for d, routes in ORDERS.items() if "IV" not in routes)
ORAL_ROUTE = ORDERS[ORAL_DRUG][0]
NORMAL = THRESHOLD + 1
LOW = THRESHOLD - 0.5
# Results are stored this long after the draw (feasibility §3: 76 min median).
LAG = 1.25


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


class Patient:
    """One patient, admission, stay and included circuit, numbered 1."""

    def __init__(self, end_h: float = 60):
        self.end_h = end_h
        self.labs: list[tuple] = []
        self.orders: list[tuple] = []
        self.death_h: float | None = None
        self.included = True

    def phos(self, h: float, value: float, lag: float = LAG):
        self.labs.append((at(h), at(h + lag), value))
        return self

    def every(self, start: float, stop: float, every: float, value: float = NORMAL):
        h = start
        while h <= stop:
            self.phos(h, value)
            h += every
        return self

    def dose(self, h: float):
        """An IV phosphate order starting at hour h."""
        return self.order(h, IV_DRUG, "IV")

    def order(self, h: float, drug: str = ORAL_DRUG, route: str = ORAL_ROUTE):
        """A prescription starting at hour h. MIMIC capitalises drug names."""
        self.orders.append((drug.title(), route, at(h)))
        return self

    def dies(self, h: float):
        self.death_h = h
        return self

    def run(self, cfg: dict = CFG) -> dict[float, dict]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, subject_id INTEGER, "
                    "hadm_id INTEGER, stay_id INTEGER, circuit_start TIMESTAMP, "
                    "circuit_end TIMESTAMP)")
        con.execute("CREATE TABLE crrt_cohort (circuit_id INTEGER, included BOOLEAN)")
        con.execute("CREATE TABLE labevents (subject_id INTEGER, itemid INTEGER, "
                    "charttime TIMESTAMP, storetime TIMESTAMP, valuenum DOUBLE)")
        con.execute("CREATE TABLE prescriptions (subject_id INTEGER, drug VARCHAR, "
                    "route VARCHAR, starttime TIMESTAMP)")
        con.execute("CREATE TABLE admissions (hadm_id INTEGER, deathtime TIMESTAMP)")
        con.execute("INSERT INTO crrt_circuits VALUES (1, 1, 1, 1, ?, ?)", [ORIGIN, at(self.end_h)])
        con.execute("INSERT INTO crrt_cohort VALUES (1, ?)", [self.included])
        con.execute("INSERT INTO admissions VALUES (1, ?)",
                    [at(self.death_h) if self.death_h is not None else None])
        for charttime, storetime, v in self.labs:
            con.execute("INSERT INTO labevents VALUES (1, ?, ?, ?, ?)", [PHOS, charttime, storetime, v])
        for drug, route, start in self.orders:
            con.execute("INSERT INTO prescriptions VALUES (1, ?, ?, ?)", [drug, route, start])
        build_hypophos(con, cfg)
        cur = con.execute("SELECT * FROM hypophos_labels ORDER BY pred_time")
        cols = [d[0] for d in cur.description]
        return {(r["pred_time"] - ORIGIN).total_seconds() / 3600: r
                for r in (dict(zip(cols, row)) for row in cur.fetchall())}


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    used = set(re.findall(r"getvariable\('(\w+)'\)", HYPOPHOS_SQL.read_text()))
    con = duckdb.connect()
    bind_hypophos(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    code = "\n".join(line.split("--")[0] for line in HYPOPHOS_SQL.read_text().splitlines())
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


def test_thresholds_are_ordered():
    assert HP["severe_mg_dl"] < HP["sensitivity_mg_dl"] < HP["moderate_mg_dl"]


# ── At risk ───────────────────────────────────────────────────────────────


def test_a_result_is_known_only_once_stored():
    rows = Patient().phos(2, NORMAL).every(8, 60, 6).run()
    assert rows[2]["not_scored_reason"] == "no_known_value"
    assert rows[3]["not_scored_reason"] == "no_known_value"   # drawn at 2, stored at 3.25
    assert rows[4]["scored"] and rows[4]["known_value"] == NORMAL


def test_a_result_older_than_the_maximum_age_is_not_known():
    rows = Patient().phos(0, NORMAL).run()
    assert rows[MAX_AGE]["scored"]
    assert rows[MAX_AGE + 1]["not_scored_reason"] == "no_known_value"


def test_low_before_crrt_is_not_at_risk_until_a_normal_result_is_known():
    rows = Patient().phos(-3, LOW).phos(5, NORMAL).every(11, 60, 6).run()
    assert rows[0]["not_scored_reason"] == "known_low"
    assert rows[6]["not_scored_reason"] == "known_low"        # drawn at 5, stored at 6.25
    assert rows[7]["scored"]


def test_value_at_the_threshold_is_not_low():
    rows = Patient(end_h=10).phos(-1, THRESHOLD).every(5, 40, 5, THRESHOLD).run()
    assert rows[1]["scored"]
    assert rows[1]["label"] is False


# ── Labels ────────────────────────────────────────────────────────────────


def test_rows_within_the_horizon_of_the_first_low_draw_are_positive():
    low_h = 40
    rows = Patient().phos(-1, NORMAL).every(5, low_h - 1, 6).phos(low_h, LOW).every(46, 60, 6).run()
    for h, r in rows.items():
        if h >= low_h:
            assert r["not_scored_reason"] == "already_low", h
        elif r["scored"]:
            assert r["label"] is (low_h - h <= H), h


def test_unstored_low_draw_already_counts():
    """The patient is below threshold from the draw, whether or not the
    result is back. Scoring such a row would ask about an event already
    past."""
    rows = Patient().phos(-1, NORMAL).phos(3, LOW, lag=5).run()
    assert rows[4]["not_scored_reason"] == "already_low"


def test_repletion_before_the_low_draw_censors():
    low_h, dose_h = 20, 15
    rows = Patient().phos(-1, NORMAL).every(5, 19, 6).phos(low_h, LOW).dose(dose_h).run()
    assert rows[10]["label"] is None and rows[10]["censor_reason"] == "repletion"
    assert rows[16]["label"] is True and rows[16]["censor_reason"] is None


def test_repletion_after_the_low_draw_does_not_censor():
    rows = Patient().phos(-1, NORMAL).every(5, 17, 6).phos(18, LOW).dose(19).run()
    assert rows[10]["label"] is True


def test_death_in_the_window_censors():
    death = 30
    rows = Patient(end_h=death - 1).every(-1, death - 2, 6).dies(death).run()
    assert rows[death - H]["label"] is None
    assert rows[death - H]["censor_reason"] == "competing_risk"


def test_window_with_no_draw_is_censored_not_negative():
    rows = Patient(end_h=10).phos(-1, NORMAL).run()
    assert rows[1]["label"] is None and rows[1]["censor_reason"] == "unmeasured"


def test_window_with_only_normal_draws_is_negative():
    rows = Patient().every(-1, 60, 6).run()
    assert rows[1]["label"] is False and rows[1]["censor_reason"] is None


# ── Oral repletion ────────────────────────────────────────────────────────


def low_at_20() -> Patient:
    return Patient().phos(-1, NORMAL).every(5, 19, 6).phos(20, LOW)


def test_new_oral_order_before_the_low_draw_censors():
    rows = low_at_20().order(15).run()
    assert rows[10]["label"] is None and rows[10]["censor_reason"] == "repletion"
    assert rows[16]["label"] is True


def test_oral_order_started_before_t_does_not_censor():
    """Ongoing supplements are known at t: a feature, not a new decision."""
    rows = low_at_20().order(5).run()
    assert rows[10]["label"] is True and rows[10]["censor_reason"] is None


@pytest.mark.parametrize("drug, route", [
    ("caphosol", ORAL_ROUTE),               # mouth rinse
    ("codeine phosphate", ORAL_ROUTE),      # phosphate salt of another drug
    (ORAL_DRUG, "IV"),                      # not one of its routes
    (IV_DRUG, ORAL_ROUTE),                  # not one of its routes
])
def test_other_phosphate_named_orders_do_not_censor(drug, route):
    rows = low_at_20().order(15, drug, route).run()
    assert rows[10]["label"] is True


# ── Repletion handling (sensitivity analyses) ─────────────────────────────


def with_repletion_handling(handling: str) -> dict:
    return {**CFG, "outcomes": {**CFG["outcomes"], "hypophosphatemia": {
        **HP, "repletion_handling_primary": handling}}}


def test_repletion_handling_bounds_the_censor():
    """A dose at 15 h with only normal draws after it: a prevented event,
    or no event at all. Censor drops the row, ignore calls it negative,
    composite calls it the event. Row 16 has no new order in its window and
    is negative under every handling."""
    def patient() -> Patient:
        return Patient().every(-1, 60, 6).dose(15)

    handlings = {"censor": (None, "repletion"), "ignore": (False, None), "composite": (True, None)}
    assert set(handlings) == {HP["repletion_handling_primary"], *HP["repletion_handling_sensitivity"]}
    for handling, (label, reason) in handlings.items():
        rows = patient().run(with_repletion_handling(handling))
        assert (rows[10]["label"], rows[10]["censor_reason"]) == (label, reason), handling
        assert (rows[16]["label"], rows[16]["censor_reason"]) == (False, None), handling


@pytest.mark.parametrize("handling", ["ignore", "composite"])
def test_repletion_before_the_low_draw_is_positive_unless_censored(handling):
    rows = low_at_20().order(15).run(with_repletion_handling(handling))
    assert rows[10]["label"] is True and rows[10]["censor_reason"] is None


@pytest.mark.parametrize("handling", ["ignore", "composite"])
def test_repletion_handling_leaves_rows_without_repletion_alone(handling):
    rows = Patient().phos(-1, NORMAL).every(5, 17, 6).phos(18, LOW).dose(19).run(
        with_repletion_handling(handling))
    assert rows[10]["label"] is True
    rows = Patient().every(-1, 60, 6).run(with_repletion_handling(handling))
    assert rows[1]["label"] is False and rows[1]["censor_reason"] is None
