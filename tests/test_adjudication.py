"""The adjudication sample draw (crrt.adjudication) on hand-built circuits.

Every termination class gets a frame a few circuits larger than its stratum
needs, so which circuits may be drawn is obvious by construction. No MIMIC
data is read. Stratum sizes and the seed come from config/config.yaml.
"""

import copy
from datetime import datetime, timedelta

import pytest

from crrt import config
from crrt.adjudication import draw, fingerprint

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
O = CFG["outcomes"]["circuit_failure"]
STRATA = O["adjudication_strata"]
CENSORED = O["competing_risk_classes"]
ORIGIN = datetime(2150, 1, 1)
SPARE = 5


def world(cfg=CFG, extra_per_stratum: int = SPARE) -> duckdb.DuckDBPyConnection:
    """Each stratum's classes share circuits + extra_per_stratum included
    circuits. Every censored class gets the same number again, and every
    stratum gets one excluded circuit of its first class."""
    con = duckdb.connect()
    con.execute("CREATE TABLE crrt_circuits (circuit_id BIGINT, subject_id INTEGER, "
                "stay_id INTEGER, circuit_start TIMESTAMP, circuit_end TIMESTAMP, "
                "termination_class VARCHAR)")
    con.execute("CREATE TABLE crrt_cohort (circuit_id BIGINT, included BOOLEAN)")
    circuits, cohort = [], []

    def add(cls: str, included: bool) -> None:
        i = len(circuits) + 1
        start = ORIGIN + timedelta(days=i)
        # Two circuits per patient, as in MIMIC: patients are not circuits.
        circuits.append((i, (i + 1) // 2, i, start, start + timedelta(hours=24), cls))
        cohort.append((i, included))

    for s in cfg["outcomes"]["circuit_failure"]["adjudication_strata"].values():
        n = s["circuits"] + extra_per_stratum
        for k in range(n):
            add(s["classes"][k % len(s["classes"])], True)
        add(s["classes"][0], False)
    for cls in CENSORED:
        for _ in range(max(s["circuits"] for s in STRATA.values()) + SPARE):
            add(cls, True)
    con.executemany("INSERT INTO crrt_circuits VALUES (?, ?, ?, ?, ?, ?)", circuits)
    con.executemany("INSERT INTO crrt_cohort VALUES (?, ?)", cohort)
    return con


def sample(con) -> list[dict]:
    cur = con.execute("SELECT * FROM adjudication_sample ORDER BY review_order")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


@pytest.fixture
def drawn():
    con = world()
    draw(con, CFG)
    return con


def test_each_stratum_draws_its_configured_count(drawn):
    by = {}
    for r in sample(drawn):
        by[r["stratum"]] = by.get(r["stratum"], 0) + 1
    assert by == {name: s["circuits"] for name, s in STRATA.items()}


def test_circuits_come_from_their_stratum_classes_only(drawn):
    for r in sample(drawn):
        assert r["termination_class"] in STRATA[r["stratum"]]["classes"]


def test_excluded_and_censored_circuits_are_never_drawn(drawn):
    excluded = {r[0] for r in drawn.execute(
        "SELECT circuit_id FROM crrt_cohort WHERE NOT included").fetchall()}
    for r in sample(drawn):
        assert r["circuit_id"] not in excluded
        assert r["termination_class"] not in CENSORED


def test_weight_is_frame_size_over_circuits_drawn(drawn):
    for r in sample(drawn):
        n = STRATA[r["stratum"]]["circuits"]
        assert r["frame_circuits"] == n + SPARE
        assert r["weight"] == pytest.approx((n + SPARE) / n)


def test_review_order_is_a_permutation_that_mixes_strata(drawn):
    rows = sample(drawn)
    assert [r["review_order"] for r in rows] == list(range(1, len(rows) + 1))
    # Sorted by stratum, the order would tell the adjudicator the stratum.
    strata_in_order = [r["stratum"] for r in rows]
    assert strata_in_order != sorted(strata_in_order, key=list(STRATA).index)


def test_the_same_seed_draws_the_same_sample():
    a, b = world(), world()
    draw(a, CFG)
    draw(b, CFG)
    assert sample(a) == sample(b)
    assert fingerprint(a) == fingerprint(b)


def test_another_seed_draws_another_sample(drawn):
    cfg = copy.deepcopy(CFG)
    cfg["reproducibility"]["random_seed"] += 1
    other = world()
    draw(other, cfg)
    assert fingerprint(other) != fingerprint(drawn)


def test_a_stratum_larger_than_its_frame_fails():
    con = world(extra_per_stratum=-1)
    with pytest.raises(ValueError, match="frame is smaller"):
        draw(con, CFG)
