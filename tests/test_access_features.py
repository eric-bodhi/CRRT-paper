"""The vascular access features (sql/access_features.sql) on hand-built
circuits.

Each test charts a few catheter rows whose correct features are obvious by
construction. No MIMIC data is read. Times are hours after an arbitrary
origin at midnight, so the date of hour h is ORIGIN's date for 0 <= h < 24;
the catheter vocabularies come from config/config.yaml.
"""

import re
from datetime import date, datetime, timedelta

import pytest

from crrt import config
from crrt.features import ACCESS_FEATURES_SQL, bind_access_features, build_access_features

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
F = CFG["features"]
TYPES = F["access_catheter_types"]
INSERTION = F["access_insertion_date_itemid"]
STEP = CFG["prediction"]["step_hours"]
ORIGIN = datetime(2150, 1, 1)

# One charted value of each harmonised type, from the first vocabulary.
OLD, NEW = list(TYPES)
TUNNELED = next(v for v, t in TYPES[OLD].items() if t == "tunneled")
TEMPORARY = next(v for v, t in TYPES[OLD].items() if t == "temporary")


def at(h: float) -> datetime:
    return ORIGIN + timedelta(hours=h)


def day(d: int) -> date:
    return ORIGIN.date() + timedelta(days=d)


class Chart:
    """Synthetic crrt_circuits, circuit_failure_labels, chartevents and
    datetimeevents rows. Every circuit is on stay 1 unless given another."""

    def __init__(self):
        self.circuits: list[tuple] = []
        self.types: list[tuple] = []
        self.insertions: list[tuple] = []

    def circuit(self, cid: int, start_h: float, end_h: float, stay: int = 1):
        self.circuits.append((cid, stay, start_h, end_h))
        return self

    def type(self, h: float, value: str, itemid: int = OLD, stored_h: float | None = None,
             stay: int = 1):
        self.types.append((stay, at(h), at(h if stored_h is None else stored_h), itemid, value))
        return self

    def inserted(self, h: float, on: date | datetime, stored_h: float | None = None,
                 stay: int = 1):
        if not isinstance(on, datetime):
            on = datetime.combine(on, datetime.min.time())
        self.insertions.append(
            (stay, at(h), at(h if stored_h is None else stored_h), INSERTION, on))
        return self

    def run(self, cfg=CFG) -> dict[tuple[int, float], dict]:
        con = duckdb.connect()
        con.execute("CREATE TABLE crrt_circuits (circuit_id INTEGER, stay_id INTEGER, "
                    "circuit_start TIMESTAMP, circuit_end TIMESTAMP)")
        con.execute("CREATE TABLE circuit_failure_labels (circuit_id INTEGER, pred_time TIMESTAMP)")
        con.execute("CREATE TABLE chartevents (stay_id INTEGER, charttime TIMESTAMP, "
                    "storetime TIMESTAMP, itemid INTEGER, value VARCHAR)")
        con.execute("CREATE TABLE datetimeevents (stay_id INTEGER, charttime TIMESTAMP, "
                    "storetime TIMESTAMP, itemid INTEGER, value TIMESTAMP)")
        for cid, stay, start_h, end_h in self.circuits:
            con.execute("INSERT INTO crrt_circuits VALUES (?, ?, ?, ?)",
                        [cid, stay, at(start_h), at(end_h)])
            h = start_h
            while h <= end_h:
                con.execute("INSERT INTO circuit_failure_labels VALUES (?, ?)", [cid, at(h)])
                h += STEP
        if self.types:
            con.executemany("INSERT INTO chartevents VALUES (?, ?, ?, ?, ?)", self.types)
        if self.insertions:
            con.executemany("INSERT INTO datetimeevents VALUES (?, ?, ?, ?, ?)", self.insertions)
        build_access_features(con, cfg)
        cur = con.execute("SELECT * FROM access_features")
        cols = [d[0] for d in cur.description]
        out = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out[(r["circuit_id"], (r["pred_time"] - ORIGIN) / timedelta(hours=1))] = r
        return out


# ── Parameter binding ─────────────────────────────────────────────────────


def test_every_sql_variable_is_bound():
    used = set(re.findall(r"getvariable\('(\w+)'\)", ACCESS_FEATURES_SQL.read_text()))
    con = duckdb.connect()
    bind_access_features(con, CFG)
    unset = {v for v in used if con.execute(f"SELECT getvariable('{v}')").fetchone()[0] is None}
    assert used and not unset, f"unbound SQL variables: {sorted(unset)}"


def test_sql_has_no_numeric_literals():
    """CLAUDE.md: a number typed into a .sql file is a bug. Allowed: the unit
    INTERVAL '1 hour'."""
    code = "\n".join(line.split("--")[0] for line in ACCESS_FEATURES_SQL.read_text().splitlines())
    code = code.replace("INTERVAL '1 hour'", "")
    assert not re.findall(r"\b\d+(?:\.\d+)?\b", code)


# ── Rows and columns ──────────────────────────────────────────────────────


def test_one_row_per_prediction_row_and_every_column_without_data():
    rows = Chart().circuit(1, 0, 4).run()
    assert sorted(rows) == [(1, k * STEP) for k in range(int(4 / STEP) + 1)]
    assert set(rows[(1, 4)]) == {
        "circuit_id", "pred_time", "catheter_type_last", "catheter_type_hours_since_last",
        "catheter_age_days", "catheter_insertion_date_hours_since_last"}
    assert all(v is None for k, v in rows[(1, 4)].items() if k not in ("circuit_id", "pred_time"))


# ── Catheter type ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("itemid,value", [(i, v) for i in TYPES for v in TYPES[i]])
def test_every_listed_value_is_harmonised_to_its_type(itemid, value):
    rows = Chart().circuit(1, 0, 2).type(1, value, itemid=itemid).run()
    assert rows[(1, 2)]["catheter_type_last"] == TYPES[itemid][value]


def test_both_vocabularies_map_to_the_same_two_types():
    assert {t for values in TYPES.values() for t in values.values()} == {"tunneled", "temporary"}
    for values in TYPES.values():
        assert set(values.values()) == {"tunneled", "temporary"}


def test_an_unlisted_value_is_skipped_not_read_as_the_latest():
    rows = (Chart().circuit(1, 0, 4)
            .type(1, TUNNELED).type(2, "Other/Remarks").run())
    assert rows[(1, 2)]["catheter_type_last"] == "tunneled"
    assert rows[(1, 2)]["catheter_type_hours_since_last"] == 1


def test_a_value_of_one_vocabulary_on_the_other_item_is_skipped():
    """A value matches only under its own itemid."""
    rows = Chart().circuit(1, 0, 2).type(1, TUNNELED, itemid=NEW).run()
    assert rows[(1, 2)]["catheter_type_last"] is None


def test_type_counts_only_once_stored():
    rows = Chart().circuit(1, 0, 4).type(1, TUNNELED, stored_h=2.5).run()
    assert rows[(1, 2)]["catheter_type_last"] is None
    assert rows[(1, 3)]["catheter_type_last"] == "tunneled"
    assert rows[(1, 3)]["catheter_type_hours_since_last"] == 2


def test_latest_charting_wins_across_vocabularies():
    rows = (Chart().circuit(1, 0, 6)
            .type(1, TUNNELED, itemid=OLD)
            .type(3, next(v for v, t in TYPES[NEW].items() if t == "temporary"), itemid=NEW)
            .run())
    assert rows[(1, 2)]["catheter_type_last"] == "tunneled"
    assert rows[(1, 6)]["catheter_type_last"] == "temporary"
    assert rows[(1, 6)]["catheter_type_hours_since_last"] == 3


def test_an_earlier_charting_stored_later_does_not_replace_the_latest():
    rows = (Chart().circuit(1, 0, 6)
            .type(1, TEMPORARY, stored_h=4.5).type(2, TUNNELED).run())
    assert rows[(1, 5)]["catheter_type_last"] == "tunneled"


def test_type_charted_before_the_circuit_counts_however_long_before():
    """A catheter property, not a filter property: the whole stay counts."""
    rows = Chart().circuit(1, 100, 102).type(1, TUNNELED).run()
    assert rows[(1, 100)]["catheter_type_last"] == "tunneled"
    assert rows[(1, 100)]["catheter_type_hours_since_last"] == 99


def test_other_stays_never_count():
    rows = (Chart().circuit(1, 0, 2).type(1, TUNNELED, stay=2).inserted(1, day(0), stay=2)
            .run())
    assert rows[(1, 2)]["catheter_type_last"] is None
    assert rows[(1, 2)]["catheter_age_days"] is None


# ── Catheter age ──────────────────────────────────────────────────────────


def test_age_is_whole_days_from_the_insertion_date_to_the_date_of_pred_time():
    rows = Chart().circuit(1, 20, 30).inserted(20, day(-3)).run()
    assert rows[(1, 20)]["catheter_age_days"] == 3
    assert rows[(1, 23)]["catheter_age_days"] == 3
    assert rows[(1, 24)]["catheter_age_days"] == 4
    assert rows[(1, 30)]["catheter_age_days"] == 4
    assert rows[(1, 30)]["catheter_insertion_date_hours_since_last"] == 10


def test_a_time_on_the_insertion_date_is_ignored():
    """The item is a date; the few values with a time are read as their date."""
    rows = Chart().circuit(1, 1, 2).inserted(1, at(-1)).run()
    assert rows[(1, 1)]["catheter_age_days"] == 1


def test_insertion_date_counts_only_once_stored():
    rows = Chart().circuit(1, 0, 4).inserted(1, day(-2), stored_h=2.5).run()
    assert rows[(1, 2)]["catheter_age_days"] is None
    assert rows[(1, 3)]["catheter_age_days"] == 2


def test_latest_charted_insertion_date_wins():
    """A new catheter: its date replaces the old one's once charted."""
    rows = (Chart().circuit(1, 0, 6)
            .inserted(1, day(-5)).inserted(3, day(0)).run())
    assert rows[(1, 2)]["catheter_age_days"] == 5
    assert rows[(1, 6)]["catheter_age_days"] == 0


def test_an_insertion_date_after_its_charting_date_is_skipped():
    rows = (Chart().circuit(1, 0, 4)
            .inserted(1, day(-2)).inserted(2, day(1)).run())
    assert rows[(1, 4)]["catheter_age_days"] == 2
    assert rows[(1, 4)]["catheter_insertion_date_hours_since_last"] == 3


def test_insertion_date_counts_on_every_circuit_of_the_stay():
    rows = Chart().circuit(1, 0, 2).circuit(2, 3, 5).inserted(1, day(0)).run()
    assert rows[(2, 3)]["catheter_age_days"] == 0
