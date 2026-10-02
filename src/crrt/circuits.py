"""Build the `crrt_circuits` table: one row per CRRT filter (Parts 4.3, 4.4, 5.1).

The derivation lives in `sql/crrt_circuits.sql` so that it can go upstream to
mimic-code as a concept (Part 3.1, contribution 2). This module only binds
that file's parameters from config/config.yaml and prints an aggregate
summary.

The summary is the STROBE-style sanity check for this stage: circuits, stays
and patients, and the termination-class table of docs/feasibility.md §2.3.
It prints aggregates only, with every count under
`reporting.small_cell_threshold` suppressed (Part 1.4).

Usage: uv run python -m crrt.circuits
"""

from datetime import timedelta
from typing import Any

import duckdb

from crrt import config

SQL_PATH = config.REPO_ROOT / "sql" / "crrt_circuits.sql"


def bind(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/crrt_circuits.sql reads."""
    c = cfg["circuits"]
    variables: dict[str, Any] = {
        "machine_itemids": c["machine_itemids"],
        "system_integrity_itemid": c["system_integrity_itemid"],
        "filter_change_reason_itemid": c["filter_change_reason_itemid"],
        "segment_gap": timedelta(hours=cfg["sessionization"]["gap_hours"]),
        "max_downtime": timedelta(hours=c["max_downtime_hours"]),
        "new_filter_min_after_start": timedelta(
            hours=c["new_filter_min_hours_after_segment_start"]
        ),
        "reached_limit": timedelta(hours=c["reached_limit_hours"]),
    }
    for name, (before, after) in c["windows_hours"].items():
        variables[f"{name}_before"] = timedelta(hours=before)
        variables[f"{name}_after"] = timedelta(hours=after)
    for name, value in variables.items():
        con.execute(f"SET VARIABLE {name} = ?", [value])


def build(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind(con, cfg)
    con.execute(SQL_PATH.read_text())


def summarize(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    small = cfg["reporting"]["small_cell_threshold"]
    min_hours = cfg["cohort"]["min_session_duration_hours"]

    def n(v: int) -> str:
        return f"<{small}" if 0 < v < small else f"{v:,}"

    total, stays, patients = con.execute(
        "SELECT count(*), count(DISTINCT stay_id), count(DISTINCT subject_id) "
        "FROM crrt_circuits"
    ).fetchone()
    print(f"all circuits: {n(total)} ({n(stays)} stays, {n(patients)} patients)")

    kept, stays, patients = con.execute(
        "SELECT count(*), count(DISTINCT stay_id), count(DISTINCT subject_id) "
        "FROM crrt_circuits WHERE duration_hours >= ?",
        [min_hours],
    ).fetchone()
    print(f"circuits >= {min_hours} h: {n(kept)} ({n(stays)} stays, {n(patients)} patients)\n")

    rows = con.execute(
        "SELECT termination_class, count(*), count(DISTINCT subject_id), "
        "median(duration_hours) "
        "FROM crrt_circuits WHERE duration_hours >= ? "
        "GROUP BY 1 ORDER BY 2 DESC",
        [min_hours],
    ).fetchall()
    print(f"{'termination class':28s} {'circuits':>9s} {'patients':>9s} {'median h':>9s}")
    for cls, circuits, pts, med in rows:
        # A median over fewer than `small` circuits describes too few patients.
        med_s = f"{med:.1f}" if circuits >= small else "—"
        print(f"{cls:28s} {n(circuits):>9s} {n(pts):>9s} {med_s:>9s}")


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    build(con, cfg)
    summarize(con, cfg)
    con.close()


if __name__ == "__main__":
    main()
