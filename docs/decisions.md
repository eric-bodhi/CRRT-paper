# Decision log

Every judgment call, with its date (plan Part 14). Newest first.

## 2026-10-02 — Small-cell rule extended to percentiles and Text values

**Decision.** Everything committed or printed goes through
`crrt.report.count`, which shows counts from 1 to 9 as `<10`
(`reporting.small_cell_threshold`). Two extensions apply wherever values,
not just counts, are published, starting with `docs/itemids.md`:

- **Percentiles** are shown only when at least 10 numeric values from at
  least 10 stays stand behind them. Otherwise they are shown as —.
- **Text values** charted fewer than 10 times are not listed at all; the
  table only notes that such values exist.

**Why.** The aggregate exemption (entry below) covers counts with small cells
suppressed. A p5 or p95 over a handful of rows is close to a row-level
value. A rare value of a Text item may be free text, and free text is
explicitly not exempt.

**Where it applies.** Plan Part 1.4, `src/crrt/report.py`,
`src/crrt/itemid_inventory.py`. `docs/itemids.md` is now generated from the
full MIMIC-IV 3.1 build. Its `include? / reason` column was empty before
the regeneration, so no review was lost.

## 2026-10-02 — Primary event, unclear and death handling, ESRD, duration floor, feature windows

**Decision.** These settle feasibility §6 proposals 1, 3, 8 and 12, plus the
circuit parameters in the entry below. Values are in `config/config.yaml`.

| Question | Primary | Sensitivity | Config key |
|---|---|---|---|
| Event | `clotted` (1,674 circuits, 900 patients) | `clotted` + `clots_increasing` | `outcomes.circuit_failure.event_classes_*` |
| `undocumented` ends (1,221, 14.5%) | non-event | excluded | `unclear_handling_*` |
| Death within 12 h (877) | censored, competing risk (Part 5.3) | — | `competing_risk_classes` |
| Maximum downtime on one filter | 6 h | 4 h, 12 h | `circuits.max_downtime_hours*` |
| Chronic dialysis dependence (22% of circuits) | kept, flagged | excluded | `cohort.esrd_handling_*` |
| Minimum circuit duration | 4 h | — | `cohort.min_session_duration_hours` |
| Trend-feature windows | 3 / 6 / 12 h, slope and variance need ≥3 points | — | `features.window_hours`, `features.min_points_for_trend` |

**Why.**

- **Event = documented `Clotted` only.** `Clots Increasing` is the
  nurse-observation comparator (Part 8.1) and a candidate feature. If it is
  also in the label, it cannot be either.
- **`undocumented` as non-event.** This reverses the original plan (Part 5.1
  step 5: exclude primary, non-event sensitivity). Exclusion selects circuits
  on how they ended, which is unknowable at prediction time. About a quarter
  of these circuits are probably hidden clots (feasibility §2.4), so the
  primary is biased toward the null rather than inflated. Excluding them
  becomes the sensitivity analysis.
- **Death is censored.** A circuit running when the patient dies did not
  survive (Part 5.3). Counting it as a non-event mixes outcomes, and excluding
  it selects on a future event.
- **6 h downtime.** The event count is insensitive to it (1,657 / 1,674 /
  1,678 at 4 / 6 / 12 h). Only the undocumented bucket moves.
- **ESRD kept.** Circuit clotting is not specific to AKI. Excluding these
  patients up front would cost 22% of circuits and 337 documented clots.
- **4 h floor.** 841 circuits are under 1 h and are documentation artifacts.
  With the 2 h warm-up (Part 6.3), a 4 h circuit still has about 2 h of
  scoreable rows.
- **Windows 3 / 6 / 12 h.** Machine charting is hourly (median 60 min), so the
  old 1 h window held one point and could not produce a slope or variance.

**Where it applies.** Plan Parts 4.1, 4.2, 4.4, 5.1, 5.3 and 7. The
outcome-label stage (`run_all.sh` stage 4) reads these keys.

## 2026-10-02 — Circuits follow filter identity

**Status.** Implements proposals 1–2 of `docs/feasibility.md` §6 (branch
`feat/crrt-circuits`). `max_downtime_hours` was confirmed the same day (entry
above), pending the co-author's PR review. Every parameter below lives
in `config/config.yaml → circuits`.

**Decision.**

- A circuit is one filter, not one run of charting (Part 4.4 amended).
  Segments split at a machine-charting gap longer than
  `sessionization.gap_hours` (2 h). A later segment stays on the same filter
  unless one of these is true: it has a New Filter at its start, the segment
  before ended `Clotted` or with a documented reason, or the gap is longer
  than `circuits.max_downtime_hours`.
- `max_downtime_hours` = 6, with sensitivity analyses at 4 and 12.
- The termination class is the 9-class hierarchy of feasibility §2.3. It
  reads documentation (System Integrity, 225956, death, ICU discharge) and
  circuit age only, never pressure (§2.4).
- The documentation windows and the 66 h `reached_limit_hours` are carried
  over unchanged from the feasibility queries, so that the planning counts
  stay reproducible.
- A New Filter with no machine charting before the next one produces no
  circuit. That removes 40 circuits, none of them ≥4 h.
- `crrt_circuits` keeps every circuit. The ≥4 h floor is applied at the
  cohort step, so the STROBE flow (Part 4.6) can count what it removes.

**Why.** Under the plain 2 h gap rule, 43% of circuits ≥4 h end with no
documentation, and 66% of those resume without a New Filter (feasibility
§2.2). Those are pauses on the same filter. The documented-clot count is
insensitive to `max_downtime_hours` (1,657 / 1,674 / 1,678 at 4 / 6 / 12 h).

**Check.** On MIMIC-IV 3.1 the implementation reproduces the feasibility
prototype circuit for circuit: 9,729 circuits with identical stay, start,
end and class. That is 8,414 circuits ≥4 h (2,798 stays, 2,564 patients),
1,674 of them `clotted`.

**Still open.** The hand review of the five machine itemids and
224146/225956 in `docs/itemids.md` (Part 2.3). The feasibility vocabulary
tables (§2.1) are the evidence so far.

## 2026-10-02 — Novelty rests on the task and the outcome definition, not on model performance

**Decision.** The paper's claim is reframed (plan Parts 0, 3.1 and 3.3) around
three contributions, plus an optional fourth:

1. An hourly, per-circuit early warning, evaluated by alert budget and lead
   time.
2. A validated filter-identity circuit definition, released as a mimic-code
   concept.
3. A test of incremental value over two simple rules: the Hu 2026 pressure rule
   and nurse-charted `Clots Increasing`.
4. *(Optional)* The AUROC inflation caused by circuit-level splits and by a
   label that uses pressure.

Whether hypophosphatemia stays in this paper or becomes its own short paper is
decided at drafting. The outcomes themselves are fixed now.

**Why.**

- Yang et al. 2024 (PMID 38704337) already modelled premature circuit clotting
  on MIMIC-III/IV. It is a static model with one row per patient.
- Its AUROC is for a different task, so it cannot be the comparator.
- The feasibility work (`docs/feasibility.md` §2) showed the circuit definition
  itself is non-trivial. That is where defensible novelty lives (plan Part 0).

**Before locking.**

- Read Yang 2024 in full to confirm their definitions.
- Pre-register on OSF before any model is fit, disclosing that the feasibility
  counts were seen first.

**Where it applies.** Plan Parts 0, 3 (table and 3.1), 3.3, 8.1 and 16.

## 2026-10-02 — Aggregate results are exempt from the LLM data restriction

**Decision.** Aggregate results computed from MIMIC-IV may be used with hosted
LLM tools. That covers counts, rates, percentiles and other summary statistics,
as long as every cell under 10 is suppressed. Row-level data may not: no
individual rows, identifiers, timestamps or free-text values. Row-level data
goes only to a local model, or to a service whose zero-retention,
no-training and no-human-review terms have been verified.

**Why.**

- PhysioNet's 24 Sept 2025 post on LLMs and online services, and DUA 1.5.0,
  restrict sharing *the data*. Neither one distinguishes row-level data from
  aggregate statistics.
- The team reads aggregates as outside that restriction. They are the same kind
  of result a paper publishes: Table 1, the STROBE flow, event counts.
- The small-cell rule keeps an "aggregate" from describing one patient.

**Where it applies.** Plan Part 1.4, and `docs/feasibility.md` §7.
