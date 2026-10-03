# Decision log

Every judgment call, with its date (plan Part 14). Newest first.

## 2026-10-03 — Plausibility bounds for the CRRT machine items

**Decision.** `features.plausibility_bounds` now bounds the 16 numeric
`chartevents` items that `config/itemid_review.yaml` includes as circuit,
feature or comparator inputs. This settles feasibility §6 proposal 9 for the
machine items. A value outside its bound becomes missing. The exception is
the four raw circuit pressures. A value at most
`features.pressure_clip_margin_mmhg` (50) past a bound is set to the bound,
and only a value further out becomes missing. Medication rates
(`inputevents`), vitals and labs get bounds when their items are validated
for the feature stage.

**Where the numbers come from.** Bounds are the machine's own operating or
settable ranges wherever it has one, not a clinical "normal". These are
taken from the Prismaflex Service Manual (Gambro G5005209, software 7.xx,
§8 Specifications). They are identical on the PrisMax spec sheet, so they
hold whichever machine BIDMC ran in 2020–22. The pressure sensor ranges are
also tabulated in the supplement of Ferrari et al. 2022 (*ASAIO J*), which
must be re-verified before it is cited.

Evidence: chartevents rows inside included circuits, by itemid. "Dropped"
becomes missing and "clipped" is set to the bound. Counts under 10 are
suppressed.

| itemid | Item, unit | Bound | Source | Rows | Dropped (circuits) | Clipped |
|---|---|---|---|--:|--:|--:|
| 224144 | Blood Flow, ml/min | 10 to 450 | device | 311,221 | 229 (163) | — |
| 224149 | Access Pressure, mmHg | −250 to 450 | device | 339,767 | 72 (69) | 87 |
| 224150 | Filter Pressure, mmHg | −50 to 450 | device | 339,797 | 145 (124) | 96 |
| 224151 | Effluent Pressure, mmHg | −350 to 400 | device | 339,504 | 62 (58) | 28 |
| 224152 | Return Pressure, mmHg | −50 to 350 | device | 339,602 | 154 (108) | 245 |
| 229247 | Trans Membrane Pressure, mmHg | −450 to 750 | derived from the sensor ranges | 255,862 | 29 (27) | — |
| 229248 | Pressure Drop, mmHg | −400 to 500 | derived from the sensor ranges | 255,307 | 24 (22) | — |
| 224153 | Replacement Rate, ml/hr | 0 to 8,000 | device | 312,749 | 103 (18) | — |
| 228006 | Post Filter Replacement Rate, ml/hr | 0 to 8,000 | device (replacement) | 292,758 | <10 (<10) | — |
| 228005 | PBP Replacement Rate, ml/hr | 0 to 4,000 | device | 297,299 | 46 (21) | — |
| 224154 | Dialysate Rate, ml/hr | 0 to 8,000 | device | 314,878 | 27 (16) | — |
| 224191 | Hourly Patient Fluid Removal, mL | 0 to 2,000 | device | 333,470 | 415 (190) | — |
| 226457 | Ultrafiltrate Output, mL | 0 to 2,000 | the fluid-removal setting's range | 356,020 | 808 (385) | — |
| 225183 | Current Goal, mL | −2,000 to 2,000 | the fluid-removal setting's range | 326,502 | 32 (<10) | — |
| 228004 | Citrate (ACD-A), ml/hr | 0 to 350 | data: gap | 287,713 | 281 (42) | — |
| 224145 | Heparin Dose (per hour), units | 0 to 4,000 | data: end of continuous tail | 179,586 | 58 (35) | — |

No bound removes more than 0.23% of its item's rows.

**The judgment calls.**

- **Missing, not clipped, by default.** Out-of-range values are
  mostly entry errors. Medians of the far tail are values like 1,142 mmHg
  filter pressure or 1.8 million ml/min blood flow. Clipping these to the
  bound would invent a reading at the extreme.
- **Except pressures just past the sensor limit.** Out-of-range raw
  pressures are 0.63% of pressure rows in the last 3 h of clotted circuits,
  against 0.056% elsewhere. There, most sit just past the limit, such as
  filter pressure charted as 500 against a 450 limit. That is a sensor at
  its limit, charted as a round number. Dropping them would remove 154
  values just before clot events, which is informative missingness in the
  primary outcome. Clipping within 50 mmHg keeps 69 of those 154 as values
  at the limit.

  | Pressure rule | Rows dropped (clot end) | Rows clipped (clot end) | r, derived vs charted Δp / TMP |
  |---|--:|--:|---|
  | No bounds | — | — | 0.08 / 0.17 |
  | Drop all out-of-range | 942 (154) | — | 0.913 / 0.959 |
  | Clip within 25, else drop | 698 (128) | 244 (26) | 0.909 / 0.956 |
  | **Clip within 50, else drop** | 478 (85) | 464 (69) | 0.906 / 0.956 |

  These figures include charted TMP and pressure drop under the drop rule.
  Their bounds are derived, not a sensor's, so they are never clipped.
  The primary rule reproduces the feasibility §1 correlations (0.91 /
  0.96).
- **Blood flow 0 is out of range.** The pump's minimum is 10 ml/min. A zero
  means the pump is stopped, which the circuit definition already treats
  as downtime. It is not a flow to average into a window.
- **Negative settings and outputs are missing.** Fluid removal, rates and
  ultrafiltrate output cannot be set or measured below 0 on the machine.
  Ultrafiltrate output is achieved net removal: its median of 355 mL
  matches the fluid-removal setting's 365 mL. That is why it takes the
  setting's range. It is not total effluent.
- **Current Goal** is a nursing net-balance goal per hour, not a machine
  setting. A positive goal is possible, because other inputs count. It
  takes the fluid-removal range on both sides.
- **Citrate and heparin have no device range in these units.** ACD-A runs
  on an external pump. The Prismaflex syringe (2 to 100 ml/h) does not
  carry it: the median charted rate is 180 ml/hr.
  - Citrate is cut at an empty gap: no row falls in (350, 450] ml/hr. Above
    the gap are 4 circuits at a constant 500 ml/hr, 2.5× blood flow
    against a median ratio of 1.0, plus scattered errors.
  - The heparin tail decays smoothly to 4,000 units/hr. Beyond that, 30
    rows remain, 16 of them above 10,000.
  - Both cuts come from the data. They go to the mentor's clinical
    plausibility review (Part 14).

**Where it applies.** Plan Part 7. `config/config.yaml → features.plausibility_bounds`,
`pressure_clip_margin_mmhg`, `pressure_clip_itemids`. Applied by the
feature stage (not yet built). `docs/data_dictionary.md`, "Plausibility
bounds".

## 2026-10-03 — Repletion sensitivity analysis

**Decision.** `sql/hypophos_labels.sql` now has a switch for what a
repletion order does to a row: a phosphate order, IV or oral, started in the
window before any low draw. Primary: `censor`, as in the entry below.
Two sensitivity analyses bound it from either side:

- `ignore` labels the row from the draws alone. An event the order
  prevented counts as a negative, so this is the lower bound.
- `composite` counts the order as the event. Every repletion counts as an
  averted low, so this is the upper bound. It stays a sensitivity analysis
  for the reason the hypophosphatemia entry rejected it as the primary: it
  would turn a clinician's decision into the label.

Config: `outcomes.hypophosphatemia.repletion_handling_primary` (`censor`)
and `repletion_handling_sensitivity` (`[ignore, composite]`).

**Why build it now.** The censor is informative, and it is uneven across
eras. It removes 6.9 / 8.7 / 8.9 / 9.0 / 16.4% of scored rows across the
five `anchor_year_group` eras, so it weighs most in the temporal test era
(Part 9.2). `crrt.outcomes` now prints each censor reason's share of
scored rows by era, so `run_all.sh` reproduces these numbers.

**Result.** Scored rows, all eras:

| Handling | Positive / labelled rows | Prevalence | Stays with a positive row | Prevalence by era (2008–10 … 2020–22) |
|---|--:|--:|--:|---|
| censor (primary) | 25,703 / 163,674 | 15.7% | 1,298 | 16.6 / 17.1 / 14.9 / 17.5 / **12.6** |
| ignore | 28,345 / 183,119 | 15.5% | 1,302 | 16.5 / 16.7 / 15.0 / 17.5 / **12.2** |
| composite | 45,372 / 183,343 | 24.7% | 1,580 | 22.6 / 24.7 / 23.0 / 25.5 / **27.8** |

Composite labels 224 more rows than ignore. These are repleted rows that
the other two handlings censor for death or for no draw.

**Consequence.** Under the primary and ignore, the test era has the lowest
prevalence. Under composite it has the highest. The 2020–22 era looks
lower-risk partly because repletion there starts before the low draw.
Calibration in the temporal test set must be read with that in mind.
The test-era hypophosphatemia results are reported under all three
handlings (confirmed by the authors 2026-10-03).

**Where it applies.** Plan Parts 5.2, 9.2. `sql/hypophos_labels.sql`,
`src/crrt/outcomes.py` (`summarize_by_era`), `config/config.yaml →
outcomes.hypophosphatemia.repletion_handling_*`, feasibility §6
proposal 11.

## 2026-10-03 — Phosphate repletion is read from orders, oral and IV

**Decision.** The repletion censor (`censor_reason = 'repletion'`) now reads
one source for both routes: a `prescriptions` order for phosphate started in
the label window before any low draw. It replaces the `inputevents` IV doses
of the hypophosphatemia entry below, and adds oral repletion, which that
entry had not counted. Plan Part 5.2 says to account for repletion "via
`inputevents`"; this departs from that for the reason below. Config:
`outcomes.hypophosphatemia.repletion_orders`, a list of routes for each drug.

| Drug (`lower(drug)`) | Routes |
|---|---|
| neutra-phos, phosphorus (K-Phos Neutral tablets) | PO/NG, PO, NG |
| sodium phosphate, potassium phosphate, sodium glycerophosphate | IV |

**Why orders.** The censor has to mean the same thing in every era, because
the temporal split (Part 9.2) tests on 2020–22. Neither administration
record does:

| Era | `emar` charts any medication during the circuit | IV phosphate during circuits: `inputevents` / `emar` / IV orders |
|---|--:|---|
| 2008–10 | 37% of circuits | 418 / 202 / 419 |
| 2011–13 | 37% | 274 / 126 / 268 |
| 2014–16 | 71% | 304 / 247 / 316 |
| 2017–19 | 99% | 456 / 465 / 460 |
| 2020–22 | 98% | **217** / 411 / 426 |

`inputevents` loses about half of IV phosphate in 2020–22, and `emar` is
incomplete before 2017. Orders are steady. Across all drugs, the order
system's volume is 456–523 orders per 1,000 circuit-hours in every era.

**The judgment calls.**

- **Drug list.** Every drug name containing "phos" or "neutra" among cohort
  patients was reviewed by hand. The others are phosphate salts of unrelated
  drugs (codeine, dexamethasone, oseltamivir, cyclophosphamide, ...),
  Caphosol (a mouth rinse) and Fleet Phospho-soda (a bowel prep, under 10
  orders). Phosphate binders do not match the pattern and are not repletion.
  Sodium glycerophosphate (IV, 52 patients) has no `inputevents` item at all.
- **An IV order is one dose.** 4,346 of the 5,554 IV orders among cohort
  patients are for one dose in 24 h. Where a dose in `inputevents` can be
  matched to an order, the order starts a median of 60–62 min earlier in
  every era. The quartiles are 15–23 min and 119–135 min. Censoring at the order is therefore slightly early, which is
  the conservative direction. 23–37% of `inputevents` doses in each era have
  no IV order starting in the 6 h before them. These are probably doses under
  standing protocol orders, and they are not counted.
- **Only new orders count.** Doses under an order that started before *t*
  mean the patient is already on supplements at *t*. That is a feature, not
  a decision made after the prediction.
- `emar` stays the better record of what was actually given (dose times,
  "Not Given"). It can serve as a check in 2017–22. It is not loaded into the
  database.

**Result (primary).** 19,669 rows in 880 circuits are censored for
repletion, 10.1% of scored rows. That compares with 6,766 for `inputevents`
IV only and 17,410 for `inputevents` IV plus oral orders. There are 25,703
positive rows (15.7% of labelled rows; was 27,794, 15.8%). 1,298 of 2,781
at-risk stays have an incident event.

**Consequences.**

- **The censor is informative.** Repletion is started for patients drifting
  toward the threshold, and most of the rows it removes would have been
  negatives. A sensitivity analysis that does not censor on repletion, or
  treats it as part of a composite event, would bound the effect. It is not
  built yet.
- **It is heavier in the test era.** Repletion censors 6.9 / 8.7 / 8.9 /
  9.0 / 16.4% of scored rows across the five eras. Oral orders account for
  most of the rise: 4.1% → 10.1% from 2017–19 to 2020–22. IV goes from 5.3%
  to 7.5%. Oral phosphate orders per circuit-hour rise by about 40% while
  overall order volume is flat, so this is a change in practice, not in
  recording. Name it as test-era drift next to Phoxillum and complete TMP
  charting (feasibility §6 proposal 11).

**Where it applies.** Plan Part 5.2. `sql/hypophos_labels.sql`,
`config/config.yaml → outcomes.hypophosphatemia.repletion_orders`.

## 2026-10-03 — Hypophosphatemia prediction rows

**Decision.** `sql/hypophos_labels.sql` labels the secondary outcome (Part
5.2) on the same hourly grid as circuit failure. This settles feasibility §6
proposal 6. Values are in `config/config.yaml → outcomes.hypophosphatemia`.

| Question | Primary | Sensitivity / other | Config key |
|---|---|---|---|
| Threshold | < 2.0 mg/dL | < 1.5; < 1.0 descriptive only | `moderate_mg_dl`, `sensitivity_mg_dl`, `severe_mg_dl` |
| Horizon | 24 h | — | `horizon_hours` |
| At risk | known result ≥ threshold, drawn ≤ 24 h before | — | `known_value_max_age_hours` |
| IV repletion before the low draw | censored | — | `repletion_itemids` |
| Death in the window | censored | — | — |
| No draw in the window | censored | — | — |

The other judgment calls:

- **Rows are the circuit grid, without the circuit rules.** Warm-up,
  blanking, the 72 h maximum age and downtime exist for the filter. Phosphate
  is cleared by whichever filter is running, so none of them applies.
  Blanking is not needed because the event is a blood draw, not something
  the machine charts, and the result is known only at its `storetime`.
- **The event is the first draw below threshold since the stay's CRRT
  start**, timed at `charttime`. Once it has been drawn the row is no longer
  at risk (`already_low`), even before the result is stored. Scoring such a
  row would ask about an event that has already happened.
- **At risk means known to be above threshold.** The latest result stored by
  *t* and drawn in the previous 24 h must be ≥ 2.0. Without a known result,
  "not already below threshold" (Part 5.2) cannot be checked.
- **Repletion censors; it does not count as an event.** Part 5.2 calls it a
  competing intervention. An IV dose started in the window before any low
  draw may have prevented the event, so the row's outcome is not observed.
  The alternative is a composite event (low draw or repletion). It was
  rejected because it would turn a clinician's decision into the label.
  Cost: 6,766 rows in 305 circuits. Oral phosphate is not counted yet.
- **Phoxillum is a feature and a stratifier, not a censor.** A
  phosphate-containing fluid runs for the whole circuit. Censoring on it
  would remove most Phoxillum stays, all of them in 2020–22, the temporal
  test era (Part 9.2). The feature stage carries it from 230083/230084.
- **A window with no draw is censored, not negative.** The label exists only
  when blood is drawn (feasibility §3). 760 rows.

**Result (primary).** 364,036 rows; 195,343 scored. 27,794 positive rows
(15.8% of labelled rows) in 1,541 circuits and 1,216 patients. 1,301 of 2,781
at-risk stays have an incident event (46.8%), against 1,253 of 2,725 (46.0%)
in feasibility §3. Censored: 11,402 rows by death, 6,766 by repletion, 760
unmeasured. 166,518 rows are past the first low draw.

**Where it applies.** Plan Parts 3.2, 5.2, 5.3. `sql/hypophos_labels.sql`,
`src/crrt/outcomes.py`, `run_all.sh` stage 4.

## 2026-10-03 — Circuit-failure prediction rows

**Decision.** `sql/circuit_failure_labels.sql` turns each included circuit
into prediction rows (Part 6.1) and labels them with the primary event. It
reads the 2026-10-02 outcome keys unchanged. The new judgment calls:

- **Grid.** One row at `circuit_start + k · prediction.step_hours` (1 h),
  up to `circuit_end`. Every row is kept; rows that are not scored carry a
  `not_scored_reason`, so the row flow can be counted like the STROBE flow.
- **The filter ends at the earlier of the last machine charting and the
  System Integrity entry that documents its class.** In 113 of 1,674 clotted
  circuits `Clotted` is charted more than 30 min before the machine stops
  (54 more than an hour before). Taking `circuit_end` as the event time
  would score rows after the clot was charted: prediction of the present,
  the thing blanking (Part 6.2) exists to stop. 440 circuits end earlier
  under this rule.
- **Blanking applies at every circuit end, not only at events.** Which rows
  are scored then does not depend on the label. Blanking only at events
  would drop the last rows of clotted circuits and keep them for every
  other circuit, a difference the model could learn.
- **Rows in downtime are not scored.** A row with no machine charting in
  the preceding `sessionization.gap_hours` falls inside a pause on the same
  filter (`n_pieces` > 1). The rule uses only the past, so it can run in
  real time. 5,034 rows.
- **Fixed-horizon binary labels with censoring (Part 5.3).** A row is
  positive if an event end falls in (*t*, *t* + H]. If a death end falls in
  the window, the label is null with `censor_reason = 'competing_risk'`.
  Otherwise it is negative, including when the filter comes down in the
  window for a reason that is not an event.
- **Follow-up is censored at 72 h of circuit age**
  (`outcomes.circuit_failure.scheduled_change_interval_hours`). This adopts
  the proposal in the cohort entry below. Rows at 72 h or later are not
  scored (`past_max_age`). A window that runs past 72 h with the filter still
  up at 72 h has no observed outcome, so its label is null with
  `censor_reason = 'max_age'`. An end before 72 h is still observed, even
  when the window runs past 72 h. The rule uses only circuit age, which is
  known in real time. Past about 96 h these circuits look like several
  filters stitched together. 1,066 circuits run past 72 h.
  **Cost:** 65 clotted circuits clot after 72 h and lose their positive rows.
- **Blanking stays at 30 min and is still UNLOCKED** (config
  `prediction.blanking_minutes`). The 60 min sensitivity rebinds the same SQL.

**Result (primary, H = 6 h).** 364,036 rows over 8,414 circuits; 317,028
scored. Of the rows that are not scored, 19,719 are past 72 h, 16,828 are in
warm-up, 5,801 are blanked and 4,660 are in downtime. There are 8,639
positive rows (2.8% of labelled rows) in 1,608 circuits and 868 patients.
5,179 rows are censored at 72 h and 4,356 by death. Without the 72 h censor
the numbers are 9,000 positive rows (2.7%) in 1,673 circuits. The
feasibility estimate (§2.6), which had no censor, was 9,230 (2.7%).

**Where it applies.** Plan Parts 5.1, 5.3, 6.1–6.3. `sql/circuit_failure_labels.sql`,
`src/crrt/outcomes.py`, `run_all.sh` stage 4.

## 2026-10-02 — Cohort rules

**Decision.** `sql/crrt_cohort.sql` keeps every circuit and flags the
exclusions. `docs/strobe.md` is the flow diagram (Part 4.6). The steps are:

| Step | Circuits | Stays | Patients |
|---|---:|---:|---:|
| ICU stays with CRRT documented | — | 3,600 | 3,104 |
| Circuits built from machine charting | 9,729 | 2,912 | 2,669 |
| Excluding age < 18 | 9,729 | 2,912 | 2,669 |
| Excluding circuits < 4 h (analysis cohort) | 8,414 | 2,798 | 2,564 |

The judgment calls behind each step:

- **Entry box.** "CRRT documented" means any item of the mimic-code CRRT
  concept or a CRRT procedure. 688 of those stays have no circuit: they have
  CRRT documentation but no machine parameters, the Metavision gap of
  Part 4.2. They are counted in the flow, not silently lost.
- **Age.** It is computed as `anchor_age + year(intime) − anchor_year`,
  the mimic-code `age` concept. MIMIC-IV is adults only, so the step removes
  nothing. It is kept because Part 4.1 names it, and the flow shows the zero.
- **Comfort measures only is not applied.** Part 4.2 lists it. 223758 Code
  Status carries `Comfort measures only` (1,085 rows, 896 stays). Fewer than
  10 circuits start after it is first charted. Applying the rule could not
  change any result. Reporting it exactly would disclose a small cell by
  subtraction, because 8,414 is already published in this log. The methods
  can say so in one sentence.
- **No upper limit on circuit duration.** Part 4.2 mentions "implausible
  CRRT durations". 1,066 circuits run past 72 h and 112 past 120 h. Past
  96 h they look like several filters stitched together: 3.4–4.7 pieces on
  average, and only 58–69% start with a New Filter. Excluding them would
  select on total duration, which is unknown while the circuit runs. That is
  the same objection that reversed the handling of `undocumented` ends, and
  it would also raise the event rate, since their clot rate is 5–12%.
  **Proposal for the outcome stage:** stop scoring a circuit once its age
  passes `outcomes.circuit_failure.scheduled_change_interval_hours`, and
  censor it there. That rule can be applied in real time and avoids
  predicting on rows that may belong to an undocumented second filter.
- **Circuits slightly outside the ICU stay are kept.** 12 start before
  `intime`, and fewer than 10 of those by more than an hour. That is
  charting skew, not an implausible circuit.
- **CRRT start, for the chronic dialysis flag, is the stay's first circuit
  of at least 4 h.** Shorter circuits are mostly documentation artifacts. An
  artifact before the real start must not hide a tunneled catheter charted
  between the two.
- **The flow cannot leak a small cell by subtraction.** `crrt.cohort`
  refuses to write a flow in which an exclusion step changes circuits, stays
  or patients by 1–9. A future step that small must be merged into a
  neighbour or dropped.

**Where it applies.** Plan Parts 4.1, 4.2, 4.6. `sql/crrt_cohort.sql`,
`src/crrt/cohort.py`, `docs/strobe.md`, `run_all.sh` stage 3.

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
cohort.chronic_dialysis`, read by `sql/crrt_cohort.sql` (`run_all.sh`
stage 3).

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
