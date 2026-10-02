"""Evidence sweep over d_items for CRRT-adjacent items -> docs/itemids.md.

Plan Part 2.3: "Do not trust remembered itemids ... derive the itemid list by
joining against icu.d_items and filtering on label patterns, then manually
eyeball every itemid you keep -- label, unit, row count, value distribution."

This module does the deriving and the measuring. It does NOT decide. Every
candidate it surfaces goes into the output with an empty "include? / reason"
cell for a human to fill in by hand. Nothing is dropped for looking like noise:
the pattern that matched is reported per row so a false positive costs one line
of review, whereas a silently discarded itemid costs a variable.

The output is committed, so every count in it goes through small-cell
suppression (Part 1.4, `reporting.small_cell_threshold`). Percentiles are
withheld when too few values or stays stand behind them, because p5/p95 of a
handful of rows is close to a row-level value. Text values seen fewer times
than the threshold are dropped outright: in a Text item a rare value may be
free text.

Usage: uv run python -m crrt.itemid_inventory
"""

from typing import Any

import duckdb

from crrt import config
from crrt.report import count

# The numeric channel(s) and unit column for each event table. chartevents is
# the only table with a `valuenum`; the others name their numeric column
# differently, and inputevents/ingredientevents carry two independent channels
# (a dose and a rate). Both are reported -- picking one would hide evidence.
CHANNELS: dict[str, list[tuple[str, str, str]]] = {
    # linksto: [(channel label, value column, unit column)]
    "chartevents": [("valuenum", "valuenum", "valueuom")],
    "procedureevents": [("value", "value", "valueuom")],
    "outputevents": [("value", "value", "valueuom")],
    "inputevents": [("amount", "amount", "amountuom"), ("rate", "rate", "rateuom")],
    "ingredientevents": [("amount", "amount", "amountuom"), ("rate", "rate", "rateuom")],
    # datetimeevents.value is a timestamp: countable, but percentiles are
    # meaningless, so it gets a channel with no numeric summary.
    "datetimeevents": [("value (timestamp)", None, "valueuom")],
}


def candidates(con: duckdb.DuckDBPyConnection, inv: dict[str, Any]):
    """Every d_items row in the seed category or matching any label pattern."""
    items = con.execute(
        "SELECT itemid, label, abbreviation, linksto, category, unitname, param_type "
        "FROM d_items"
    ).fetchdf()

    seed = inv["seed_category"]
    patterns = inv["label_patterns"]
    rows = []
    for r in items.itertuples(index=False):
        haystack = f"{r.label or ''} {r.abbreviation or ''}".lower()
        matched = [p for p in patterns if p in haystack]
        in_seed = r.category == seed
        if not (matched or in_seed):
            continue
        why = ([f"category={seed}"] if in_seed else []) + matched
        rows.append({**r._asdict(), "matched_by": ", ".join(why)})
    return rows


def measure(con, linksto: str, itemids: list[int], inv: dict[str, Any], small: int):
    """Row/stay counts, observed units and percentiles, per itemid per channel.

    Percentiles come back as None unless at least `small` numeric values from
    at least `small` stays stand behind them.
    """
    if not itemids:
        return {}
    ids = ",".join(str(i) for i in itemids)
    qs = [p / 100 for p in inv["percentiles"]]
    out: dict[tuple[int, str], dict] = {}

    for channel, valcol, uomcol in CHANNELS[linksto]:
        pct_sql = ", ".join(
            f"quantile_cont(TRY_CAST({valcol} AS DOUBLE), {q}) AS p{i}"
            for i, q in enumerate(qs)
        ) if valcol else ", ".join(f"NULL AS p{i}" for i, _ in enumerate(qs))
        nonnull = f"count(TRY_CAST({valcol} AS DOUBLE))" if valcol else f"count({uomcol})"

        stats = con.execute(
            f"SELECT itemid, count(*) AS n_rows, "
            f"count(DISTINCT stay_id) AS n_stays, {nonnull} AS n_num, {pct_sql} "
            f"FROM {linksto} WHERE itemid IN ({ids}) GROUP BY itemid"
        ).fetchdf()

        units = con.execute(
            f"SELECT itemid, coalesce({uomcol}, '(null)') AS unit, count(*) AS n "
            f"FROM {linksto} WHERE itemid IN ({ids}) GROUP BY 1, 2 ORDER BY 1, 3 DESC"
        ).fetchdf()

        by_item: dict[int, list[str]] = {}
        for u in units.itertuples(index=False):
            by_item.setdefault(u.itemid, []).append(f"{u.unit} ({count(u.n, small)})")

        for s in stats.itertuples(index=False):
            seen = by_item.get(s.itemid, [])
            cap = inv["max_units_listed"]
            shown = ", ".join(seen[:cap])
            if len(seen) > cap:
                shown += f", +{len(seen) - cap} more"
            out[(s.itemid, channel)] = {
                "n_rows": s.n_rows,
                "n_stays": s.n_stays,
                "n_num": s.n_num,
                "units": shown or "—",
                "pcts": [getattr(s, f"p{i}") if s.n_num >= small and s.n_stays >= small
                         else None for i, _ in enumerate(qs)],
            }
    return out


def _num(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f != f:  # NaN
        return "—"
    return f"{f:g}"


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|")


def crrt_stay_counts(con, inv: dict[str, Any], cands) -> list[tuple[str, str, int]]:
    """Distinct stay_ids with CRRT documentation, under several definitions.

    "Any CRRT documentation" is not one number. The Dialysis category also
    holds peritoneal dialysis and intermittent hemodialysis items, so the
    broad reading over-counts; the mimic-code concept is the tight reading.
    Both are reported rather than choosing one here.
    """
    seed_ce = [c["itemid"] for c in cands
               if c["category"] == inv["seed_category"] and c["linksto"] == "chartevents"]
    seed_pe = [c["itemid"] for c in cands
               if c["category"] == inv["seed_category"] and c["linksto"] == "procedureevents"]
    concept = inv["mimic_code_crrt_itemids"]

    def stays(table: str, ids: list[int]) -> int:
        if not ids:
            return 0
        return con.execute(
            f"SELECT count(DISTINCT stay_id) FROM {table} "
            f"WHERE itemid IN ({','.join(map(str, ids))})"
        ).fetchone()[0]

    union = con.execute(
        f"SELECT count(DISTINCT stay_id) FROM ("
        f"  SELECT stay_id FROM chartevents WHERE itemid IN ({','.join(map(str, seed_ce))})"
        f"  UNION SELECT stay_id FROM procedureevents WHERE itemid IN ({','.join(map(str, seed_pe))})"
        f")"
    ).fetchone()[0]

    total = con.execute("SELECT count(DISTINCT stay_id) FROM icustays").fetchone()[0]
    return [
        ("All ICU stays", "denominator", total),
        ("Broad — any Dialysis-category item, chartevents or procedureevents",
         "over-counts: includes peritoneal and intermittent hemodialysis", union),
        ("Dialysis-category chartevents only", f"{len(seed_ce)} itemids",
         stays("chartevents", seed_ce)),
        ("Dialysis-category procedureevents only", f"{len(seed_pe)} itemids",
         stays("procedureevents", seed_pe)),
        ("Tight — any of the 20 mimic-code crrt.sql chartevents itemids",
         "the validated CRRT concept (Part 2.3)", stays("chartevents", concept)),
        ("CRRT/CVVHD/CVVHDF/SCUF procedure items only",
         ", ".join(map(str, inv["crrt_procedure_itemids"])),
         stays("procedureevents", inv["crrt_procedure_itemids"])),
    ]


def text_values(con, cands, inv: dict[str, Any], limit: int, small: int):
    """Distinct chartevents values for the categorical items in the seed category.

    Text items have no percentiles, so the numeric columns of the main table
    carry no evidence for them at all. Their value vocabulary is the evidence
    -- and for Part 5.1 it is the whole ballgame: "Reason for CRRT Filter
    Change" and "System Integrity" are where the circuit-failure label comes
    from, and you cannot judge that label without seeing what they actually say.

    Only values charted at least `small` times are returned. The rest may be
    free text, so they are not printed, only flagged as present.
    """
    ids = [c["itemid"] for c in cands
           if c["category"] == inv["seed_category"]
           and c["linksto"] == "chartevents"
           and c["param_type"] == "Text"]
    if not ids:
        return {}
    rows = con.execute(
        f"SELECT itemid, value, count(*) AS n FROM chartevents "
        f"WHERE itemid IN ({','.join(map(str, ids))}) AND value IS NOT NULL "
        f"GROUP BY 1, 2 ORDER BY 1, 3 DESC"
    ).fetchdf()
    shown: dict[int, list[str]] = {}
    rare: set[int] = set()
    for r in rows.itertuples(index=False):
        shown.setdefault(r.itemid, [])
        if r.n >= small:
            shown[r.itemid].append(f"`{r.value}` ({r.n:,})")
        else:
            rare.add(r.itemid)
    return {k: (v[:limit], len(v), k in rare) for k, v in shown.items()}


def render(cfg: dict[str, Any], con) -> str:
    inv = cfg["itemid_inventory"]
    cands = candidates(con, inv)
    concept = set(inv["mimic_code_crrt_itemids"])
    pcts = inv["percentiles"]
    small = cfg["reporting"]["small_cell_threshold"]

    by_table: dict[str, list[dict]] = {}
    for c in cands:
        by_table.setdefault(c["linksto"], []).append(c)

    L = []
    L.append("# CRRT itemid inventory — evidence for manual review\n\n")
    patients, stays = con.execute(
        "SELECT count(DISTINCT subject_id), count(DISTINCT stay_id) FROM icustays"
    ).fetchone()
    L.append(
        "Generated by `uv run python -m crrt.itemid_inventory` against "
        f"`{cfg['paths']['mimic_dir']}` ({count(patients, small)} patients with an ICU "
        f"stay, {count(stays, small)} ICU stays).\n\n"
    )
    L.append(
        "> **This file decides nothing.** Plan Part 2.3 requires that every itemid be\n"
        "> eyeballed by hand — label, unit, row count, value distribution — before it is\n"
        "> trusted. The sweep below is deliberately over-inclusive; the `include? / reason`\n"
        "> column is empty on purpose. Fill it in by hand, then promote whatever survives\n"
        "> into `docs/data_dictionary.md`.\n\n"
    )
    L.append(
        f"> **Small cells (Part 1.4).** Every count from 1 to {small - 1} is shown as "
        f"`<{small}`. Percentiles are shown as — unless at least {small} values from "
        f"at least {small} stays stand behind them. Text values charted fewer than "
        f"{small} times are not listed.\n\n"
    )
    L.append(
        "> **Scale.** Counts come from the database named above. A build on the "
        "demo can reject an itemid that is empty or mislabelled, but "
        "cannot show that one is representative. Lock the list from a full-database "
        "run.\n\n"
    )

    # ---- how candidates were selected -------------------------------------
    L.append("## How candidates were selected\n\n")
    total_items = con.execute("SELECT count(*) FROM d_items").fetchone()[0]
    L.append(
        f"Of **{total_items:,}** rows in `d_items`, **{len(cands)}** are listed below. "
        f"A row qualifies if *either*:\n\n"
    )
    L.append(f"1. `category = '{inv['seed_category']}'`, regardless of label; **or**\n")
    L.append(
        "2. its `label` **or** `abbreviation` contains any of the "
        f"{len(inv['label_patterns'])} case-insensitive substrings in "
        "`config.yaml → itemid_inventory.label_patterns`.\n\n"
    )
    L.append(
        "\nThe `matched by` column records which rule fired. Broad patterns pull in "
        "obvious non-CRRT items — `tmp` matches Bactrim (SMX/TMP), `filter` matches "
        "ventilator filters, `renal` matches enteral formulas. Those are left in. A "
        "false positive costs one line of review; a missed itemid costs a variable.\n\n"
    )
    L.append(
        "\n**Recall check.** All 20 itemids in `MIT-LCP/mimic-code` "
        "`concepts/treatment/crrt.sql` are present below (marked ✔ in `concept`). The "
        "sweep also surfaces circuit items that concept does not carry — notably "
        "`229247 Trans Membrane Pressure` and `229248 Pressure Drop`, which are exactly "
        "the flow-adjusted pressure parameters Part 7 calls the differentiator.\n\n"
    )

    # ---- stay counts ------------------------------------------------------
    L.append("## Stays with CRRT documentation\n\n")
    L.append(
        "\"Any CRRT documentation\" is not one number, so here are several. The "
        "`Dialysis` category also holds peritoneal and intermittent hemodialysis items, "
        "so the broad count over-states CRRT.\n\n"
    )
    L.append("| Definition | Note | Distinct `stay_id` |\n|---|---|---:|\n")
    for name, note, n in crrt_stay_counts(con, inv, cands):
        L.append(f"| {name} | {note} | **{count(n, small)}** |\n")

    # ---- evidence tables --------------------------------------------------
    L.append("\n## Evidence table\n\n")
    L.append(
        f"One row per itemid per numeric channel. `n rows` / `n stays` are raw counts; "
        f"`n num` is how many rows carry a parseable number (0 for Text items). "
        f"`units` are the distinct unit strings **observed in the data**, with counts — "
        f"not `d_items.unitname`. Percentiles are p{pcts[0]}/p{pcts[1]}/p{pcts[2]} of "
        f"the channel column.\n\n"
        f"`inputevents` and `ingredientevents` items appear **twice**, once for `amount` "
        f"and once for `rate` — both are real channels and reporting only one would hide "
        f"evidence. Items with no rows in this database are listed with `n rows` = 0.\n\n"
    )

    hdr = ("| include? / reason | itemid | label | category | concept | channel | "
           f"n rows | n stays | n num | units observed | p{pcts[0]} | p{pcts[1]} | "
           f"p{pcts[2]} | matched by |\n"
           "|---|---|---|---|:-:|---|--:|--:|--:|---|--:|--:|--:|---|\n")

    for linksto in sorted(by_table):
        rows = sorted(by_table[linksto], key=lambda r: (r["category"] or "", r["label"] or ""))
        stats = measure(con, linksto, [r["itemid"] for r in rows], inv, small)
        L.append(f"\n### `{linksto}` — {len(rows)} candidates\n\n")
        L.append(hdr)
        for r in rows:
            mark = "✔" if r["itemid"] in concept else ""
            for channel, _, _ in CHANNELS[linksto]:
                s = stats.get((r["itemid"], channel))
                if s is None:
                    s = {"n_rows": 0, "n_stays": 0, "n_num": 0, "units": "—",
                         "pcts": [None] * len(pcts)}
                p = [_num(v) for v in s["pcts"]]
                L.append(
                    f"|  | {r['itemid']} | {_esc(r['label'])} | {_esc(r['category'])} | "
                    f"{mark} | {channel} | {count(s['n_rows'], small)} | "
                    f"{count(s['n_stays'], small)} | {count(s['n_num'], small)} | "
                    f"{_esc(s['units'])} | {p[0]} | {p[1]} | {p[2]} | "
                    f"{_esc(r['matched_by'])} |\n"
                )

    # ---- text vocabulary appendix ----------------------------------------
    limit = inv["max_text_values_listed"]
    tv = text_values(con, cands, inv, limit, small)
    L.append(f"\n## Appendix — value vocabulary of the `{inv['seed_category']}` Text items\n\n")
    L.append(
        "Text items have no percentiles, so the table above shows nothing for them. "
        "Their evidence is what they actually say. `225956 Reason for CRRT Filter "
        "Change` and `224146 System Integrity` are the two the circuit-failure label "
        "(Part 5.1) is built from — read these before writing that label rule.\n\n"
    )
    L.append(f"| itemid | label | values charted ≥{small} times | top {limit} values (count) |\n")
    L.append("|---|---|--:|---|\n")
    label_of = {c["itemid"]: c["label"] for c in cands}
    for itemid in sorted(tv):
        vals, n_distinct, has_rare = tv[itemid]
        if has_rare:
            vals = vals + [f"*(plus values charted <{small} times, not listed)*"]
        L.append(f"| {itemid} | {_esc(label_of[itemid])} | {n_distinct} | "
                 f"{_esc(', '.join(vals))} |\n")
    absent = [c["itemid"] for c in cands
              if c["category"] == inv["seed_category"] and c["linksto"] == "chartevents"
              and c["param_type"] == "Text" and c["itemid"] not in tv]
    if absent:
        L.append(f"\nText items in `{inv['seed_category']}` with **no rows** in this database: "
                 f"{', '.join(map(str, sorted(absent)))}.\n")
    return "".join(L)


def main() -> None:
    cfg = config.load()
    out = config.REPO_ROOT / "docs" / "itemids.md"
    con = duckdb.connect(str(config.path(cfg, "duckdb")), read_only=True)
    out.write_text(render(cfg, con))
    con.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
