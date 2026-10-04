"""Draw the label adjudication sample (Part 5.1 step 4) -> `adjudication_sample`.

A stratified sample of included circuits by `termination_class`, one stratum
per `outcomes.circuit_failure.adjudication_strata` entry, drawn with
`reproducibility.random_seed` (docs/decisions.md 2026-10-04, "Adjudication
sample"). It is frozen before any model is fit, so model output cannot steer
which circuits a clinician reviews ("Clinical review waits for a clinical
mentor").

The table is row-level data and is never committed (Part 2.4). What is
committed is the fingerprint this module prints: a SHA-256 over the sampled
circuits' (stay_id, circuit_start), which do not depend on row numbering. A
rerun on the same data reproduces the sample, and a matching fingerprint
proves it. A different fingerprint means the sample moved and must be logged.

`review_order` shuffles the strata together, so a circuit's position does
not reveal its stratum. `stratum` and `termination_class` are for the
analysis only; nothing shown to the adjudicator may include them. `weight`
is the stratum's frame size over the circuits drawn, for kappa weighted
back to the frame.

Prints aggregates only, every count under `reporting.small_cell_threshold`
suppressed (Part 1.4).

Usage: uv run python -m crrt.adjudication
"""

import hashlib
from typing import Any

import duckdb
import numpy as np

from crrt import config
from crrt.report import count


def draw(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Build `adjudication_sample` from crrt_circuits and crrt_cohort."""
    strata = cfg["outcomes"]["circuit_failure"]["adjudication_strata"]
    rng = np.random.default_rng(cfg["reproducibility"]["random_seed"])
    drawn: list[tuple] = []
    for name, s in strata.items():
        # Sorted, so the same seed picks the same circuits on any machine.
        frame = [r[0] for r in con.execute(
            "SELECT c.circuit_id FROM crrt_circuits AS c "
            "JOIN crrt_cohort AS k USING (circuit_id) "
            "WHERE k.included AND list_contains(?, c.termination_class) "
            "ORDER BY c.circuit_id",
            [s["classes"]],
        ).fetchall()]
        n = s["circuits"]
        if len(frame) < n:
            raise ValueError(f"stratum {name}: {n} circuits requested, and the frame is smaller")
        picked = sorted(rng.choice(len(frame), size=n, replace=False))
        drawn += [(frame[i], name, len(frame), n) for i in picked]
    order = rng.permutation(len(drawn)) + 1

    con.execute("CREATE OR REPLACE TEMP TABLE adjudication_drawn (circuit_id BIGINT, "
                "stratum VARCHAR, frame_circuits INTEGER, drawn_circuits INTEGER, "
                "review_order INTEGER)")
    con.executemany("INSERT INTO adjudication_drawn VALUES (?, ?, ?, ?, ?)",
                    [(*d, int(o)) for d, o in zip(drawn, order)])
    con.execute(
        "CREATE OR REPLACE TABLE adjudication_sample AS "
        "SELECT d.review_order, c.circuit_id, c.subject_id, c.stay_id, "
        "       c.circuit_start, c.circuit_end, d.stratum, c.termination_class, "
        "       d.frame_circuits, d.drawn_circuits, "
        "       d.frame_circuits / d.drawn_circuits AS weight "
        "FROM adjudication_drawn AS d JOIN crrt_circuits AS c USING (circuit_id) "
        "ORDER BY d.review_order"
    )


def fingerprint(con: duckdb.DuckDBPyConnection) -> str:
    """SHA-256 over the sampled (stay_id, circuit_start), in a fixed order."""
    rows = con.execute(
        "SELECT stay_id, circuit_start FROM adjudication_sample "
        "ORDER BY stay_id, circuit_start"
    ).fetchall()
    text = "\n".join(f"{stay},{start.isoformat()}" for stay, start in rows)
    return hashlib.sha256(text.encode()).hexdigest()


def summarize(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    small = cfg["reporting"]["small_cell_threshold"]
    rows = con.execute(
        "SELECT stratum, any_value(frame_circuits), count(*), "
        "       count(DISTINCT subject_id), any_value(weight) "
        "FROM adjudication_sample GROUP BY stratum ORDER BY stratum"
    ).fetchall()
    print(f"{'stratum':18s} {'frame':>7s} {'drawn':>6s} {'patients':>9s} {'weight':>7s}")
    for stratum, frame, n, patients, weight in rows:
        print(f"{stratum:18s} {count(frame, small):>7s} {count(n, small):>6s} "
              f"{count(patients, small):>9s} {weight:>7.2f}")
    total, patients = con.execute(
        "SELECT count(*), count(DISTINCT subject_id) FROM adjudication_sample"
    ).fetchone()
    print(f"{'total':18s} {'':>7s} {count(total, small):>6s} {count(patients, small):>9s}")
    print(f"\nfingerprint (sha256 of stay_id, circuit_start): {fingerprint(con)}")


def main() -> None:
    cfg = config.load()
    con = duckdb.connect(str(config.path(cfg, "duckdb")))
    draw(con, cfg)
    summarize(con, cfg)
    con.close()


if __name__ == "__main__":
    main()
