"""Build the mimic-code concepts that the static features read (stage 0b).

SOFA and Sepsis-3 (Part 7, static group) come from MIT-LCP/mimic-code's
validated concepts, not a rewrite (CLAUDE.md). Their DuckDB versions are
vendored byte for byte under sql/mimic_code/ at the commit named in
sql/mimic_code/README.md (tests/test_concepts.py checks every file against
sql/mimic_code/SHA256SUMS) and run here, in the order of mimic-code's own
duckdb.sql, into the schema `mimiciv_derived`.

The concepts read `mimiciv_hosp.<table>` and `mimiciv_icu.<table>`. Here
those are views over `main` in which every time is the time the row became
available (Part 6.4): `charttime` is greatest(charttime, storetime) in
labevents, chartevents and outputevents, and `starttime` is
greatest(starttime, storetime) in inputevents. An hourly concept row then
holds only what was stored by its hour, and a score read at time t uses
nothing stored after t, without a line of the concepts changed. Decision:
docs/decisions.md 2026-10-05, "Static features".

What that costs, measured there: a vital sign or GCS row whose items were
stored at different times splits into several rows, and a pressor rate
segment stored at its end is never visible (the SOFA cardiovascular score,
which the static group leaves out). The other tables are passed through:
prescriptions and microbiologyevents carry no time of entry other than the
order or draw time the concepts already use.

The concepts read no circuit or cohort table, so this stage runs once and
every sensitivity analysis shares it.

Usage: uv run python -m crrt.concepts
"""

import duckdb

from crrt import config
from crrt.report import count

CONCEPTS_DIR = config.REPO_ROOT / "sql" / "mimic_code"

# Dependency order, as in mimic-code's mimic-iv/concepts_duckdb/duckdb.sql.
CONCEPTS = [
    "demographics/icustay_times",
    "demographics/icustay_hourly",
    "demographics/weight_durations",
    "measurement/urine_output",
    "measurement/bg",
    "measurement/chemistry",
    "measurement/complete_blood_count",
    "measurement/enzyme",
    "measurement/gcs",
    "measurement/oxygen_delivery",
    "measurement/urine_output_rate",
    "measurement/ventilator_setting",
    "measurement/vitalsign",
    "medication/antibiotic",
    "medication/dobutamine",
    "medication/dopamine",
    "medication/epinephrine",
    "medication/norepinephrine",
    "treatment/ventilation",
    "score/sofa",
    "sepsis/suspicion_of_infection",
    "sepsis/sepsis3",
]

# Source tables, as `schema/name`: the column replaced by its time of
# availability, or None to pass the table through unchanged.
SOURCES = {
    "hosp/labevents": "charttime",
    "hosp/microbiologyevents": None,
    "hosp/prescriptions": None,
    "icu/chartevents": "charttime",
    "icu/icustays": None,
    "icu/inputevents": "starttime",
    "icu/outputevents": "charttime",
}


def create_sources(con: duckdb.DuckDBPyConnection) -> None:
    """The schemas the concepts read from, as views over main, and an empty
    mimiciv_derived for them to write to."""
    for schema in ("mimiciv_derived", "mimiciv_hosp", "mimiciv_icu"):
        con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        con.execute(f"CREATE SCHEMA {schema}")
    for qualified, column in SOURCES.items():
        schema, name = qualified.split("/")
        replace = f" REPLACE (greatest({column}, storetime) AS {column})" if column else ""
        con.execute(f"CREATE VIEW mimiciv_{schema}.{name} AS "
                    f"SELECT *{replace} FROM main.{name}")


def build(con: duckdb.DuckDBPyConnection) -> None:
    create_sources(con)
    for concept in CONCEPTS:
        con.execute((CONCEPTS_DIR / f"{concept}.sql").read_text())


def summarize(con: duckdb.DuckDBPyConnection, cfg: dict) -> None:
    small = cfg["reporting"]["small_cell_threshold"]
    print(f"{'mimiciv_derived':45s} {'rows':>12s}")
    for concept in CONCEPTS:
        name = concept.split("/")[-1]
        rows = con.execute(f"SELECT count(*) FROM mimiciv_derived.{name}").fetchone()[0]
        print(f"{concept:45s} {count(rows, small):>12s}")
    print()


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    con.execute("SET preserve_insertion_order = false")
    build(con)
    summarize(con, cfg)
    con.close()


if __name__ == "__main__":
    main()
