"""Build `crrt_cohort` and the STROBE flow (Parts 4.1, 4.2, 4.6).

The rules live in `sql/crrt_cohort.sql`. This module binds that file's
parameters from config/config.yaml, then counts the flow diagram over the
result and writes it to docs/strobe.md. Part 4.6 says build the flow as you
go, with exact counts at each exclusion step, not at the end.

docs/strobe.md is committed, so every count in it goes through small-cell
suppression (Part 1.4, `reporting.small_cell_threshold`).

Usage: uv run python -m crrt.cohort
"""

from typing import Any

import duckdb

from crrt import config
from crrt.report import count

SQL_PATH = config.REPO_ROOT / "sql" / "crrt_cohort.sql"
OUT_PATH = config.REPO_ROOT / "docs" / "strobe.md"

# exclusion_reason values in sql/crrt_cohort.sql, in the order the SQL tests
# them, with the wording used in the flow diagram.
EXCLUSIONS = [
    ("under_min_age", "age at ICU admission < {min_age} years"),
    ("under_min_duration", "circuit shorter than {min_hours} h"),
]


def bind(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Set every DuckDB variable that sql/crrt_cohort.sql reads."""
    c = cfg["cohort"]
    d = c["chronic_dialysis"]
    variables: dict[str, Any] = {
        "min_age_years": c["min_age_years"],
        "min_duration_hours": float(c["min_session_duration_hours"]),
        "admission_history_itemid": d["admission_history_itemid"],
        "admission_history_value": float(d["admission_history_value"]),
        "last_dialysis_itemid": d["last_dialysis_itemid"],
        # Matched as "itemid=value": each catheter item has its own vocabulary.
        "tunneled_catheter": [f"{i}={v}" for i, v in d["tunneled_catheter_values"].items()],
        "chronic_dialysis_icd_codes": d["icd_codes"],
        "same_admission_icd_primary": d["same_admission_icd_primary"],
        "same_admission_icd_sensitivity": d["same_admission_icd_sensitivity"],
    }
    for name, value in variables.items():
        con.execute(f"SET VARIABLE {name} = ?", [value])


def build(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    bind(con, cfg)
    con.execute(SQL_PATH.read_text())


def flow(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> list[tuple[str, tuple, int | None]]:
    """STROBE boxes as (label, (circuits, stays, patients), circuits removed).

    Stay-level boxes carry None for circuits. The entry box counts ICU stays
    with any item of the validated mimic-code CRRT concept or a CRRT
    procedure: CRRT was documented, whether or not a circuit could be built.
    """
    inv = cfg["itemid_inventory"]
    c = cfg["cohort"]
    labels = {k: v.format(min_age=c["min_age_years"], min_hours=c["min_session_duration_hours"])
              for k, v in EXCLUSIONS}

    def triple(where: str) -> tuple:
        return con.execute(
            "SELECT count(*), count(DISTINCT stay_id), count(DISTINCT subject_id) "
            f"FROM crrt_cohort WHERE {where}"
        ).fetchone()

    icu = con.execute(
        "SELECT NULL, count(DISTINCT stay_id), count(DISTINCT subject_id) FROM icustays"
    ).fetchone()
    documented = con.execute(
        "SELECT NULL, count(DISTINCT stay_id), count(DISTINCT subject_id) FROM ("
        "  SELECT stay_id, subject_id FROM chartevents WHERE list_contains(?, itemid)"
        "  UNION SELECT stay_id, subject_id FROM procedureevents WHERE list_contains(?, itemid))",
        [inv["mimic_code_crrt_itemids"], inv["crrt_procedure_itemids"]],
    ).fetchone()

    boxes: list[tuple[str, tuple, int | None]] = [
        ("All ICU stays", icu, None),
        ("ICU stays with CRRT documented", documented, None),
        ("Circuits built from machine charting", triple("true"), None),
    ]
    remaining = "true"
    for reason, _ in EXCLUSIONS:
        before = triple(remaining)[0]
        remaining += f" AND coalesce(exclusion_reason, '') <> '{reason}'"
        after = triple(remaining)
        boxes.append((f"Excluding: {labels[reason]}", after, before - after[0]))

    cohort = triple("included")
    boxes.append(("**Analysis cohort**", cohort, None))
    boxes.append(("— flagged chronic dialysis (kept, Part 4.2)",
                  triple("included AND chronic_dialysis"), None))
    boxes.append(("Sensitivity: cohort without flagged chronic dialysis",
                  triple("included AND NOT chronic_dialysis"), None))
    boxes.append(("Sensitivity flag: also same-admission ICD",
                  triple("included AND chronic_dialysis_sensitivity"), None))
    return boxes


def render(cfg: dict[str, Any], boxes) -> str:
    small = cfg["reporting"]["small_cell_threshold"]

    # Suppressing a small "removed" cell is useless if the rows on either side
    # are exact: their difference is the suppressed number. So no exclusion
    # step may change circuits, stays or patients by 1 to small - 1. If one
    # does, merge it into a neighbouring step or drop the rule (decisions.md,
    # 2026-10-02, "Cohort rules").
    for (_, prev, _), (label, cur, _) in zip(boxes, boxes[1:]):
        if not label.startswith("Excluding"):
            continue
        for a, b in zip(prev, cur):
            if 0 < a - b < small:
                raise ValueError(f"'{label}' changes a count by {a - b} (< {small}); "
                                 "publishing both rows would disclose a small cell")

    def n(v) -> str:
        return "—" if v is None else count(v, small)

    L = [
        "# STROBE flow\n\n",
        "Generated by `uv run python -m crrt.cohort` (stage 3 of `run_all.sh`) against "
        f"`{cfg['paths']['mimic_dir']}`. Rules: `sql/crrt_cohort.sql`; decisions: "
        "`docs/decisions.md` (2026-10-02, \"Cohort rules\", \"Chronic dialysis flag\").\n\n",
        f"Counts from 1 to {small - 1} are shown as `<{small}` (Part 1.4). The unit of "
        "analysis is the circuit (Part 4.3), so circuits, stays and patients are "
        "given at every step. Each exclusion applies to what the row above it "
        "left.\n\n",
        "| Step | Circuits | Stays | Patients | Circuits removed |\n",
        "|---|--:|--:|--:|--:|\n",
    ]
    for label, (circuits, stays, patients), removed in boxes:
        L.append(f"| {label} | {n(circuits)} | {n(stays)} | {n(patients)} | {n(removed)} |\n")
    return "".join(L)


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    build(con, cfg)
    doc = render(cfg, flow(con, cfg))
    con.close()
    OUT_PATH.write_text(doc)
    print(doc)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
