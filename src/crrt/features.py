"""Build the feature tables (Part 7).

So far only the machine/circuit group: `machine_features`, one row per
prediction row of `circuit_failure_labels` (the same grid as
`hypophos_labels`), from data available at the prediction time. Rules in
`sql/machine_features.sql`.

This module binds the SQL's parameters from config/config.yaml and prints
an aggregate summary, with every count under
`reporting.small_cell_threshold` suppressed (Part 1.4).

Usage: uv run python -m crrt.features
"""

from datetime import timedelta
from typing import Any

import duckdb

from crrt import config
from crrt.outcomes import _set
from crrt.report import count

MACHINE_FEATURES_SQL = config.REPO_ROOT / "sql" / "machine_features.sql"


def bind_machine_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/machine_features.sql reads."""
    f = cfg["features"]
    bounds = f["plausibility_bounds"]
    clipped = set(f["pressure_clip_itemids"])
    items = [
        {"name": name, "itemid": itemid,
         "low": float(bounds[itemid][0]), "high": float(bounds[itemid][1]),
         "clip_margin": float(f["pressure_clip_margin_mmhg"] if itemid in clipped else 0)}
        for name, itemid in f["machine_signals"].items()
    ]
    _set(con, {
        "machine_items": items,
        "machine_itemids": [i["itemid"] for i in items],
        "windows": [{"hours": h, "span": timedelta(hours=h)} for h in f["window_hours"]],
        "min_points_for_trend": f["min_points_for_trend"],
        "step": timedelta(hours=cfg["prediction"]["step_hours"]),
        "crrt_mode_itemid": f["crrt_mode_itemid"],
    })


def build_machine_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind_machine_features(con, cfg)
    con.execute(MACHINE_FEATURES_SQL.read_text())


def summarize(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Coverage of each signal among scored circuit-failure rows."""
    small = cfg["reporting"]["small_cell_threshold"]
    windows = cfg["features"]["window_hours"]
    shortest = min(windows)
    columns = [d[0] for d in con.execute("SELECT * FROM machine_features LIMIT 0").description]
    signals = [c.removesuffix("_hours_since_last") for c in columns if c.endswith("_hours_since_last")]

    scored = con.execute("SELECT count(*) FROM circuit_failure_labels WHERE scored").fetchone()[0]
    print(f"machine_features: {len(columns)} columns; {count(scored, small)} scored rows")

    def share(k: int) -> str:
        return f"{k / scored:.1%}" if k >= small else count(k, small)

    print(f"\n{'signal':30s} {'has last':>9s} {'median n ' + str(shortest) + 'h':>12s} "
          f"{'slope ' + str(shortest) + 'h':>9s} {'slope ' + str(max(windows)) + 'h':>9s}")
    for s in signals:
        has_last, n_med, slope_short, slope_long = con.execute(
            f"SELECT count({s}_last), median({s}_{shortest}h_n), "
            f"count({s}_{shortest}h_slope), count({s}_{max(windows)}h_slope) "
            "FROM machine_features JOIN circuit_failure_labels USING (circuit_id, pred_time) "
            "WHERE scored"
        ).fetchone()
        print(f"{s:30s} {share(has_last):>9s} {n_med:>12.0f} {share(slope_short):>9s} {share(slope_long):>9s}")

    print(f"\n{'crrt_mode_last':30s} {'scored rows':>12s}")
    for mode, k in con.execute(
        "SELECT coalesce(crrt_mode_last, '(none)'), count(*) "
        "FROM machine_features JOIN circuit_failure_labels USING (circuit_id, pred_time) "
        "WHERE scored GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(f"{mode:30s} {count(k, small):>12s}")
    print()


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    build_machine_features(con, cfg)
    summarize(con, cfg)
    con.close()


if __name__ == "__main__":
    main()
