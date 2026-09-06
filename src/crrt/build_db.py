"""Load the MIMIC-IV demo into a local DuckDB file.

Plan Part 2.1: DuckDB reads the gzipped CSVs directly, so there is no
intermediate import step for most tables. `chartevents` is the one table that
hurts, so it is converted to Parquet once and queried through a view.

The demo is 100 patients; at full scale the same script runs unchanged except
that the chartevents conversion is the expensive step. Partitioning that
Parquet by itemid (Part 2.1) pays off on the full database but would produce
thousands of near-empty files on the demo, so this writes a single file.

Usage: uv run python -m crrt.build_db
"""

from pathlib import Path

import duckdb

from crrt import config

# Tables loaded straight from CSV, as `schema/name` under the demo directory.
# The demo ships the same layout as the full database.
CSV_TABLES = [
    "hosp/admissions",
    "hosp/d_icd_diagnoses",
    "hosp/d_icd_procedures",
    "hosp/d_labitems",
    "hosp/diagnoses_icd",
    "hosp/labevents",
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

# Converted to Parquet first, then exposed as a view (Part 2.1).
PARQUET_TABLES = ["icu/chartevents"]


def build(cfg: dict) -> None:
    demo_dir = config.path(cfg, "demo_dir")
    duckdb_path = config.path(cfg, "duckdb")
    parquet_dir = config.path(cfg, "parquet_dir")

    if not demo_dir.is_dir():
        raise SystemExit(f"demo directory not found: {demo_dir}")

    parquet_dir.mkdir(parents=True, exist_ok=True)
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    duckdb_path.unlink(missing_ok=True)

    con = duckdb.connect(str(duckdb_path))

    for qualified in PARQUET_TABLES:
        name = qualified.split("/")[-1]
        csv = demo_dir / f"{qualified}.csv.gz"
        parquet = parquet_dir / f"{name}.parquet"
        con.execute(
            f"COPY (SELECT * FROM read_csv_auto('{csv}')) "
            f"TO '{parquet}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        con.execute(
            f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{parquet}')"
        )
        _report(con, name, parquet)

    for qualified in CSV_TABLES:
        name = qualified.split("/")[-1]
        csv = demo_dir / f"{qualified}.csv.gz"
        con.execute(
            f"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{csv}')"
        )
        _report(con, name, csv)

    con.close()
    print(f"\nwrote {duckdb_path} ({duckdb_path.stat().st_size / 1e6:.1f} MB)")


def _report(con: duckdb.DuckDBPyConnection, name: str, source: Path) -> None:
    rows = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    print(f"  {name:20s} {rows:>10,} rows  ({source.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    build(config.load())
