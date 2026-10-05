"""Build every sensitivity analysis in config/config.yaml (stage 6).

Each analysis is the primary config with one key set to a `*_sensitivity`
value. It is built into its own schema of the same database, named after
it, e.g. `horizon_12h.circuit_failure_labels`. While it builds, unqualified
names resolve to that schema first and to `main` second. So the stage SQL
and the summaries run unchanged, new tables land in the analysis's schema,
and the raw MIMIC tables and the primary analysis are read from `main`
without being touched.

There are two kinds:

- **Label analyses** change only which rows are scored and how they are
  labelled: horizon, blanking, event classes, unclear handling,
  phosphate threshold, repletion handling. Each rebuilds one label table.
  It shares `main`'s circuits, cohort and feature tables, and its grid is
  checked against the primary's so the features join.
- **Circuit analyses** change which circuits exist: maximum downtime and
  the segment gap. `circuit_id` is a row number, so under another circuit
  definition the same id is another circuit. These rebuild every stage from
  circuits to features in their own schema. **Never join a table of one of
  these schemas to a table of another schema.**

The cohort flow (docs/strobe.md) is written for the primary only.

Prints the label table summaries of crrt.outcomes, then one comparison table
per outcome with the primary on the first line, with every count under
`reporting.small_cell_threshold` suppressed (Part 1.4).

Usage: uv run python -m crrt.sensitivity
"""

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import duckdb

from crrt import circuits, cohort, config, features, outcomes
from crrt.report import count

Stage = Callable[[duckdb.DuckDBPyConnection, dict[str, Any]], None]

CIRCUIT_FAILURE: tuple[Stage, ...] = (outcomes.build_circuit_failure,)
HYPOPHOS: tuple[Stage, ...] = (outcomes.build_hypophos,)
EVERY_STAGE: tuple[Stage, ...] = (
    circuits.build, cohort.build, outcomes.build_circuit_failure, outcomes.build_hypophos,
    features.build_machine_features, features.build_anticoag_features,
    features.build_lab_features, features.build_access_features,
)
LABEL_TABLES = {outcomes.build_circuit_failure: "circuit_failure_labels",
                outcomes.build_hypophos: "hypophos_labels"}


@dataclass(frozen=True)
class Analysis:
    name: str             # the schema it is built in
    cfg: dict[str, Any]   # the primary config with one key changed
    stages: tuple[Stage, ...]

    @property
    def label_tables(self) -> list[str]:
        return [LABEL_TABLES[s] for s in self.stages if s in LABEL_TABLES]


def analyses(cfg: dict[str, Any]) -> list[Analysis]:
    """One Analysis per sensitivity value in the config."""
    out: list[Analysis] = []

    def add(name: str, path: tuple[str, ...], value: Any, stages: tuple[Stage, ...]) -> None:
        changed = copy.deepcopy(cfg)
        node = changed
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        out.append(Analysis(name.replace(".", "_"), changed, stages))

    p = cfg["prediction"]
    cf = cfg["outcomes"]["circuit_failure"]
    hp = cfg["outcomes"]["hypophosphatemia"]
    for h in p["horizon_hours_sensitivity"]:
        add(f"horizon_{h}h", ("prediction", "horizon_hours"), h, CIRCUIT_FAILURE)
    for m in p["blanking_minutes_sensitivity"]:
        add(f"blanking_{m}min", ("prediction", "blanking_minutes"), m, CIRCUIT_FAILURE)
    add("event_" + "_".join(cf["event_classes_sensitivity"]),
        ("outcomes", "circuit_failure", "event_classes_primary"),
        cf["event_classes_sensitivity"], CIRCUIT_FAILURE)
    add(f"unclear_{cf['unclear_handling_sensitivity']}",
        ("outcomes", "circuit_failure", "unclear_handling_primary"),
        cf["unclear_handling_sensitivity"], CIRCUIT_FAILURE)
    add(f"phosphate_below_{hp['sensitivity_mg_dl']}",
        ("outcomes", "hypophosphatemia", "moderate_mg_dl"), hp["sensitivity_mg_dl"], HYPOPHOS)
    for handling in hp["repletion_handling_sensitivity"]:
        add(f"repletion_{handling}", ("outcomes", "hypophosphatemia", "repletion_handling_primary"),
            handling, HYPOPHOS)
    for h in cfg["circuits"]["max_downtime_hours_sensitivity"]:
        add(f"max_downtime_{h}h", ("circuits", "max_downtime_hours"), h, EVERY_STAGE)
    for h in cfg["sessionization"]["gap_hours_sensitivity"]:
        add(f"segment_gap_{h}h", ("sessionization", "gap_hours"), h, EVERY_STAGE)
    return out


def build(con: duckdb.DuckDBPyConnection, a: Analysis) -> None:
    """Build `a` into a fresh schema of its name, leaving `main` untouched."""
    con.execute(f"DROP SCHEMA IF EXISTS {a.name} CASCADE")
    con.execute(f"CREATE SCHEMA {a.name}")
    con.execute(f"SET search_path = '{a.name},main'")
    try:
        for stage in a.stages:
            stage(con, a.cfg)
    finally:
        con.execute("SET search_path = 'main'")
    if EVERY_STAGE != a.stages:
        for table in a.label_tables:
            check_same_grid(con, a.name, table)


def check_same_grid(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> None:
    """A label analysis shares main's features, which join on (circuit_id,
    pred_time). If its grid differed, rows would silently lose features."""
    differ = con.execute(
        f"SELECT (SELECT count(*) FROM (SELECT circuit_id, pred_time FROM {schema}.{table} "
        f"        EXCEPT SELECT circuit_id, pred_time FROM main.{table})) "
        f"     + (SELECT count(*) FROM (SELECT circuit_id, pred_time FROM main.{table} "
        f"        EXCEPT SELECT circuit_id, pred_time FROM {schema}.{table}))"
    ).fetchone()[0]
    if differ:
        raise RuntimeError(f"{schema}.{table}: grid differs from main.{table} in {differ} rows")


def compare(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], table: str,
            schemas: list[str]) -> None:
    """Positive / labelled scored rows, prevalence, stays with a positive row
    and prevalence by era, one line per schema."""
    small = cfg["reporting"]["small_cell_threshold"]

    def share(k: int, n: int) -> str:
        return f"{k / n:.1%}" if k >= small else count(k, small)

    eras = [e for (e,) in con.execute(
        "SELECT DISTINCT anchor_year_group FROM main.patients ORDER BY 1").fetchall()]
    print(f"{table}, scored rows")
    print(f"{'analysis':32s} {'positive / labelled':>22s} {'prev.':>6s} {'stays +':>8s}  "
          f"prevalence by era ({eras[0]} … {eras[-1]})")
    for schema in schemas:
        q = f"FROM {schema}.{table} AS l JOIN main.patients AS p USING (subject_id) WHERE l.scored"
        pos, labelled, stays = con.execute(
            f"SELECT count(*) FILTER (WHERE label), count(label), "
            f"count(DISTINCT stay_id) FILTER (WHERE label) {q}").fetchone()
        by_era = dict((e, (k, n)) for e, k, n in con.execute(
            f"SELECT anchor_year_group, count(*) FILTER (WHERE label), count(label) {q} GROUP BY 1"
        ).fetchall())
        era_cells = " / ".join(share(*by_era.get(e, (0, 0))) if by_era.get(e, (0, 0))[1] else "—"
                               for e in eras)
        print(f"{schema:32s} {count(pos, small) + ' / ' + count(labelled, small):>22s} "
              f"{share(pos, labelled):>6s} {count(stays, small):>8s}  {era_cells}")
    print()


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    built = analyses(cfg)
    for a in built:
        build(con, a)
        con.execute(f"SET search_path = '{a.name},main'")
        print(f"=== {a.name}\n")
        if a.stages == EVERY_STAGE:
            circuits.summarize(con, a.cfg)
        for table in a.label_tables:
            outcomes.summarize(con, a.cfg, table, table)
        con.execute("SET search_path = 'main'")

    for table in LABEL_TABLES.values():
        compare(con, cfg, table, ["main"] + [a.name for a in built if table in a.label_tables])
    con.close()


if __name__ == "__main__":
    main()
