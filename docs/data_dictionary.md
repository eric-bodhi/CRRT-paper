# Data dictionary

Every derived variable: definition, source itemids, unit, cleaning rule (plan
Part 2.4). Thresholds are named by their `config/config.yaml` key rather than
restated, so this file cannot drift from the config.

## `crrt_circuits`

One row per CRRT circuit (filter). Built by `sql/crrt_circuits.sql`, run from
`uv run python -m crrt.circuits` (stage 2 of `run_all.sh`). Derivation and
evidence: `docs/feasibility.md` §2.2–2.3; decision: `docs/decisions.md`
2026-10-02.

**Sources.**

| Role | Table | itemid / column | Config key |
|---|---|---|---|
| Machine running | `chartevents` | 224144 Blood Flow (ml/min), 224149 Access Pressure, 224150 Filter Pressure, 224151 Effluent Pressure, 224152 Return Pressure | `circuits.machine_itemids` |
| Filter events | `chartevents` | 224146 System Integrity (`value`) | `circuits.system_integrity_itemid` |
| Documented reason | `chartevents` | 225956 Reason for CRRT Filter Change (`value`) | `circuits.filter_change_reason_itemid` |
| Death | `admissions` | `deathtime`, via `icustays.hadm_id` | — |
| ICU discharge | `icustays` | `outtime` | — |

**Cleaning rules.**

- A machine row counts when `valuenum` is not null. Only its charttime is
  used, never its value, so plausibility bounds do not apply here.
- Duplicate charttimes across the five machine items collapse to one.
- System Integrity and reason rows with null `value` are ignored.
- A New Filter with no machine charting before the next piece start produces
  no circuit (40 in MIMIC-IV 3.1, none of them ≥4 h).
- No row is dropped for duration. The ≥4 h floor
  (`cohort.min_session_duration_hours`) is a cohort step, applied downstream.

**Construction.** *Segments* are runs of machine charting with no gap longer
than `sessionization.gap_hours`. Each segment is cut into *pieces* at every
New Filter charted more than `circuits.new_filter_min_hours_after_segment_start`
after the segment start. Consecutive pieces of a stay are the same circuit
unless `start_reason` below is set.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id` | integer | Row number ordered by `stay_id`, `circuit_no`. Stable for a given input and config. |
| `subject_id` | integer | Patient. The grouping key for every split and CI (Part 4.3). |
| `hadm_id` | integer | From `icustays`. |
| `stay_id` | integer | ICU stay. |
| `circuit_no` | integer | 1, 2, … in time order within the stay. |
| `circuit_start` | timestamp | Start of the circuit's first piece: the first machine charttime of a segment, or the New Filter charttime that cut a segment. |
| `circuit_end` | timestamp | Last machine charttime of the circuit's last piece. |
| `duration_hours` | hours | `circuit_end − circuit_start`, including downtime. |
| `running_hours` | hours | Sum of piece durations, i.e. `duration_hours` minus gaps longer than `sessionization.gap_hours`. |
| `n_pieces` | count | Pieces stitched into the circuit. >1 means at least one pause on the same filter. |
| `start_reason` | text | Why this circuit is not a continuation of the one before. The first of these that applies: `first_of_stay`; `new_filter` (a New Filter cut the segment, or one is charted within `circuits.windows_hours.new_filter_at_start` of the start); `after_clotted` (the previous piece has `end_clotted`); `after_reason` (the previous piece has an `end_reason`); `after_long_gap` (the gap from the previous piece exceeds `circuits.max_downtime_hours`). |
| `starts_new_filter` | boolean | A New Filter documents this circuit's start (window `new_filter_at_start`). |
| `end_clotted` | boolean | System Integrity `Clotted` within `windows_hours.clotted_at_end` of `circuit_end`. |
| `end_clots_increasing` | boolean | `Clots Increasing` within `windows_hours.clots_increasing_at_end`. |
| `end_stopped` | boolean | `Discontinued` or `Recirculating` within `windows_hours.stopped_at_end`. |
| `end_reason` | text | 225956 value within `windows_hours.reason_at_end` (lexical max if several). Observed values: `Clotted`, `Procedure`, `Line changed`. |
| `end_death` | boolean | `admissions.deathtime` within `windows_hours.death_after_end`. |
| `end_icu_discharge` | boolean | `icustays.outtime` within `windows_hours.icu_discharge_after_end`. |
| `last_of_stay` | boolean | No later circuit in the stay. |
| `termination_class` | text | How the circuit ended. Hierarchical: the first rule that applies wins (feasibility §2.3, classes 1–9). The table below gives the rules. |

Every window is `[hours before, hours after]` the anchor time. Each `end_*`
flag is taken from the circuit's last piece.

| `termination_class` | Rule (first match wins) | Feasibility class |
|---|---|---|
| `clotted` | `end_clotted`, or `end_reason = 'Clotted'` | 1 |
| `clots_increasing` | `end_clots_increasing` | 2 |
| `death` | `end_death` | 3 |
| `reached_limit` | `duration_hours ≥ circuits.reached_limit_hours` | 4 |
| `procedure_or_line_change` | `end_reason` is `Procedure` or `Line changed` | 5 |
| `icu_discharge` | `end_icu_discharge` | 6 |
| `crrt_ended` | `last_of_stay` | 7 |
| `stopped_then_restarted` | `end_stopped` | 8 |
| `undocumented` | none of the above | 9 |

`termination_class` reads documentation and circuit age only, **never a
pressure**. Pressure is used to validate the label (feasibility §2.4), and a
label built from pressure would grade a pressure-based model on its own
inputs. Which classes count as events, non-events or censored is an outcome
decision (Part 5.1 step 5, Part 5.3), not part of this table.

## Source itemids

The reviewed itemid list is `config/itemid_review.yaml` (Part 2.3; decision:
`docs/decisions.md` 2026-10-02, "Itemid review"). Each include verdict names
its role and the evidence for it. A derived variable may read only itemids
included there. Its entry in this file names the itemids it uses, and its
plausibility bounds go in `features.plausibility_bounds`.

Two rules from the review apply to every derived variable:

- **Laboratory values come from `hosp.labevents`**, through the mimic-code
  concepts, never from the chartevents copies (99.6% duplicates). A result is
  available at its `storetime`, not its `charttime` (Part 6.4).
- **Circuit-period items are used only inside a circuit.** A few have rows
  outside one, e.g. 226457 Ultrafiltrate Output at 2.3% (intermittent HD,
  SCUF). Rows are matched to `crrt_circuits` on `stay_id` and time before
  use.

### Plausibility bounds

Applied to `valuenum` before any feature is computed (Part 7). Decision and
evidence: `docs/decisions.md` 2026-10-03, "Plausibility bounds for the CRRT
machine items".

| Items | Rule | Config key |
|---|---|---|
| Machine items: 224144 Blood Flow; 224149, 224150, 224151, 224152 the raw circuit pressures; 229247 TMP; 229248 Pressure Drop; 224153, 228006, 228005, 224154 replacement, post-filter, PBP and dialysate rates; 224191 Hourly Patient Fluid Removal; 226457 Ultrafiltrate Output; 225183 Current Goal; 228004 Citrate (ACD-A); 224145 Heparin Dose | A value outside [low, high] (inclusive) is set to missing. | `features.plausibility_bounds` |
| Calcium labs (`labevents`): 50808 Free Calcium, 50893 Calcium, Total | As above. Decision: `docs/decisions.md` 2026-10-04, "Anticoagulation features". | `features.plausibility_bounds` |
| Coagulation/hematology and chemistry labs (`labevents`): the 14 items of `features.lab_groups` | As above. Decision: `docs/decisions.md` 2026-10-04, "Laboratory features". | `features.plausibility_bounds` |
| Hemodynamics: 220052, 225312, 220181 mean pressures; 220045 Heart Rate; 223762, 223761 Temperature (each in its own unit); 50813 Lactate (`labevents`) | As above. Decision: `docs/decisions.md` 2026-10-04, "Hemodynamic features". | `features.plausibility_bounds` |
| Raw circuit pressures 224149, 224150, 224151, 224152 | Exception: a value past a bound by at most the margin is set to the bound (a sensor at its limit). Further out, missing. | `features.pressure_clip_margin_mmhg`, `features.pressure_clip_itemids` |

TMP and pressure drop derived from the raw pressures (feasibility §1) are
computed from the bounded raw values (`machine_features`). Charted 229247 and
229248 are bounded on their own. Items without an entry have no bound yet, and no feature may
read their values until they have one.

## `crrt_cohort`

One row per `crrt_circuits` row, with the cohort rules applied (Parts 4.1,
4.2). Built by `sql/crrt_cohort.sql`, run from `uv run python -m crrt.cohort`
(stage 3 of `run_all.sh`), which also writes the STROBE flow to
`docs/strobe.md`. Decisions: `docs/decisions.md` 2026-10-02, "Cohort rules"
and "Chronic dialysis flag". Downstream stages read `WHERE included`.

**Sources.**

| Role | Table | itemid / column | Config key |
|---|---|---|---|
| Circuits | `crrt_circuits` | all | — |
| Age | `patients`, `icustays` | `anchor_age`, `anchor_year`, `intime` | `cohort.min_age_years` |
| Admission history | `chartevents` | 225126 Dialysis patient (`valuenum`) | `cohort.chronic_dialysis.admission_history_*` |
| Last dialysis | `datetimeevents` | 225128 Last dialysis (`value`) | `cohort.chronic_dialysis.last_dialysis_itemid` |
| Tunneled catheter | `chartevents` | 227124, 229536 Dialysis Catheter Type (`value`) | `cohort.chronic_dialysis.tunneled_catheter_values` |
| Dialysis-dependence codes | `diagnoses_icd`, `admissions` | `icd_code`, `admittime` | `cohort.chronic_dialysis.icd_codes` |

**Cleaning rules.**

- No row is dropped; exclusions are flags.
- CRRT start for the chronic dialysis flag is the stay's first circuit of at
  least `cohort.min_session_duration_hours`. Evidence charted after it does
  not count (except admission history, which records pre-admission status).
- ICD codes match `icd_code` exactly, with no dots, as MIMIC stores them.
- "Earlier admission" means an admission of the same patient with an earlier
  `admittime`.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `subject_id`, `hadm_id`, `stay_id` | integer | As in `crrt_circuits`. |
| `age_years` | years | `anchor_age + year(intime) − anchor_year` (mimic-code `age`). |
| `adult` | boolean | `age_years ≥ cohort.min_age_years`. |
| `meets_min_duration` | boolean | `duration_hours ≥ cohort.min_session_duration_hours`. |
| `src_admission_history` | boolean | 225126 = `admission_history_value` charted in the stay. |
| `src_last_dialysis` | boolean | 225128 charted with a date before CRRT start. |
| `src_tunneled_catheter` | boolean | A `tunneled_catheter_values` value charted before CRRT start. |
| `src_prior_admission_icd` | boolean | An `icd_codes` code on an earlier admission. |
| `src_same_admission_icd` | boolean | An `icd_codes` code on this admission (a discharge diagnosis). |
| `chronic_dialysis` | boolean | Primary flag: any of the four pre-CRRT sources, plus same-admission ICD if `same_admission_icd_primary`. Flag only (`esrd_handling_primary`). |
| `chronic_dialysis_sensitivity` | boolean | As above with `same_admission_icd_sensitivity`. |
| `exclusion_reason` | text | First rule failed, in STROBE order: `under_min_age`, `under_min_duration`. Null if included. |
| `included` | boolean | `exclusion_reason` is null. |

## `adjudication_sample`

One row per circuit drawn for label adjudication (Part 5.1 step 4): a
stratified sample of included circuits by `termination_class`. Built by
`uv run python -m crrt.adjudication` (stage 3b of `run_all.sh`). Decisions:
`docs/decisions.md` 2026-10-04, "Adjudication sample" and "Clinical review
waits for a clinical mentor". Never committed. The fingerprint the stage
prints is what is recorded.

**Sources.**

| Role | Table | itemid / column | Config key |
|---|---|---|---|
| Frame | `crrt_circuits`, `crrt_cohort` | `termination_class`, `included` | `outcomes.circuit_failure.adjudication_strata` |
| Seed | — | — | `reproducibility.random_seed` |

**Cleaning rules.**

- The frame of a stratum is every included circuit whose
  `termination_class` is in its `classes`, sorted by `circuit_id`.
  Censored classes (`competing_risk_classes`) are in no stratum.
- One generator, seeded once, draws the strata in config order without
  replacement, then shuffles `review_order`.
- The fingerprint is a SHA-256 over the sampled `stay_id,circuit_start`
  lines, sorted. It does not depend on `circuit_id` numbering.

| Column | Type / unit | Definition |
|---|---|---|
| `review_order` | integer | 1 to the sample size. The order the adjudicator reviews in; strata are mixed. |
| `circuit_id`, `subject_id`, `stay_id`, `circuit_start`, `circuit_end` | as in `crrt_circuits` | The circuit. |
| `stratum` | text | Its `adjudication_strata` key. **Never shown to the adjudicator.** |
| `termination_class` | text | As in `crrt_circuits`. **Never shown to the adjudicator.** |
| `frame_circuits` | integer | Circuits in the stratum's frame. |
| `drawn_circuits` | integer | The stratum's `circuits`. |
| `weight` | ratio | `frame_circuits / drawn_circuits`: how many frame circuits each sampled circuit stands for, for kappa weighted back to the frame. |

`adjudication_practice` holds the practice circuits for the calibration
session: `adjudication_practice_per_stratum` per stratum, drawn by the same
generator after the sample, from the circuits the sample left. Its columns
are `practice_order` (1 to its size, strata mixed), `circuit_id`,
`subject_id`, `stay_id`, `circuit_start`, `circuit_end`, `stratum` and
`termination_class`, as above. Their verdicts are never counted.

## Verdict sheets

The adjudicator's verdicts, in `paths.adjudication_dir` on the
adjudicator's own machine. `uv run python -m crrt.adjudication_viewer build`
creates them empty, and never overwrites one that exists. The adjudication
app (`... serve`) rewrites a sheet each time a verdict button is clicked or
a note is changed. Never committed. Decision: `docs/decisions.md`
2026-10-04, "Adjudication viewer".

| File | Key column | Rows |
|---|---|---|
| `verdicts.csv` | `review_order` | One per `adjudication_sample` circuit. |
| `practice_verdicts.csv` | `practice_order` | One per `adjudication_practice` circuit. Never counted, never sent. |

| Column | Type / unit | Definition |
|---|---|---|
| `verdict` | text | One of `outcomes.circuit_failure.adjudication_verdicts`; empty until clicked. Only `clotting` is a clot. |
| `note` | free text | Optional. Stays on the adjudicator's machine, because a note can quote a charted value. |

Once every `verdicts.csv` row has a verdict,
`verdicts_send_<first 12 of adjudication_sample_sha256>.csv` is written with
`review_order` and `verdict` only. It is the one file sent back.

`uv run python -m crrt.adjudication_viewer export` packs the pages, the
app and a Python for Windows into `adjudication_pages_<first 12 of adjudication_sample_sha256>.zip`,
for handing to the adjudicator (`docs/decisions.md` 2026-10-04, "Hand the
pages to a credentialed adjudicator" and "The package runs on Python
alone"). It carries no sheet, so no machine's verdicts or notes go in it,
and a newer package unzipped over the folder never overwrites the answers.
The app (`crrt.adjudication_app`) creates any missing sheet empty, from
`sample_size` and `practice_size` in the package's `manifest.json`.

## `circuit_failure_labels`

One row per included `crrt_cohort` circuit per prediction time, with the
primary circuit-failure label (Parts 5.1, 5.3, 6.1–6.3). Built by
`sql/circuit_failure_labels.sql`, run from `uv run python -m crrt.outcomes`
(stage 4 of `run_all.sh`). Decisions: `docs/decisions.md` 2026-10-02,
"Primary event, unclear and death handling", and 2026-10-03,
"Circuit-failure prediction rows". The model stages read `WHERE scored`.

**Sources.**

| Role | Table | itemid / column | Config key |
|---|---|---|---|
| Circuits | `crrt_circuits`, `crrt_cohort` | `included` circuits | — |
| Machine running | `chartevents` | `circuits.machine_itemids` (`valuenum` not null) | `circuits.machine_itemids` |
| Documented end | `chartevents` | 224146 System Integrity `Clotted` / `Clots Increasing` | `circuits.system_integrity_itemid`, `circuits.windows_hours` |

**Cleaning rules.**

- No row is dropped. A row that is not scored names the first rule it fails.
- The documenting entry is searched in the same window `crrt_circuits` used
  to classify the circuit (`windows_hours.clotted_at_end`,
  `windows_hours.clots_increasing_at_end`), and only for circuits of that
  class.
- `label` is null on every row that is not scored.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `subject_id`, `stay_id` | integer | As in `crrt_circuits`. `subject_id` is the grouping key for splits and CIs (Part 4.3). |
| `pred_time` | timestamp | Prediction time *t*: `circuit_start + k · prediction.step_hours`, up to `circuit_end`. |
| `hours_since_start` | hours | `pred_time − circuit_start`. |
| `termination_class` | text | As in `crrt_circuits`. Never a feature. |
| `end_time` | timestamp | When the filter ended: the earlier of `circuit_end` and the first System Integrity entry documenting the class (`Clotted` for `clotted`, `Clots Increasing` for `clots_increasing`). Never a feature. |
| `not_scored_reason` | text | First rule failed, in order: `unclear_excluded` (class in `outcomes.circuit_failure.unclear_classes` and `unclear_handling` = `exclude`); `warmup` (`hours_since_start < prediction.warmup_hours`); `past_max_age` (`hours_since_start ≥ outcomes.circuit_failure.scheduled_change_interval_hours`); `blanking` (`pred_time + prediction.blanking_minutes ≥ end_time`, any class); `downtime` (no machine charting in the `sessionization.gap_hours` up to `pred_time`). Null if scored. |
| `scored` | boolean | `not_scored_reason` is null. |
| `label` | boolean | Scored rows only. Follow-up stops at the censor time, `circuit_start + scheduled_change_interval_hours`. If `end_time` is in the window (*t*, *t* + `prediction.horizon_hours`] and by the censor time: true if the class is in `event_classes`, null if it is in `competing_risk_classes`, false otherwise. If not, false when the window ends by the censor time (the filter ran through it) and null when it runs past it. |
| `censor_reason` | text | Why a scored row's `label` is null: `competing_risk` (death in the window) or `max_age` (the window runs past the censor time with the filter still up). |

## `hypophos_labels`

One row per included `crrt_cohort` circuit per prediction time, with the
incident hypophosphatemia label (Parts 3.2, 5.2, 5.3). The grid is the same
as `circuit_failure_labels`. Built by `sql/hypophos_labels.sql`, run from
`uv run python -m crrt.outcomes` (stage 4 of `run_all.sh`). Decision:
`docs/decisions.md` 2026-10-03, "Hypophosphatemia prediction rows". The
model stages read `WHERE scored`.

**Sources.**

| Role | Table | itemid / column | Config key |
|---|---|---|---|
| Circuits | `crrt_circuits`, `crrt_cohort` | `included` circuits | — |
| Phosphate | `labevents` | 50970 Phosphate, mg/dL (`valuenum`, `charttime`, `storetime`) | `outcomes.hypophosphatemia.phosphate_itemid` |
| Repletion orders | `prescriptions` | `drug` Neutra-Phos, Phosphorus by PO/NG, PO, NG; Sodium / Potassium Phosphate, Sodium Glycerophosphate by IV (`starttime`) | `outcomes.hypophosphatemia.repletion_orders` |
| Death | `admissions` | `deathtime`, via the circuit's `hadm_id` | — |

**Cleaning rules.**

- Phosphate rows with null `valuenum` are ignored. No plausibility bound is
  applied: in CRRT patients no value is ≤ 0 and the 0.1th percentile is
  0.9 mg/dL. Every row is in mg/dL.
- Phosphate and repletion are matched on `subject_id` and time, not on
  `hadm_id` or `stay_id`.
- A result is *known* at *t* when `storetime ≤ t` and `charttime ≤ t`. Three
  rows have `storetime` before `charttime`.
- Repletion is a new order, IV or oral: a `prescriptions` row whose
  `lower(drug)` is a key of `repletion_orders` and whose `route` is listed
  for it, timed at `starttime`. Doses given under an order that started
  earlier are not counted. `inputevents` and `emar` are not used, because
  their coverage changes by era.
- `label` is null on every row that is not scored.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `subject_id`, `stay_id` | integer | As in `crrt_circuits`. |
| `pred_time` | timestamp | As in `circuit_failure_labels`. |
| `known_value` | mg/dL | The latest-drawn phosphate known at `pred_time`, drawn within `known_value_max_age_hours`. |
| `known_drawn_at` | timestamp | Its `charttime`. |
| `first_low_at` | timestamp | The first phosphate below `moderate_mg_dl` drawn at or after the stay's CRRT start (its first included circuit). The event time. Never a feature. |
| `not_scored_reason` | text | First rule failed, in order: `already_low` (`first_low_at ≤ pred_time`, whether or not the result is stored); `no_known_value`; `known_low` (`known_value < moderate_mg_dl`). Null if scored. |
| `scored` | boolean | `not_scored_reason` is null. |
| `label` | boolean | Scored rows only, over (*t*, *t* + `outcomes.hypophosphatemia.horizon_hours`]. Null if `censor_reason` is set. Otherwise true if `first_low_at` is in the window, false if not. With `repletion_handling` = `composite` (a sensitivity analysis), a repletion order in the window before any low draw also makes it true. |
| `censor_reason` | text | Checked in order: `repletion` (a phosphate order, IV or oral, starts in the window before any low draw; only when `outcomes.hypophosphatemia.repletion_handling_primary` is `censor`. Under `ignore` the row is labelled from the draws alone, under `composite` it is true); `competing_risk` (no low draw in the window, and death in it); `unmeasured` (no phosphate drawn in the window). |

## `machine_features`

The machine/circuit feature group (Part 7, first bullet). One row per
`circuit_failure_labels` row, scored or not. `hypophos_labels` has the same
grid, so both outcomes join on (`circuit_id`, `pred_time`). Built by
`sql/machine_features.sql`, run from `uv run python -m crrt.features`
(stage 5 of `run_all.sh`). Decision: `docs/decisions.md` 2026-10-03,
"Machine features".

**Sources.**

| Signal | Table | itemid | Unit |
|---|---|---|---|
| `blood_flow` | `chartevents` | 224144 Blood Flow | ml/min |
| `access_pressure` | `chartevents` | 224149 Access Pressure | mmHg |
| `filter_pressure` | `chartevents` | 224150 Filter Pressure | mmHg |
| `effluent_pressure` | `chartevents` | 224151 Effluent Pressure | mmHg |
| `return_pressure` | `chartevents` | 224152 Return Pressure | mmHg |
| `replacement_rate` | `chartevents` | 224153 Replacement Rate, total of pre- and post-filter | ml/hr |
| `post_filter_replacement_rate` | `chartevents` | 228006 Post Filter Replacement Rate, part of 224153 | ml/hr |
| `pbp_rate` | `chartevents` | 228005 PBP (Prefilter) Replacement Rate | ml/hr |
| `dialysate_rate` | `chartevents` | 224154 Dialysate Rate | ml/hr |
| `fluid_removal_rate` | `chartevents` | 224191 Hourly Patient Fluid Removal, the net UF setting | mL per hour |
| `ultrafiltrate_output` | `chartevents` | 226457 Ultrafiltrate Output, achieved net removal | mL |
| `current_goal` | `chartevents` | 225183 Current Goal | mL |
| `crrt_mode_last` | `chartevents` | 227290 CRRT Mode (`value`) | text |

Names and itemids: `features.machine_signals`, `features.crrt_mode_itemid`.
Charted 229247 TMP and 229248 Pressure Drop are not used (see below).

**Cleaning rules.**

- A value counts at prediction time *t* only if `charttime ≤ t`,
  `storetime ≤ t` and `charttime ≥ circuit_start`. Values charted on another
  filter or another stay never enter.
- `valuenum` passes through `features.plausibility_bounds` first (see
  "Plausibility bounds" above). An out-of-range value is dropped, not
  counted as a measurement. The exception is a raw pressure within
  `features.pressure_clip_margin_mmhg` of a bound, which is set to the bound.
- No duplicate (`stay_id`, `itemid`, `charttime`) exists for these items in
  MIMIC-IV 3.1 inside included circuits, so no duplicate rule is applied.

**Derived signals.** Each is computed at a charttime where every component
is charted, from the bounded values. It is available at the latest
`storetime` among its components.

| Signal | Definition | Unit |
|---|---|---|
| `pressure_drop` | `filter_pressure − return_pressure` | mmHg |
| `tmp` | `(filter_pressure + return_pressure) / 2 − effluent_pressure` | mmHg |
| `uf_rate` | `pbp_rate + replacement_rate + fluid_removal_rate`: total ultrafiltration across the membrane | ml/hr |
| `pressure_drop_per_blood_flow` | `pressure_drop / blood_flow` | mmHg per ml/min |
| `tmp_per_uf_rate` | `tmp / uf_rate`, missing when `uf_rate` is 0 | mmHg per ml/hr |

The pressure formulas are the Prismaflex manual's. They are not calibrated
to the charted 229248 / 229247, which sit a constant 27 / 16.5 mmHg below
them in every era.

**Columns.** `<s>` is any signal above except `crrt_mode_last`, and `<w>` is
each of `features.window_hours`. A window is the closed interval
[*t* − *w*, *t*] on `charttime`.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `pred_time` | | As in `circuit_failure_labels`. |
| `circuit_hours` | hours | `pred_time − circuit_start`, the circuit's runtime so far. |
| `crrt_mode_last` | text | The latest-charted CRRT mode in the longest window. Null if none. |
| `<s>_last` | signal unit | The latest-charted value in the longest window. Null if none. |
| `<s>_hours_since_last` | hours | `pred_time` − the `charttime` of `<s>_last`. |
| `<s>_<w>h_n` | count | Values in the window. 0, never null, if none: the measurement-presence flag. |
| `<s>_<w>h_mean`, `_min`, `_max` | signal unit | Over the window. Null if `n` = 0. |
| `<s>_<w>h_slope` | signal unit per hour | Least-squares slope on `charttime`. Null if `n` < `features.min_points_for_trend`. |
| `<s>_<w>h_var` | signal unit² | Sample variance. Null if `n` < `features.min_points_for_trend`. |

## `anticoag_features`

The anticoagulation feature group (Part 7, third bullet). One row per
`circuit_failure_labels` row, scored or not: the same grid as
`machine_features`. Built by `sql/anticoag_features.sql`, run from
`uv run python -m crrt.features` (stage 5 of `run_all.sh`). Decision:
`docs/decisions.md` 2026-10-04, "Anticoagulation features".

**Sources.**

| Signal | Table | itemid | Unit |
|---|---|---|---|
| `citrate_rate` | `chartevents` | 228004 Citrate (ACD-A). 0 means citrate off, not missing | ml/hr |
| `heparin_dose` | `chartevents` | 224145 Heparin Dose (per hour): the heparin infusion as charted on the CRRT flowsheet | units/hr |
| `ionized_calcium` | `labevents` | 50808 Free Calcium (blood gas) | mmol/L |
| `total_calcium` | `labevents` | 50893 Calcium, Total (chemistry) | mg/dL |

Names and itemids: `features.anticoag_signals`, `features.calcium_labs`.
No `inputevents` item is read (ACD-A 227529/227528, CRRT calcium 227525,
heparin 225152, argatroban 225147, bivalirudin 225148). See the decision.

**Cleaning rules.**

- `citrate_rate`, `heparin_dose`: the `machine_features` rules. A value
  counts at *t* only if `charttime ≤ t`, `storetime ≤ t` and
  `charttime ≥ circuit_start`, and it must be inside its plausibility bound.
  Out of bound is missing, never clipped. No duplicate (`stay_id`, `itemid`,
  `charttime`) exists for either inside included circuits.
- Calcium labs: the patient's results, matched on `subject_id`, so a result
  drawn before `circuit_start` (on the previous filter, or before CRRT)
  counts. A result counts at *t* only if `charttime ≤ t`, `storetime ≤ t`,
  and `charttime ≥ t −` `features.lab_lookback_hours`, and it must be
  inside its plausibility bound. Results of one item at one `charttime`
  (26 total-calcium and under 10 ionized charttimes) are averaged and
  available at the later `storetime`. The lookback was the longest of
  `features.window_hours` until 2026-10-04 ("Laboratory features").

**Derived.**

| Name | Definition | Unit |
|---|---|---|
| `calcium_ratio` | Total calcium / `features.calcium_mg_dl_per_mmol_l` ÷ ionized calcium. Each bounded total calcium is paired with the bounded ionized calcium whose `charttime` is nearest, within `features.calcium_pair_minutes` either side, ties to the earlier draw. Timed at the total's `charttime`; available once both are stored. | ratio |
| `anticoag_class` | From `citrate_rate_last` and `heparin_dose_last`: `citrate_heparin` if both > 0; else `citrate` or `heparin` if that one is > 0; else `none` if `citrate_rate_last` = 0; else null (nothing known about citrate). | text |

**Columns.** `<s>` is `citrate_rate` or `heparin_dose`; `<c>` is
`ionized_calcium`, `total_calcium` or `calcium_ratio`; `<l>` is any of
these five; `<w>` is each of `features.window_hours`.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `pred_time` | | As in `circuit_failure_labels`. |
| `anticoag_class` | text | See above. |
| `<l>_last` | signal unit | The latest-charted value that counts at `pred_time`: in the longest window for `<s>`, in the lookback for `<c>`. Null if none. |
| `<l>_hours_since_last` | hours | `pred_time` − the `charttime` of `<l>_last`. |
| `<c>_delta`, `<c>_delta_hours` | signal unit, hours | As in `lab_features`. |
| `<s>_<w>h_n`, `_mean`, `_min`, `_max`, `_slope`, `_var` | | As in `machine_features`. |

Known misclassification in `anticoag_class` (scored rows before 2020, where
`inputevents` is complete): 18.6% of `none` rows have a 225152 heparin
infusion running and 4.9% argatroban or bivalirudin. 7.4% of `citrate` rows
have 225152 heparin running.

## `lab_features`

The coagulation/hematology and chemistry feature groups (Part 7, fourth and
seventh bullets), in one table. One row per `circuit_failure_labels` row,
scored or not: the same grid as `machine_features`. Built by
`sql/lab_features.sql`, run from `uv run python -m crrt.features` (stage 5
of `run_all.sh`). Decision: `docs/decisions.md` 2026-10-04, "Laboratory
features".

**Sources.** All from `labevents`. The group of each lab is its key in
`features.lab_groups`, the list an ablation by group reads.

| Group | Signal | itemid | Unit |
|---|---|---|---|
| `coagulation_hematology` | `platelets` | 51265 Platelet Count | K/uL |
| | `inr` | 51237 INR(PT) | ratio |
| | `ptt` | 51275 PTT. 150 is the analyser's ceiling (">150") | sec |
| | `fibrinogen` | 51214 Fibrinogen, Functional | mg/dL |
| | `hemoglobin` | 51222 Hemoglobin (blood count, not 50811 blood gas) | g/dL |
| | `hematocrit` | 51221 Hematocrit (blood count, not 50810 blood gas) | % |
| `chemistry` | `phosphate` | 50970 Phosphate, the hypophosphatemia outcome's item | mg/dL |
| | `potassium` | 50971 Potassium (serum, not 50822 whole blood) | mEq/L |
| | `magnesium` | 50960 Magnesium | mg/dL |
| | `bicarbonate` | 50882 Bicarbonate (not 50804 blood gas total CO2) | mEq/L |
| | `bun` | 51006 Urea Nitrogen | mg/dL |
| | `creatinine` | 50912 Creatinine | mg/dL |
| | `glucose` | 50931 Glucose (chemistry, not 50809 blood gas) | mg/dL |
| | `triglycerides` | 51000 Triglycerides | mg/dL |

Part 7 also lists D-dimer. It is left out (51196, 50915); see the decision.

**Cleaning rules.** The calcium labs' rules in `anticoag_features`:

- The patient's results, matched on `subject_id`, so a result drawn before
  `circuit_start` (on the previous filter, or before CRRT) counts.
- A result counts at *t* only if `charttime ≤ t`, `storetime ≤ t`, and
  `charttime ≥ t −` `features.lab_lookback_hours`.
- It must be inside its plausibility bound. Out of bound is missing, never
  clipped.
- Results of one item at one `charttime` (under 30 per item inside
  included circuits) are averaged and available at the latest `storetime`.

**Columns.** `<l>` is each signal above.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `pred_time` | | As in `circuit_failure_labels`. |
| `<l>_last` | signal unit | The value at the latest `charttime` that counts at `pred_time`. Null if none. |
| `<l>_hours_since_last` | hours | `pred_time` − the `charttime` of `<l>_last`. |
| `<l>_delta` | signal unit | `<l>_last` − the value at the `charttime` before it among results that count at `pred_time`. A result drawn earlier but not yet stored is skipped. Null if fewer than two results count. |
| `<l>_delta_hours` | hours | The `charttime` of `<l>_last` − the `charttime` of the previous result. Null with `<l>_delta`. |

## `access_features`

The vascular access feature group (Part 7, sixth bullet). One row per
`circuit_failure_labels` row, scored or not: the same grid as
`machine_features`. Built by `sql/access_features.sql`, run from
`uv run python -m crrt.features` (stage 5 of `run_all.sh`). Decision:
`docs/decisions.md` 2026-10-04, "Access features".

**Sources.**

| Signal | Table | itemid | Unit |
|---|---|---|---|
| `catheter_type` | `chartevents` | 227124 Dialysis Catheter Type (older vocabulary), 229536 Dialysis Catheter Type (newer), `value` | text |
| `catheter_age` | `datetimeevents` | 225322 Dialysis Catheter Insertion Date, `value` | days |

Names, itemids and the vocabulary map: `features.access_catheter_types`,
`features.access_insertion_date_itemid`. Site and side are not features:
224270 Dialysis Catheter `location` is filled in at removal (see the
decision).

**Cleaning rules.**

- Both are the stay's, matched on `stay_id`, so a value charted before
  `circuit_start` counts, however long before. A value counts at *t* only
  if `charttime ≤ t` and `storetime ≤ t`. The latest `charttime` wins.
- `catheter_type`: each charted value maps to `tunneled` or `temporary`
  through `features.access_catheter_types`, under its own itemid. A value
  not listed there is skipped.
- `catheter_age`: the value is read as a date (a time on it is dropped). An
  insertion date later than the date it was charted on is skipped.

**Columns.**

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `pred_time` | | As in `circuit_failure_labels`. |
| `catheter_type_last` | text | `tunneled` or `temporary`: the harmonised value at the latest `charttime` that counts at `pred_time`. Null if none. |
| `catheter_type_hours_since_last` | hours | `pred_time` − the `charttime` of `catheter_type_last`. |
| `catheter_age_days` | days, integer | The date of `pred_time` − the insertion date at the latest `charttime` that counts. 0 on the day of insertion. Null if none. |
| `catheter_insertion_date_hours_since_last` | hours | `pred_time` − the `charttime` of that insertion date. |

## `hemodynamic_features`

The hemodynamics feature group (Part 7, fifth bullet). One row per
`circuit_failure_labels` row, scored or not: the same grid as
`machine_features`. Built by `sql/hemodynamic_features.sql`, run from
`uv run python -m crrt.features` (stage 5 of `run_all.sh`). Decision:
`docs/decisions.md` 2026-10-04, "Hemodynamic features".

**Sources.** The items of each vital are mimic-code's `vitalsign` concept.

| Signal | Table | itemid | Unit |
|---|---|---|---|
| `map` | `chartevents` | 220052 Arterial Blood Pressure mean, 225312 ART BP Mean, 220181 Non Invasive Blood Pressure mean | mmHg |
| `heart_rate` | `chartevents` | 220045 Heart Rate | bpm |
| `temperature` | `chartevents` | 223762 Temperature Celsius; 223761 Temperature Fahrenheit, converted | °C |
| `lactate` | `labevents` | 50813 Lactate (blood gas, the only lactate item) | mmol/L |

Part 7 also lists the norepinephrine-equivalent dose. It is left out
(`inputevents`); see the decision.

**Cleaning rules.**

- Vitals are the stay's, matched on `stay_id`, so a value charted before
  `circuit_start` (on the previous filter, or before CRRT) counts, back to
  the longest window.
- A vital counts at *t* only if `charttime ≤ t` and `storetime ≤ t`. It must
  be inside its item's plausibility bound, in the item's own unit. Out of
  bound is missing, never clipped. Unit swaps in the temperature items
  (37 in the °F item) are therefore missing, not repaired.
- 223761 is put in °C as (value − `features.fahrenheit_freezing_point`) /
  `features.fahrenheit_per_celsius`.
- Values of one signal at one `charttime`, from one item or several (e.g.
  arterial and non-invasive mean pressure), are averaged and available at
  the latest `storetime`.
- Lactate follows `lab_features`' rules: the patient's results, matched on
  `subject_id`, counting if `charttime ≤ t`, `storetime ≤ t` and
  `charttime ≥ t −` `features.lab_lookback_hours`.

**Columns.** `<v>` is each vital (`map`, `heart_rate`, `temperature`), `<w>`
each of `features.window_hours`.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id`, `pred_time` | | As in `circuit_failure_labels`. |
| `<v>_last` | signal unit | The value at the latest `charttime` in [`pred_time` − longest window, `pred_time`] that counts. Null if none. |
| `<v>_hours_since_last` | hours | `pred_time` − the `charttime` of `<v>_last`. |
| `<v>_<w>h_n` | count | Values in [`pred_time` − `<w>` h, `pred_time`]. 0, never null, if none. |
| `<v>_<w>h_mean`, `_min`, `_max` | signal unit | Over those values. Null if none. |
| `<v>_<w>h_slope` | signal unit per hour | Least squares on `charttime`. Null below `features.min_points_for_trend` values. |
| `<v>_<w>h_var` | signal unit² | Sample variance. Null below `features.min_points_for_trend` values. |
| `lactate_last`, `lactate_hours_since_last`, `lactate_delta`, `lactate_delta_hours` | mmol/L, hours | As `<l>_last` … `<l>_delta_hours` in `lab_features`. |

## Sensitivity analysis schemas

Built by `uv run python -m crrt.sensitivity` (stage 6 of `run_all.sh`).
Decision: `docs/decisions.md` 2026-10-04, "Sensitivity analyses". Each
analysis is the primary config with one key set to its `*_sensitivity`
value, built into a schema of that name. Its tables have the columns and
rules of the `main` tables of the same name.

| Schema | Changed key | Tables built |
|---|---|---|
| `horizon_<h>h` | `prediction.horizon_hours` | `circuit_failure_labels` |
| `blanking_<m>min` | `prediction.blanking_minutes` | `circuit_failure_labels` |
| `event_clotted_clots_increasing` | `outcomes.circuit_failure.event_classes_primary` | `circuit_failure_labels` |
| `unclear_exclude` | `outcomes.circuit_failure.unclear_handling_primary` | `circuit_failure_labels` |
| `phosphate_below_1_5` | `outcomes.hypophosphatemia.moderate_mg_dl` | `hypophos_labels` |
| `repletion_<handling>` | `outcomes.hypophosphatemia.repletion_handling_primary` | `hypophos_labels` |
| `max_downtime_<h>h` | `circuits.max_downtime_hours` | `crrt_circuits` through `hemodynamic_features` |
| `segment_gap_<h>h` | `sessionization.gap_hours` | `crrt_circuits` through `hemodynamic_features` |

- A label analysis has the primary's grid (checked when it is built), so
  it joins `main.machine_features`, `main.anticoag_features`,
  `main.lab_features`, `main.access_features` and
  `main.hemodynamic_features` on (`circuit_id`,
  `pred_time`).
- A circuit analysis renumbers `circuit_id`. Join its tables only to tables
  in the same schema.
