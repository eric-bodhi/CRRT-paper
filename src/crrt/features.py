"""Build the feature tables (Part 7).

So far five groups in four tables, each one row per prediction row of
`circuit_failure_labels` (the same grid as `hypophos_labels`), from data
available at the prediction time: the machine/circuit group
(`machine_features`, rules in `sql/machine_features.sql`), the
anticoagulation group (`anticoag_features`, rules in
`sql/anticoag_features.sql`), the coagulation/hematology and chemistry
groups (`lab_features`, rules in `sql/lab_features.sql`), and the vascular
access group (`access_features`, rules in `sql/access_features.sql`).

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
ANTICOAG_FEATURES_SQL = config.REPO_ROOT / "sql" / "anticoag_features.sql"
LAB_FEATURES_SQL = config.REPO_ROOT / "sql" / "lab_features.sql"
ACCESS_FEATURES_SQL = config.REPO_ROOT / "sql" / "access_features.sql"


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


def bind_anticoag_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/anticoag_features.sql reads."""
    f = cfg["features"]
    bounds = f["plausibility_bounds"]

    def bounded(signals: dict[str, int]) -> list[dict[str, Any]]:
        return [{"name": name, "itemid": itemid,
                 "low": float(bounds[itemid][0]), "high": float(bounds[itemid][1])}
                for name, itemid in signals.items()]

    items = bounded(f["anticoag_signals"])
    _set(con, {
        "anticoag_items": items,
        "anticoag_itemids": [i["itemid"] for i in items],
        "calcium_labs": bounded(f["calcium_labs"]),
        "calcium_pair": timedelta(minutes=f["calcium_pair_minutes"]),
        "calcium_mg_dl_per_mmol_l": float(f["calcium_mg_dl_per_mmol_l"]),
        "lab_lookback": timedelta(hours=f["lab_lookback_hours"]),
        "windows": [{"hours": h, "span": timedelta(hours=h)} for h in f["window_hours"]],
        "min_points_for_trend": f["min_points_for_trend"],
        "step": timedelta(hours=cfg["prediction"]["step_hours"]),
    })


def build_anticoag_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind_anticoag_features(con, cfg)
    con.execute(ANTICOAG_FEATURES_SQL.read_text())


def bind_lab_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/lab_features.sql reads."""
    f = cfg["features"]
    bounds = f["plausibility_bounds"]
    labs = [{"name": name, "itemid": itemid,
             "low": float(bounds[itemid][0]), "high": float(bounds[itemid][1])}
            for group in f["lab_groups"].values() for name, itemid in group.items()]
    _set(con, {
        "labs": labs,
        "lab_itemids": [i["itemid"] for i in labs],
        "lab_lookback": timedelta(hours=f["lab_lookback_hours"]),
    })


def build_lab_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind_lab_features(con, cfg)
    con.execute(LAB_FEATURES_SQL.read_text())


def bind_access_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/access_features.sql reads."""
    f = cfg["features"]
    types = f["access_catheter_types"]
    _set(con, {
        "catheter_types": [{"itemid": itemid, "value": value, "type": t}
                           for itemid, values in types.items() for value, t in values.items()],
        "catheter_type_itemids": list(types),
        "insertion_date_itemid": f["access_insertion_date_itemid"],
    })


def build_access_features(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind_access_features(con, cfg)
    con.execute(ACCESS_FEATURES_SQL.read_text())


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


def summarize_anticoag(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Coverage of each signal, and the anticoagulation class by era, among
    scored circuit-failure rows. By era because the group was restricted to
    sources that are charted the same way in every era (decisions.md,
    2026-10-04)."""
    small = cfg["reporting"]["small_cell_threshold"]
    columns = [d[0] for d in con.execute("SELECT * FROM anticoag_features LIMIT 0").description]
    names = [c.removesuffix("_hours_since_last") for c in columns if c.endswith("_hours_since_last")]
    scored = "FROM anticoag_features JOIN circuit_failure_labels USING (circuit_id, pred_time) WHERE scored"
    total = con.execute(f"SELECT count(*) {scored}").fetchone()[0]
    print(f"anticoag_features: {len(columns)} columns; {count(total, small)} scored rows")

    def share(k: int) -> str:
        return f"{k / total:.1%}" if k >= small else count(k, small)

    print(f"\n{'signal':20s} {'has last':>9s} {'median last':>12s} {'median h since':>15s} "
          f"{'has delta':>10s}")
    for s in names:
        k, med, since = con.execute(
            f"SELECT count({s}_last), median({s}_last), median({s}_hours_since_last) {scored}"
        ).fetchone()
        has_delta = (share(con.execute(f"SELECT count({s}_delta) {scored}").fetchone()[0])
                     if f"{s}_delta" in columns else "—")
        print(f"{s:20s} {share(k):>9s} {med:>12.3g} {since:>15.1f} {has_delta:>10s}")

    rows = con.execute(
        "SELECT p.anchor_year_group, coalesce(a.anticoag_class, '(unknown)'), count(*) "
        "FROM anticoag_features AS a "
        "JOIN circuit_failure_labels AS l USING (circuit_id, pred_time) "
        "JOIN patients AS p USING (subject_id) WHERE l.scored GROUP BY ALL"
    ).fetchall()
    eras = sorted({r[0] for r in rows})
    classes = sorted({r[1] for r in rows})
    cell = {(e, c): k for e, c, k in rows}
    print(f"\n{'anticoag_class':20s}" + "".join(f"{e:>13s}" for e in eras))
    for c in classes:
        line = f"{c:20s}"
        for e in eras:
            k = cell.get((e, c), 0)
            n = sum(cell.get((e, x), 0) for x in classes)
            line += f"{(f'{k / n:.1%}' if k >= small else count(k, small)):>13s}"
        print(line)
    print()


def summarize_labs(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Coverage of each lab among scored circuit-failure rows, overall and by
    era: how often a lab is drawn changed by era for some of them
    (decisions.md, 2026-10-04, "Laboratory features")."""
    small = cfg["reporting"]["small_cell_threshold"]
    columns = [d[0] for d in con.execute("SELECT * FROM lab_features LIMIT 0").description]
    scored = ("FROM lab_features JOIN circuit_failure_labels USING (circuit_id, pred_time) "
              "JOIN patients USING (subject_id) WHERE scored")
    total = con.execute(f"SELECT count(*) {scored}").fetchone()[0]
    print(f"lab_features: {len(columns)} columns; {count(total, small)} scored rows")

    def share(k: int, n: int) -> str:
        return f"{k / n:.1%}" if k >= small else count(k, small)

    eras = [e for (e,) in con.execute(
        f"SELECT DISTINCT anchor_year_group {scored} ORDER BY 1").fetchall()]
    print(f"\n{'group':24s} {'lab':14s} {'has last':>9s} {'median last':>12s} "
          f"{'median h since':>15s} {'has delta':>10s}  has last by era ({eras[0]} … {eras[-1]})")
    for group, labs in cfg["features"]["lab_groups"].items():
        for s in labs:
            k, med, since, k_delta = con.execute(
                f"SELECT count({s}_last), median({s}_last), median({s}_hours_since_last), "
                f"count({s}_delta) {scored}"
            ).fetchone()
            by_era = dict((e, (k_e, n_e)) for e, k_e, n_e in con.execute(
                f"SELECT anchor_year_group, count({s}_last), count(*) {scored} GROUP BY 1"
            ).fetchall())
            print(f"{group:24s} {s:14s} {share(k, total):>9s} {med:>12.3g} {since:>15.1f} "
                  f"{share(k_delta, total):>10s}  " + " / ".join(share(*by_era[e]) for e in eras))
    print()


def summarize_access(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Coverage of each signal, and the tunneled share and catheter age, by
    era among scored circuit-failure rows: by era, to show that neither
    drifts with it as 224270, the site item left out, did (decisions.md,
    2026-10-04, "Access features")."""
    small = cfg["reporting"]["small_cell_threshold"]
    columns = [d[0] for d in con.execute("SELECT * FROM access_features LIMIT 0").description]
    scored = ("FROM access_features JOIN circuit_failure_labels USING (circuit_id, pred_time) "
              "JOIN patients USING (subject_id) WHERE scored")
    print(f"access_features: {len(columns)} columns; "
          f"{count(con.execute(f'SELECT count(*) {scored}').fetchone()[0], small)} scored rows")

    def share(k: int, n: int) -> str:
        return f"{k / n:.1%}" if k >= small else count(k, small)

    print(f"\n{'era':14s} {'scored rows':>12s} {'has type':>9s} {'tunneled':>9s} "
          f"{'has age':>8s} {'median age d':>13s} {'median h since type':>20s}")
    for era, n, k_type, k_tun, k_age, age, since in con.execute(
        "SELECT coalesce(anchor_year_group, 'all'), count(*), count(catheter_type_last), "
        "count(*) FILTER (WHERE catheter_type_last = 'tunneled'), count(catheter_age_days), "
        f"median(catheter_age_days), median(catheter_type_hours_since_last) {scored} "
        "GROUP BY ROLLUP (anchor_year_group) ORDER BY anchor_year_group NULLS LAST"
    ).fetchall():
        print(f"{era:14s} {count(n, small):>12s} {share(k_type, n):>9s} {share(k_tun, k_type):>9s} "
              f"{share(k_age, n):>8s} {age:>13.0f} {since:>20.1f}")
    print()


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    build_machine_features(con, cfg)
    summarize(con, cfg)
    build_anticoag_features(con, cfg)
    summarize_anticoag(con, cfg)
    build_lab_features(con, cfg)
    summarize_labs(con, cfg)
    build_access_features(con, cfg)
    summarize_access(con, cfg)
    con.close()


if __name__ == "__main__":
    main()
