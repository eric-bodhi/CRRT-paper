"""Guards on the itemid evidence sweep (Plan Part 2.3).

The sweep is supposed to be over-inclusive. The risk it carries is the
opposite of a bug that shouts: someone tightens `label_patterns` to reduce
noise, an itemid silently stops being a candidate, and a variable quietly
disappears from the study. The recall test below is the tripwire for that.
"""

import pytest

from crrt import config
from crrt.itemid_inventory import CHANNELS, REVIEW_PATH, candidates

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


# ── Small-cell suppression (Part 1.4) ─────────────────────────────────────
# docs/itemids.md is committed, so nothing in it may describe fewer than
# `reporting.small_cell_threshold` rows or stays. These run on a synthetic
# database, so they need no MIMIC data.

SMALL = CFG["reporting"]["small_cell_threshold"]
RARE_TEXT = "rare free text that must not be published"


@pytest.fixture(scope="module")
def synthetic_doc():
    from crrt.itemid_inventory import render

    c = duckdb.connect()
    c.execute("CREATE TABLE d_items (itemid INTEGER, label VARCHAR, abbreviation VARCHAR, "
              "linksto VARCHAR, category VARCHAR, unitname VARCHAR, param_type VARCHAR)")
    c.execute("CREATE TABLE icustays (subject_id INTEGER, stay_id INTEGER)")
    c.execute("CREATE TABLE chartevents (stay_id INTEGER, itemid INTEGER, value VARCHAR, "
              "valuenum DOUBLE, valueuom VARCHAR)")
    for t in ["procedureevents", "outputevents"]:
        c.execute(f"CREATE TABLE {t} (stay_id INTEGER, itemid INTEGER, value DOUBLE, valueuom VARCHAR)")
    for t in ["inputevents", "ingredientevents"]:
        c.execute(f"CREATE TABLE {t} (stay_id INTEGER, itemid INTEGER, amount DOUBLE, "
                  "amountuom VARCHAR, rate DOUBLE, rateuom VARCHAR)")
    c.execute("CREATE TABLE datetimeevents (stay_id INTEGER, itemid INTEGER, value TIMESTAMP, "
              "valueuom VARCHAR)")

    seed = CFG["itemid_inventory"]["seed_category"]
    rare_numeric, text_item, common_numeric = 1, 2, 3
    c.executemany("INSERT INTO d_items VALUES (?, ?, NULL, 'chartevents', ?, NULL, ?)", [
        (rare_numeric, "rare numeric", seed, "Numeric"),
        (text_item, "text item", seed, "Text"),
        (common_numeric, "common numeric", seed, "Numeric"),
    ])
    # The stay-count query expects at least one seed-category procedure item,
    # as the real d_items always has.
    c.execute("INSERT INTO d_items VALUES (4, 'procedure item', NULL, 'procedureevents', ?, "
              "NULL, 'Process')", [seed])
    stays = range(SMALL * 2)
    c.executemany("INSERT INTO icustays VALUES (?, ?)", [(s, s) for s in stays])
    rows = [(0, rare_numeric, "7", 7.0, "mmHg"), (1, rare_numeric, "8", 8.0, "mmHg")]
    rows += [(s, text_item, "Clotted", None, None) for s in stays]
    rows += [(0, text_item, RARE_TEXT, None, None)]
    rows += [(s, common_numeric, str(s), float(s), "ml/hr") for s in stays]
    c.executemany("INSERT INTO chartevents VALUES (?, ?, ?, ?, ?)", rows)
    review = {
        rare_numeric: {"verdict": "include", "roles": ["feature"], "reason": "kept for a test"},
        text_item: {"verdict": "exclude", "reason": "dropped for a test"},
    }
    return render(CFG, c, review)


def table_cells(doc: str) -> list[str]:
    return [cell.strip() for line in doc.splitlines() if line.startswith("|")
            for cell in line.strip("|").split("|")]


def test_no_small_count_is_printed(synthetic_doc):
    """Bare integers 1..SMALL-1 in a table cell would be unsuppressed counts.
    (Ids 1-3 sit in the itemid column, so only count columns are checked.)"""
    rare_row = next(l for l in synthetic_doc.splitlines() if "| rare numeric |" in l)
    cells = [c.strip().strip("*") for c in rare_row.strip("|").split("|")]
    n_rows, n_stays, n_num = cells[6:9]
    assert (n_rows, n_stays, n_num) == (f"<{SMALL}",) * 3
    assert f"mmHg (<{SMALL})" in rare_row


def test_percentiles_withheld_for_small_samples(synthetic_doc):
    rare_row = next(l for l in synthetic_doc.splitlines() if "| rare numeric |" in l)
    p5, p50, p95 = [c.strip() for c in rare_row.strip("|").split("|")][10:13]
    assert (p5, p50, p95) == ("—", "—", "—")
    common_row = next(l for l in synthetic_doc.splitlines() if "| common numeric |" in l)
    assert [c.strip() for c in common_row.strip("|").split("|")][10:13] != ["—"] * 3


def test_rare_text_values_are_not_published(synthetic_doc):
    assert RARE_TEXT not in synthetic_doc
    assert f"`Clotted` ({SMALL * 2:,})" in synthetic_doc
    assert "not listed" in synthetic_doc


def test_output_does_not_claim_to_be_the_demo(synthetic_doc):
    assert "Demo 2.2" not in synthetic_doc
    assert CFG["paths"]["mimic_dir"] in synthetic_doc


# ── Hand review (config/itemid_review.yaml) ───────────────────────────────
# docs/itemids.md is regenerated on every run, so the verdicts live in the
# review file and are copied in. These guard that copy, and that no candidate
# reaches the pipeline without a verdict.


def test_verdicts_are_copied_into_the_include_column(synthetic_doc):
    lines = synthetic_doc.splitlines()
    first_cell = {name: next(l for l in lines if f"| {name} |" in l).split("|")[1].strip()
                  for name in ("rare numeric", "text item", "common numeric")}
    assert first_cell["rare numeric"] == "**include** (feature): kept for a test"
    assert first_cell["text item"] == "exclude: dropped for a test"
    assert first_cell["common numeric"] == "**UNREVIEWED**"
    assert "2 candidate(s) are UNREVIEWED: 3, 4." in synthetic_doc


def test_review_file_is_well_formed():
    import yaml
    items = yaml.safe_load(REVIEW_PATH.read_text())["items"]
    for itemid, v in items.items():
        assert v["verdict"] in ("include", "exclude"), itemid
        assert v["reason"].strip(), itemid
        if v["verdict"] == "include":
            assert v.get("roles"), f"{itemid} is included without a role"


@needs_db
def test_every_candidate_has_a_verdict_and_every_verdict_a_candidate(con):
    """Part 2.3: no itemid enters the study without being eyeballed. A new
    pattern or a new MIMIC release that adds a candidate fails here until
    the candidate is reviewed."""
    import yaml
    items = yaml.safe_load(REVIEW_PATH.read_text())["items"]
    found = {c["itemid"] for c in candidates(con, CFG["itemid_inventory"])}
    assert not found - set(items), f"unreviewed: {sorted(found - set(items))}"
    assert not set(items) - found, f"stale verdicts: {sorted(set(items) - found)}"
