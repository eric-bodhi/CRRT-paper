"""Load MIMIC-IV 3.1 into a local DuckDB file.

Plan Part 2.1: DuckDB reads the gzipped CSVs directly, so there is no
intermediate import step for most tables. `chartevents` (433M rows) and
`labevents` (158M rows) are the two tables that hurt, so each is converted to
Parquet once, partitioned by `itemid`, and queried through a view. Every
downstream query filters on itemid, so partition pruning turns a full scan
into a read of the handful of directories it names.

The conversion is skipped when the partitioned directory already exists. The
source is a checksummed release (`SHA256SUMS.txt`) that never changes, so a
completed conversion is never stale; the DuckDB file itself is rebuilt from
scratch every run. Delete `data/parquet/<table>` to force a reconversion.

The demo (Part 1.6) has the same layout, so pointing `paths.mimic_dir` at it
runs this unchanged.

Usage: uv run python -m crrt.build_db
"""

from pathlib import Path

import duckdb

from crrt import config

# Tables loaded straight from CSV, as `schema/name` under the source directory.
CSV_TABLES = [
    "hosp/admissions",
    "hosp/d_icd_diagnoses",
    "hosp/d_icd_procedures",
    "hosp/d_labitems",
    "hosp/diagnoses_icd",
    "hosp/omr",
    "hosp/patients",
    "hosp/pharmacy",
    "hosp/prescriptions",
    "hosp/procedures_icd",
    "hosp/services",
    "hosp/transfers",
    "icu/caregiver",
    "icu/d_items",
    "icu/datetimeevents",
    "icu/icustays",
    "icu/ingredientevents",
    "icu/inputevents",
    "icu/outputevents",
    "icu/procedureevents",
]

# Converted to itemid-partitioned Parquet, then exposed as a view (Part 2.1).
# Column types are stated rather than sniffed: at full scale the type sniffer
# samples too little of the file, and the free-text `value`/`comments`
# columns contain embedded quotes that need the explicit quote/escape below.
PARQUET_TABLES = {
    "icu/chartevents": dict(
        subject_id="INTEGER", hadm_id="INTEGER", stay_id="INTEGER",
        caregiver_id="INTEGER", charttime="TIMESTAMP", storetime="TIMESTAMP",
        itemid="INTEGER", value="VARCHAR", valuenum="DOUBLE",
        valueuom="VARCHAR", warning="INTEGER",
    ),
    "hosp/labevents": dict(
        labevent_id="BIGINT", subject_id="INTEGER", hadm_id="INTEGER",
        specimen_id="BIGINT", itemid="INTEGER", order_provider_id="VARCHAR",
        charttime="TIMESTAMP", storetime="TIMESTAMP", value="VARCHAR",
        valuenum="DOUBLE", valueuom="VARCHAR", ref_range_lower="DOUBLE",
        ref_range_upper="DOUBLE", flag="VARCHAR", priority="VARCHAR",
        comments="VARCHAR",
    ),
}


def build(cfg: dict) -> None:
    mimic_dir = config.path(cfg, "mimic_dir")
    duckdb_path = config.path(cfg, "duckdb")
    parquet_dir = config.path(cfg, "parquet_dir")

    if not mimic_dir.is_dir():
        raise SystemExit(f"MIMIC-IV directory not found: {mimic_dir}")

    parquet_dir.mkdir(parents=True, exist_ok=True)
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    duckdb_path.unlink(missing_ok=True)

    con = duckdb.connect(str(duckdb_path))
    # Without this the partitioned COPY must hold the whole table in order.
    con.execute("SET preserve_insertion_order = false")

    for qualified, columns in PARQUET_TABLES.items():
        name = qualified.split("/")[-1]
        csv = mimic_dir / f"{qualified}.csv.gz"
        out = parquet_dir / name
        if out.is_dir():
            print(f"  {name}: reusing {out}")
        else:
            con.execute(
                f"COPY (SELECT * FROM read_csv('{csv}', header = true, "
                f"quote = '\"', escape = '\"', columns = {columns!r})) "
                f"TO '{out}' (FORMAT PARQUET, PARTITION_BY (itemid), COMPRESSION ZSTD)"
            )
        con.execute(
            f"CREATE VIEW {name} AS SELECT * FROM "
            f"read_parquet('{out}/*/*.parquet', hive_partitioning = true)"
        )
        _report(con, name, csv)

    for qualified in CSV_TABLES:
        name = qualified.split("/")[-1]
        csv = mimic_dir / f"{qualified}.csv.gz"
        con.execute(
            f"CREATE TABLE {name} AS SELECT * FROM "
            f"read_csv_auto('{csv}', sample_size = -1)"
        )
        _report(con, name, csv)

    con.close()
    print(f"\nwrote {duckdb_path} ({duckdb_path.stat().st_size / 1e6:.1f} MB)")


def _report(con: duckdb.DuckDBPyConnection, name: str, source: Path) -> None:
    rows = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    print(f"  {name:20s} {rows:>12,} rows  ({source.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    build(config.load())
