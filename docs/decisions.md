# Decision log

Every judgment call, with its date (plan Part 14). Newest first.

## 2026-10-02 — Chronic dialysis flag from pre-CRRT evidence only

**Decision.** The chronic dialysis flag (Part 4.2) counts only evidence that
exists before the stay's first circuit. A stay is flagged if any of these
holds:

- 225126 "Dialysis patient" = 1 (admission history);
- 225128 "Last dialysis" charted with a date before the first circuit;
- a tunneled catheter (227124 `Tunneled (PermaCath)`, 229536
  `Tunneled 2-Lumen`) charted before the first circuit;
- a dialysis-dependence ICD code on an *earlier* admission of the same
  patient.

ICD codes from the same admission count only in a sensitivity flag. The
handling itself is unchanged: kept and flagged in the primary analysis,
excluded in a sensitivity analysis. Keys: `cohort.chronic_dialysis`.

| Flag | Circuits ≥4 h | Clotted | Patients |
|---|---:|---:|---:|
| Previous: same-admission ICD only | 1,892 (22.5%) | 337 | — |
| **Primary: pre-CRRT evidence** | **1,742 (20.7%)** | **315** | **538** |
| Sensitivity: primary + same-admission ICD | 2,449 (29.1%) | 433 | — |

Contributions to the primary flag: admission history 835 circuits, last
dialysis date 583, tunneled catheter 697, ICD on an earlier admission 971.
The previous flag is reproduced exactly (1,892 circuits, 337 clots), so the
22% in the ESRD entry below was same-admission ICD. 707 circuits carried it
with no pre-CRRT evidence at all.

**Why.**

- Discharge diagnoses are coded after the admission. N18.6 or Z99.2 on the
  same admission can describe a patient who *became* dialysis dependent
  during it, which is AKI non-recovery, an outcome of the CRRT course rather
  than a baseline condition. Among stays where 225126 is charted, at least 68 have
  same-admission ICD ESRD but 225126 = 0.
- Used as a feature, a same-admission discharge code is post-*t*
  information (Part 6.4).
- The ICD list was checked against `d_icd_diagnoses`, not remembered. It
  holds ESRD, renal dialysis status or dependence, and noncompliance with
  renal dialysis. CKD stage 5 and the hypertensive "stage V or ESRD" codes
  are left out: they do not separate dialysis dependence.

**Changed from the proposal in the itemid review entry.** Intermittent HD
earlier in the same stay is *not* a source. AKI patients are often started
on IHD and moved to CRRT when they become unstable, so it would repeat the
same-admission error. 225441 and 226499 stay included, but only to describe
IHD next to CRRT.

**Limits.** "Earlier admission" means an earlier admission to this hospital.
A patient on outpatient dialysis who has never been admitted here before is
caught only by the admission history, last dialysis date or tunneled
catheter. Admission history (225126) records pre-admission status, so it
counts whenever it is charted in the stay. As a model feature, it is
available only from its charttime.

**Where it applies.** Plan Part 4.2. `config/config.yaml →
cohort.chronic_dialysis`; the cohort stage (`run_all.sh` stage 1b) reads it.

## 2026-10-02 — Itemid review

**Decision.** Every candidate in `docs/itemids.md` was reviewed by hand
against the full MIMIC-IV 3.1 build (Part 2.3): 167 itemids, 40 included and
127 excluded. Each verdict and its evidence is in `config/itemid_review.yaml`.
`crrt.itemid_inventory` copies them into `docs/itemids.md`, which it rewrites
on every run, so a verdict typed into the markdown would not survive. This
closes the "Still open" item of the circuits entry below: the five machine
itemids, 224146 and 225956 are confirmed.

| Role | Included itemids |
|---|---|
| Circuit definition | 224144, 224149–224152 (machine running); 224146, 225956 (filter events) |
| Label | 224146, 225956 |
| Comparators (Part 8.1) | 224146 `Clots Increasing`; 229247 TMP, 229248 pressure drop, and the raw pressures they derive from |
| Features: machine and prescription | 227290 mode, 224153, 228005, 228006, 224154 (replacement and dialysate rates), 224191, 226457, 225183 |
| Features: anticoagulation | 228004 citrate, 227529/227528 ACD-A, 227525 CRRT calcium, 224145 circuit heparin, 225152 systemic heparin, 225147 argatroban, 225148 bivalirudin |
| Features: access | 224270 dialysis catheter (site, insertion), 227124/229536 catheter type, 225322 insertion date |
| Hypophosphatemia | 225834 K Phos, 225835 Na Phos (repletion); 230083, 230084, 225976 (replacement fluid) |
| Cohort | 225126, 225128 (dialysis history), 227124/229536 (tunneled catheter): chronic dialysis flag; 225441, 226499 (intermittent HD, descriptive); 225802 |
| Validation only | 225436 CRRT Filter Change, 225802 CRRT procedure interval |

**Judgment calls.**

- **The sweep had a recall gap.** `phosph` does not match "K Phos" or
  "Na Phos". Those are the phosphate repletion items Part 5.2 requires, with
  418 and 854 stays with a circuit. No pattern matched "clot" either.
  `phos` and `clot` were added to `itemid_inventory.label_patterns`. Two
  other gaps were checked and left alone. A pheresis catheter is in place at
  the start of only 18 circuits. The Prismasate `inputevents` items have no
  rows.
- **Laboratory values come from `hosp.labevents`, never chartevents.** The
  chartevents lab items are copies: 225677 Phosphorous matches labevents
  50970 at the same subject and charttime in 99.6% of rows, and 229375
  Anti-Xa matches 51228 in 99.6%. Labevents carries `storetime`. For
  phosphate, storetime is a median 83 min (p95 248 min) after charttime. The
  `storetime` rule in the leakage checklist (Part 6.4) therefore changes the
  hypophosphatemia features materially; it is not a formality.
- **Pressure drop and TMP can be derived for every era.** The
  machine-computed 229248 and 229247 exist in only 2,090 stays: 38% of
  2008–2013 stays (by `anchor_year_group`), 91% of 2014–2016 and all of
  2017–2022. They track the raw pressures at a fixed offset that is the same
  in every era:
  - pressure drop ≈ filter − return − 27 mmHg, within ±10 mmHg in 75% of
    rows;
  - TMP ≈ (filter + return)/2 − effluent − 16.5 mmHg, within ±10 mmHg in 91%
    of rows.

  (Plain Pearson r is 0.07 and 0.17 because of outliers. Within each decile of
  the derived value the relationship is tight and monotone.) **Proposal for
  the feature stage, not decided here:** derive both from the raw pressures
  for every circuit, so the feature means the same thing in every era, and
  keep the charted values as a check. Report the Hu 2026 rule two ways: on
  charted values in the circuits that have them, and on derived values for
  all circuits. Because Prismaflex's computed values are offset from the
  textbook formulas, Hu's Aquarius thresholds cannot transfer unrecalibrated.
  That reinforces the recalibrated arm already in Part 3.1.
- **Anticoagulation is a core feature group, and citrate dominates it.**
  Across 8,414 circuits:

  | Agent | Circuits |
  |---|---:|
  | Citrate charted > 0 | 6,190 (74%) |
  | Circuit heparin (224145 > 0) | 1,928 |
  | Systemic heparin infusion (225152) | 1,954 |
  | Argatroban | 126 |
  | Bivalirudin | 115 |
  | None documented | 1,101 (13%) |

  228004 is the primary citrate signal. The ACD-A medication record is the
  secondary source. 227526 (citrate in mmol) records the same infusion again
  and is excluded.
- **224191 and 226457 are both kept.** They are different quantities, a
  setting and an achieved output: at the same charttime they agree within
  10 mL in only 44% of rows.
- **Exposure to phosphate-containing fluid is under-ascertained.** Phoxillium
  appears only in 230083 and 230084. Those two items cover 412 stays, two
  thirds of them in 2020–2022. Before them, the only trace is `Other` in
  225976 (2,232 rows). Part 5.2 must either name this as a limitation or
  restrict a sensitivity analysis to stays where 230083/230084 are charted.
- **Catheter site is mostly missing.** The 224270 `location` field is filled
  in 32% of rows. Lock volume (224404/224406) was tested as a proxy for site
  and does not separate sites, so it is excluded. Catheter type (tunneled vs
  temporary) is well populated and is included.

**The chronic dialysis flag.** Settled the same day; see the entry above.
The ESRD entry below flags chronic dialysis dependence from ICD codes. Discharge
diagnoses of the *same* admission (N18.6, Z99.2) can record dialysis
dependence that *began* during that admission, which is AKI non-recovery, an
outcome of the CRRT course. Among stays with a circuit where 225126 "Dialysis
patient" is charted, 68 have ICD ESRD but 225126 = 0. A flag built from
same-admission ICD would mislabel those patients. Used as a feature, it would
also be post-*t* information (Part 6.4).

Proposal for the cohort stage: flag only on evidence that exists before the
first circuit:
- 225126 = 1, or 225128 charted;
- a tunneled catheter (227124/229536) charted before the first circuit;
- intermittent HD (225441/226499) before the first circuit;
- an ESRD ICD code on a *prior* admission.

Same-admission ICD would then be a sensitivity analysis.

**Where it applies.** Plan Parts 2.3, 4.2, 5.2, 6.4 and 7.
`config/itemid_review.yaml`, `config/config.yaml →
itemid_inventory.label_patterns`, `src/crrt/itemid_inventory.py`,
`docs/itemids.md`.

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
