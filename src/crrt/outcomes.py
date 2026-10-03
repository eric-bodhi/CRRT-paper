"""Build the outcome label tables (Parts 5, 6.1-6.3).

Both tables hold one row per included circuit per prediction time:

- `circuit_failure_labels` (primary outcome): did the filter clot in the
  next `prediction.horizon_hours`? Rules in `sql/circuit_failure_labels.sql`.
- `hypophos_labels` (secondary outcome): is phosphate first drawn below
  `outcomes.hypophosphatemia.moderate_mg_dl` in the next
  `outcomes.hypophosphatemia.horizon_hours`? Rules in
  `sql/hypophos_labels.sql`.

This module binds each file's parameters from config/config.yaml and prints
an aggregate summary. Only the primary analyses are built here. The
sensitivity analyses (event classes, unclear handling, horizon, blanking,
phosphate threshold) rebind the same SQL with their config values.

The summary prints aggregates only, with every count under
`reporting.small_cell_threshold` suppressed (Part 1.4).

Usage: uv run python -m crrt.outcomes
"""

from datetime import timedelta
from typing import Any

import duckdb

from crrt import config
from crrt.report import count

CIRCUIT_FAILURE_SQL = config.REPO_ROOT / "sql" / "circuit_failure_labels.sql"
HYPOPHOS_SQL = config.REPO_ROOT / "sql" / "hypophos_labels.sql"


def _set(con: duckdb.DuckDBPyConnection, variables: dict[str, Any]) -> None:
    for name, value in variables.items():
        con.execute(f"SET VARIABLE {name} = ?", [value])


def bind_circuit_failure(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/circuit_failure_labels.sql reads."""
    p = cfg["prediction"]
    o = cfg["outcomes"]["circuit_failure"]
    c = cfg["circuits"]
    variables: dict[str, Any] = {
        "step": timedelta(hours=p["step_hours"]),
        "horizon": timedelta(hours=p["horizon_hours"]),
        "blanking": timedelta(minutes=p["blanking_minutes"]),
        "warmup": timedelta(hours=p["warmup_hours"]),
        "running_gap": timedelta(hours=cfg["sessionization"]["gap_hours"]),
        "max_age": timedelta(hours=o["scheduled_change_interval_hours"]),
        "machine_itemids": c["machine_itemids"],
        "system_integrity_itemid": c["system_integrity_itemid"],
        "event_classes": o["event_classes_primary"],
        "competing_risk_classes": o["competing_risk_classes"],
        "unclear_classes": o["unclear_classes"],
        "unclear_handling": o["unclear_handling_primary"],
    }
    # The windows crrt_circuits used to find the documenting entry.
    for name in ("clotted_at_end", "clots_increasing_at_end"):
        before, after = c["windows_hours"][name]
        variables[f"{name}_before"] = timedelta(hours=before)
        variables[f"{name}_after"] = timedelta(hours=after)
    _set(con, variables)


def bind_hypophos(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/hypophos_labels.sql reads."""
    h = cfg["outcomes"]["hypophosphatemia"]
    _set(con, {
        "step": timedelta(hours=cfg["prediction"]["step_hours"]),
        "horizon": timedelta(hours=h["horizon_hours"]),
        "max_age": timedelta(hours=h["known_value_max_age_hours"]),
        "threshold": float(h["moderate_mg_dl"]),
        "phosphate_itemid": h["phosphate_itemid"],
        "repletion_orders": [f"{drug}={route}"
                             for drug, routes in h["repletion_orders"].items()
                             for route in routes],
    })


def build_circuit_failure(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind_circuit_failure(con, cfg)
    con.execute(CIRCUIT_FAILURE_SQL.read_text())


def build_hypophos(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind_hypophos(con, cfg)
    con.execute(HYPOPHOS_SQL.read_text())


def summarize(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], table: str, title: str) -> None:
    small = cfg["reporting"]["small_cell_threshold"]

    def n(v: int) -> str:
        return count(v, small)

    print(title)
    rows, circuits = con.execute(
        f"SELECT count(*), count(DISTINCT circuit_id) FROM {table}"
    ).fetchone()
    print(f"prediction rows: {n(rows)} over {n(circuits)} circuits")
    for reason, k in con.execute(
        f"SELECT not_scored_reason, count(*) FROM {table} "
        "WHERE NOT scored GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(f"  not scored, {reason:20s} {n(k):>9s}")

    print(f"\n{'scored rows':28s} {'rows':>9s} {'circuits':>9s} {'patients':>9s}")
    for label, k, circ, pts in con.execute(
        "SELECT CASE WHEN label THEN 'event in horizon' WHEN NOT label THEN 'no event' "
        "            ELSE 'censored: ' || censor_reason END, "
        "       count(*), count(DISTINCT circuit_id), count(DISTINCT subject_id) "
        f"FROM {table} WHERE scored GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(f"{label:28s} {n(k):>9s} {n(circ):>9s} {n(pts):>9s}")
    pos, labelled = con.execute(
        f"SELECT count(*) FILTER (WHERE label), count(label) FROM {table}"
    ).fetchone()
    if pos >= small:
        print(f"prevalence among labelled rows: {pos / labelled:.1%}")
    print()


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    cf = cfg["outcomes"]["circuit_failure"]
    hp = cfg["outcomes"]["hypophosphatemia"]

    build_circuit_failure(con, cfg)
    summarize(con, cfg, "circuit_failure_labels",
              f"circuit failure, horizon {cfg['prediction']['horizon_hours']} h "
              f"(primary: {', '.join(cf['event_classes_primary'])})")

    build_hypophos(con, cfg)
    summarize(con, cfg, "hypophos_labels",
              f"hypophosphatemia, horizon {hp['horizon_hours']} h "
              f"(primary: phosphate < {hp['moderate_mg_dl']} mg/dL)")
    con.close()


if __name__ == "__main__":
    main()
