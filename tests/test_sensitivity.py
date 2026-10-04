"""The sensitivity runner (crrt.sensitivity) on the real config and a
synthetic database. No MIMIC data is read."""

import pytest

from crrt import config
from crrt.sensitivity import EVERY_STAGE, Analysis, analyses, build, check_same_grid

duckdb = pytest.importorskip("duckdb")

CFG = config.load()

# Every sensitivity key in the config, and where it is handled. A key added
# to the config without an entry here fails test_every_sensitivity_key_is_handled,
# so no sensitivity analysis can be specified and then silently never run.
BUILT = {
    "prediction.horizon_hours_sensitivity",
    "prediction.blanking_minutes_sensitivity",
    "outcomes.circuit_failure.event_classes_sensitivity",
    "outcomes.circuit_failure.unclear_handling_sensitivity",
    "outcomes.hypophosphatemia.sensitivity_mg_dl",
    "outcomes.hypophosphatemia.repletion_handling_sensitivity",
    "circuits.max_downtime_hours_sensitivity",
    "sessionization.gap_hours_sensitivity",
}
ELSEWHERE = {
    # A column of crrt_cohort (chronic_dialysis_sensitivity), built in stage 3.
    "cohort.chronic_dialysis.same_admission_icd_sensitivity",
    # A row filter on that flag, applied at model fitting. Nothing to build.
    "cohort.esrd_handling_sensitivity",
}


def sensitivity_keys(node, prefix=""):
    for key, value in node.items():
        path = f"{prefix}{key}"
        if "sensitivity" in str(key):
            yield path
        elif isinstance(value, dict):
            yield from sensitivity_keys(value, path + ".")


def changed(a: dict, b: dict, prefix="") -> list[str]:
    out = []
    for key in a.keys() | b.keys():
        if isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
            out += changed(a[key], b[key], f"{prefix}{key}.")
        elif a.get(key) != b.get(key):
            out.append(f"{prefix}{key}")
    return out


def test_every_sensitivity_key_is_handled():
    assert set(sensitivity_keys(CFG)) == BUILT | ELSEWHERE


def config_value(dotted: str):
    node = CFG
    for part in dotted.split("."):
        node = node[part]
    return node


def test_one_analysis_per_sensitivity_value():
    """A list is one analysis per value, except event classes, where the
    list is the single alternative set of classes."""
    one = {"outcomes.circuit_failure.event_classes_sensitivity"}
    expected = sum(1 if k in one or not isinstance(config_value(k), list)
                   else len(config_value(k)) for k in BUILT)
    assert len(analyses(CFG)) == expected


def test_each_analysis_changes_exactly_one_key_and_has_a_unique_schema_name():
    built = analyses(CFG)
    for a in built:
        assert len(changed(CFG, a.cfg)) == 1, a.name
        assert a.name.isidentifier(), a.name
    assert len({a.name for a in built}) == len(built)


def test_label_analyses_rebuild_only_labels_and_circuit_analyses_everything():
    for a in analyses(CFG):
        key = changed(CFG, a.cfg)[0]
        rebuilds_circuits = key.startswith(("circuits.", "sessionization."))
        assert (a.stages == EVERY_STAGE) is rebuilds_circuits, a.name


def test_the_primary_config_is_not_modified():
    before = repr(CFG)
    analyses(CFG)
    assert repr(CFG) == before


# ── Building into a schema ────────────────────────────────────────────────


def labels_stage(value: int):
    """Stands in for a label stage: (re)creates the label table from a
    table in main, as the real SQL does with unqualified names."""
    def stage(con, cfg):
        con.execute("CREATE OR REPLACE TABLE circuit_failure_labels AS "
                    f"SELECT circuit_id, pred_time, {value} AS label FROM grid_source")
    return stage


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE grid_source AS SELECT 1 AS circuit_id, 0 AS pred_time")
    labels_stage(0)(c, CFG)
    return c


def test_build_writes_only_into_its_schema(con):
    build(con, Analysis("variant", CFG, (labels_stage(1),)))
    assert con.execute("SELECT label FROM main.circuit_failure_labels").fetchall() == [(0,)]
    assert con.execute("SELECT label FROM variant.circuit_failure_labels").fetchall() == [(1,)]
    # search_path is restored: unqualified names are main's again.
    assert con.execute("SELECT label FROM circuit_failure_labels").fetchall() == [(0,)]


def test_rebuild_starts_from_an_empty_schema(con):
    con.execute("CREATE SCHEMA variant")
    con.execute("CREATE TABLE variant.stale AS SELECT 1")
    build(con, Analysis("variant", CFG, (labels_stage(1),)))
    tables = con.execute("SELECT table_name FROM information_schema.tables "
                         "WHERE table_schema = 'variant'").fetchall()
    assert tables == [("circuit_failure_labels",)]


def test_a_label_analysis_with_another_grid_fails(con):
    con.execute("CREATE SCHEMA variant")
    con.execute("CREATE TABLE variant.circuit_failure_labels AS "
                "SELECT 1 AS circuit_id, 1 AS pred_time")
    with pytest.raises(RuntimeError, match="grid differs"):
        check_same_grid(con, "variant", "circuit_failure_labels")
