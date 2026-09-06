"""Guards on the itemid evidence sweep (Plan Part 2.3).

The sweep is supposed to be over-inclusive. The risk it carries is the
opposite of a bug that shouts: someone tightens `label_patterns` to reduce
noise, an itemid silently stops being a candidate, and a variable quietly
disappears from the study. The recall test below is the tripwire for that.
"""

import pytest

from crrt import config
from crrt.itemid_inventory import CHANNELS, candidates

duckdb = pytest.importorskip("duckdb")

CFG = config.load()
DB = config.path(CFG, "duckdb")

needs_db = pytest.mark.skipif(
    not DB.exists(), reason=f"{DB} not built; run `python -m crrt.build_db`"
)


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def test_every_event_table_has_a_declared_channel():
    """A d_items.linksto with no CHANNELS entry would crash the sweep."""
    assert set(CHANNELS) == {
        "chartevents", "procedureevents", "outputevents",
        "inputevents", "ingredientevents", "datetimeevents",
    }


@needs_db
def test_sweep_rediscovers_the_whole_mimic_code_crrt_concept(con):
    """Part 2.3 says start from concepts/treatment/crrt.sql and extend it.

    Extending means the sweep is a superset. If this fails, `label_patterns`
    or `seed_category` was narrowed and the sweep now misses a validated
    CRRT itemid.
    """
    inv = CFG["itemid_inventory"]
    found = {c["itemid"] for c in candidates(con, inv)}
    missing = set(inv["mimic_code_crrt_itemids"]) - found
    assert not missing, f"sweep no longer finds validated CRRT itemids: {sorted(missing)}"


@needs_db
def test_sweep_finds_the_newer_circuit_pressure_items(con):
    """229247 TMP and 229248 Pressure Drop are absent from the mimic-code
    concept but are the flow-adjusted pressure parameters Part 7 names as the
    differentiator. They must not fall out of the candidate set."""
    found = {c["itemid"] for c in candidates(con, CFG["itemid_inventory"])}
    assert {229247, 229248} <= found


@needs_db
def test_candidates_are_unique_per_itemid(con):
    cands = candidates(con, CFG["itemid_inventory"])
    assert len(cands) == len({c["itemid"] for c in cands})
