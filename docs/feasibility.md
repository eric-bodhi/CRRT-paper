# Feasibility on full MIMIC-IV 3.1, and what it changes in the plan

Status: **proposal for review**, 2026-10-02. Nothing here is a locked decision.
Each change in the last section needs both authors' agreement, then an entry in
`docs/decisions.md`, before it touches `config/config.yaml` or the outline.

These are **planning numbers**, not paper numbers. They come from exploratory
queries that are not part of `run_all.sh`, so they will move once the real
pipeline stages (sessionization, labels) are built and reviewed. All counts are
aggregates, and cells under 10 are suppressed.

## Bottom line

The primary outcome is feasible at volume, but **not with the label the plan
describes**. Three findings change the paper:

1. **There is no usable "reason for filter change".** The label has to come
   from `224146 System Integrity`, and circuits have to be defined by filter
   identity rather than by the 2-hour charting-gap rule.
2. **MIMIC-based clotting prediction is already published.** Yang et al. 2024
   built a static, one-row-per-patient model on MIMIC-III/IV. The open gap is
   narrower: a dynamic, circuit-level, hourly early-warning model.
3. **"Severe" hypophosphatemia (<1.0 mg/dL) has only 75 incident events.**
   That is below our own modeling floor of 100. The secondary outcome has to be
   <2.0 mg/dL.

| Outcome | Events (patients) | Verdict |
|---|---|---|
| Premature circuit failure, documented `Clotted` | 1,674 circuits (900) | **Go.** Relabelled and reframed; see §2 and §6. |
| Incident phosphate <2.0 mg/dL during CRRT | 1,253 stays (1,168) | **Go**, as the secondary outcome. |
| Incident phosphate <1.5 / <1.0 mg/dL | 546 / 75 stays | <1.5 as a sensitivity analysis; <1.0 descriptive only. |
| Citrate accumulation (total:ionized Ca >2.5) | 645 circuits (489) | Feasible but partly taken (Hu 2025). Defer. |

## 1. Data and cohort

The data is MIMIC-IV 3.1. All 33 files pass `SHA256SUMS.txt`, including
`chartevents` and `labevents`, which were assembled from parallel byte ranges.
`chartevents` has 432,997,491 rows and `labevents` has 158,374,764.

| Step | Stays | Patients |
|---|--:|--:|
| ICU stays in 3.1 | 94,458 | — |
| Any of the 20 mimic-code `crrt.sql` chartevents itemids | 3,597 | 3,103 |
| Any CRRT machine data (blood flow or any of the 4 circuit pressures) | 2,912 | 2,669 |
| ≥1 circuit ≥4 h under the filter-identity definition (§2.2) | 2,798 | 2,564 |
| *(reference)* procedureevents `225802 Dialysis - CRRT` | 2,274 | 2,095 |

That gives **8,414 circuits ≥4 h** and **341,685 scoreable circuit-hours**
(2 h warm-up, rows up to 30 min before the circuit ends).

Points that affect the plan:

- **Charting is hourly.** The median interval between machine charting times
  is 60 min (p10 26, p90 92), and 88% of intervals are ≤75 min.
- **CVVHDF dominates.** It accounts for 2,780 mode-charted stays. CVVHD has 88,
  CVVH 91 and SCUF fewer than 10, so CRRT mode cannot be a subgroup.
- **Anticoagulation is mostly regional citrate.** By circuit: citrate 6,190,
  heparin without citrate 683, neither charted 1,541. Prefilter heparin via
  `inputevents 230044` appears in fewer than 10 stays.
- **Chronic dialysis dependence is common.** ESRD/dialysis-dependence ICD codes
  are present for 570 patients and 1,889 circuits (22%). Those circuits contain
  337 of the documented clot events.

### Era effects

Approximate year is the patient's `anchor_year_group` shifted to the circuit's
date.

| Period | Circuits | TMP & Δp charted | Citrate (chart only → chart + inputevents) | Clot-terminated (classes 1–2) | Phoxillum stays |
|---|--:|--:|--:|--:|--:|
| 2008–10 | 735 | 0% | 35% → **61%** | 35% | 0 |
| 2011–13 | 1,093 | 1% | 84% → 84% | 23% | 0 |
| 2014–16 | 1,264 | 83% | 71% → 71% | 25% | 0 |
| 2017–19 | 2,386 | 100% | 73% → 74% | 26% | 0 |
| 2020–22 | 2,936 | 100% | 81% → 81% | 26% | 174 of 882 |

What the era table means:

- `229247 Trans Membrane Pressure` and `229248 Pressure Drop` do not exist
  before about 2014.
- After plausibility bounds, both can be reconstructed from the four raw
  pressures: Δp ≈ filter − return (r = 0.91), and TMP ≈ (filter + return)/2 −
  effluent (r = 0.96). There is a systematic offset, so the derived values
  track the charted ones but are not equal to them. Calibrate on 2014+.
- Without bounds, the same correlations are 0.08 and 0.19. About 0.2% of
  pressure rows are wild outliers.
- Citrate charting in `228004` is incomplete in 2008–10. Anticoagulation exposure
  must union chartevents with `inputevents` 227526/227528/227529.

## 2. Primary outcome: the label

### 2.1 The documented reason does not exist at scale

| Source | Volume | Usable as the label? |
|---|---|---|
| `225956 Reason for CRRT Filter Change` | 350 rows, 267 stays (Clotted 197, Procedure 101, Line changed 52) | No. mimic-code itself comments "only ~200 rows, not super useful" |
| `procedureevents 225436 CRRT Filter Change` | 316 rows, 240 stays | No |
| `224146 System Integrity` | 380,652 rows, 2,901 stays | **Yes** |

System Integrity vocabulary (no value has fewer than 10 rows):

| Value | Rows | Stays |
|---|--:|--:|
| Active | 286,279 | 2,878 |
| Clots Present | 61,896 | 1,934 |
| New Filter | 8,394 | 2,575 |
| No Clot Present | 6,163 | 944 |
| Clots Increasing | 4,386 | 979 |
| Discontinued | 3,754 | 1,816 |
| Reinitiated | 3,446 | 1,305 |
| Recirculating | 2,845 | 1,112 |
| Clotted | 1,959 | 1,002 |
| Line pressure inconsistent | 1,530 | 526 |

`Line pressure inconsistent` is not mapped by mimic-code `crrt.sql`. That
concept also omits 229247/229248 and the newer fluid items 230083–230085.
`230177 CRRT - Filter Type` exists in `d_items` but has no rows.

### 2.2 Circuits must follow filter identity, not charting gaps

Under the Part 4.4 rule (a new session after >2 h with no machine data):

- 58% of `New Filter` events fall in a session's first hour, because a filter
  change usually leaves a >2 h charting gap.
- Splitting circuits at every gap gives 11,737 circuits ≥4 h, and **43% of them
  end with no termination documentation**.
- Of those undocumented ends, **66% resume without a `New Filter`**. They are
  pauses or charting gaps on the same filter, not circuit ends.

**Filter-identity definition.** A new circuit starts at any of:

- a `New Filter`;
- the first segment after a documented `Clotted` or a documented reason;
- the first segment of a stay;
- a segment that follows a gap longer than *G*<sub>max</sub> = 6 h.

Shorter gaps are downtime within the same circuit.

| *G*<sub>max</sub> | Circuits ≥4 h | Documented clot | New filter, no documentation | Median life |
|--:|--:|--:|--:|--:|
| 4 h | 8,905 | 1,657 | 1,582 | 35.0 h |
| **6 h** | **8,414** | **1,674** | **1,221** | **38.8 h** |
| 12 h | 8,175 | 1,678 | 1,080 | 40.0 h |

The event count is insensitive to *G*<sub>max</sub>; only the undocumented
bucket moves.

Lifespan is median 38.8 h (IQR 18.0–66.6), and 22% of circuits reach the 72 h
limit. That is about twice the config's `expected_median_lifespan_hours:
[17, 21]`, which was flagged as unverified and is not supported as stated (§5).
A citrate-dominated practice plausibly explains the longer life.

### 2.3 How circuits end

Classes are hierarchical, for circuits ≥4 h with *G*<sub>max</sub> = 6 h.

| Class | Circuits | Patients | Median life | % |
|---|--:|--:|--:|--:|
| 1 `Clotted` charted at the end (−2 h…+3 h), or reason = Clotted | 1,674 | 900 | 24.5 h | 19.9 |
| 2 `Clots Increasing` in the last 3 h | 543 | 408 | 32.9 h | 6.5 |
| 3 death within 12 h of the circuit end | 877 | 866 | 25.0 h | 10.4 |
| 4 reached ~72 h (≥66 h) | 1,875 | 1,014 | 72.0 h | 22.3 |
| 5 procedure / line change (reason item) | 35 | 32 | 30.5 h | 0.4 |
| 6 ICU discharge within 6 h | 45 | 45 | 24.2 h | 0.5 |
| 7 CRRT ends for this stay | 1,073 | 1,004 | 33.3 h | 12.8 |
| 8 `Discontinued`/`Recirculating`, then a new filter | 1,071 | 664 | 28.0 h | 12.7 |
| 9 new filter, no termination documentation | 1,221 | 737 | 28.3 h | 14.5 |

Patients by number of clot-terminated circuits (classes 1–2): 0 → 1,492;
1 → 574; 2 → 257; 3 → 99; 4 → 49; 5 → 29; 6 → 27; 7 → 16; the tail continues
from there. The clustering is heavy, so the patient-level split and clustered
CIs are not optional.

### 2.4 Construct validity: pressures show the expected terminal rise

The table gives the median change from hours 1–4 to the last 3 h, for circuits
≥8 h.

| Class | n | Δ filter P | Δ TMP | Δ pressure drop | Share with Δp rise >20 mmHg |
|---|--:|--:|--:|--:|--:|
| 1 documented clot | 1,505 | **+41.8** | **+60.1** | **+39.1** | **0.69** |
| 2 clots increasing | 511 | +42.5 | +75.8 | +44.6 | 0.72 |
| 4 reached 72 h | 1,867 | +2.7 | +25.0 | +6.8 | 0.23 |
| 7 CRRT ends | 999 | +4.5 | +18.8 | +7.3 | 0.24 |
| 9 undocumented new filter | 1,103 | +8.8 | +23.3 | +10.3 | 0.35 |

Three things follow:

- **The documented label tracks physiology.** This is objective evidence
  available now, ahead of the week-9 adjudication checkpoint.
- **Class 9 is a mixture.** A mixture estimate on the Δp column puts about a
  quarter of it as hidden clots, roughly 300 circuits. Counting class 9 as
  non-events adds that much label noise; excluding it, as Part 5.1 step 5
  plans, removes 15% of circuits.
- **Pressure must not be part of the label.** Part 5.1 step 3 suggests using a
  terminal pressure rise to support the label. If it is folded into the label
  definition, a model built on pressure features is graded on its own inputs.
  Use pressure only to validate the label.

### 2.5 What the nurse already sees

This is the share of circuits ≥8 h with an observation in the window from 6 h
to 30 min before the end.

| | Clots Present | Clots Increasing |
|---|--:|--:|
| Documented clot | 0.54 | 0.22 |
| Reached 72 h | 0.35 | 0.01 |
| Other non-clot | 0.32 | 0.02 |

- `Clots Present` is charted on a third of circuits that never clot, so it
  barely discriminates.
- `Clots Increasing` is specific, but present before only 22% of clots.
- A "nurse observation" rule is the comparator the model has to beat, alongside
  the Hu 2026 pressure rule. `Clots Increasing` cannot be both a feature and
  part of the label (class 2).

### 2.6 Prediction-task volume

| Horizon | Positive rows: class 1 (prevalence) | Classes 1–2 (prevalence) |
|--:|--:|--:|
| 3 h | 4,514 (1.3%) | 5,974 (1.7%) |
| **6 h** | **9,230 (2.7%)** | 12,278 (3.6%) |
| 12 h | 17,539 (5.1%) | 23,490 (6.9%) |

The temporal hold-out works. 2020–22 contains 2,936 circuits, 819 patients and
619 documented clot circuits in 288 patients. The earlier periods together have
5,478 circuits and 1,055 events.

## 3. Secondary outcome: hypophosphatemia

The lab is `labevents 50970` Phosphate (mg/dL). Baseline is the last value in
the 24 h before the first circuit. There are 2,778 CRRT stays with any value in
the window.

| Threshold | At risk (baseline ≥ threshold) | Incident on CRRT | Incidence |
|---|--:|--:|--:|
| <2.0 | 2,725 | 1,253 stays (1,168 patients) | 46.0% |
| <1.5 | — | 546 | 19.9% |
| <1.0 | — | **75** | 2.7% |

Incidence of <1.0 falls over time: 4.5%, 4.7%, 3.3%, 2.4% and 1.3% across the
five periods. Incidence of <2.0 stays flat at 43–48%.

- **Sampling:** phosphate is drawn every 6.5 h (median; IQR 5.8–11.7). That
  supports a 24 h horizon, but the label exists only when blood is drawn.
- **Availability time:** for phosphate and total calcium, `storetime` trails
  `charttime` by a median of **76 min** (p90 151). The blood-gas ionized calcium
  trails by 4 min. Features must use `storetime`; the outcome time is
  `charttime`.
- **Repletion:** 897 CRRT stays (32%) receive IV phosphate (K Phos, Na Phos or
  Potassium Phosphate). In 674 of them the first dose comes after the first value
  <2.0. In 223 it comes before any value <2.0, which is treatment that can
  prevent the event. Oral phosphate in `prescriptions`/`emar` has not been
  counted yet.
- **Practice change:** Phoxillum, a phosphate-containing replacement fluid,
  appears only in 2020–22 (174 of 882 stays). It falls exactly inside the
  temporal test period and has to be a feature and a stratifier.

## 4. Citrate accumulation

Citrate circuits contain 30,140 total/ionized Ca pairs drawn within 60 min of
each other (`50893` and `50808`, iCa ≥0.6). The median ratio is 2.07 (p95
2.47), and pairs come about every 6.6 h. A ratio >2.5 occurs in **645 circuits
from 489 of 2,024 citrate patients**. Post-filter contamination of `50808` is
negligible: 0.14% of on-citrate iCa values are below 0.6.

This is feasible, but Hu ZQ et al. 2025 (*BMC Nephrol*) already published a
static MIMIC-IV 2.2 nomogram for it. They used ratio ≥2.5 plus anion-gap
acidosis, with 11.3% incidence. Recommendation: keep it out of this paper and
treat it as a possible follow-on.

## 5. Literature: what changed

Searched 2026-10-02. Yang 2024, Hu Y 2026 and Hu ZQ 2025 were checked
against their PubMed records. Every other citation here comes from the search
alone and must be re-verified before it goes into a manuscript.

- **Yang E et al. 2024**, *Intensive Crit Care Nurs* 84:103703 (PMID 38704337).
  - Premature circuit clotting, developed on MIMIC-III CareVue plus MIMIC-IV,
    externally validated on eICU, N = 2,531 patients.
  - Static logistic model with one row per patient. Predictors: temperature,
    anticoagulation, MAP, maximum TMP change within 2 h, and vasopressor.
  - External AUROC 0.877.
  - **Consequence:** the outline's "nobody has done it at scale on a public
    database" (Part 3.1) is false and must go.
  - **What remains open:** a dynamic, hourly, circuit-level early warning that
    is split by patient, has leakage controls, and is evaluated at an alert
    budget. Nothing like that has been found published or preprinted.
  - Yang's design is the natural foil. Their "max TMP change" feature sits
    close to how clotting is recognised at the bedside, the same circularity
    §2.4 warns about.
- **Hu Y et al. 2026**, *Sci Rep* 16:17411 (PMID 41981025), the source of the
  77.1% / 62.9% rule.
  - Rule: positive if ΔBFR > 0.075 mmHg/(ml/min) or ΔTFR > 0.115 mmHg/(ml/h).
    BFR = (filter − return)/Q<sub>b</sub>; TFR = TMP/Q<sub>uf</sub>.
  - Data: 51 patients, 96 circuits, Baxter Aquarius, only circuits that had a
    clotting change, and 30-min sampling near clotting.
  - MIMIC's hourly Prismaflex charting is a different regime, so the rule's
    thresholds will not transfer as-is. Report the rule both as published and
    recalibrated.
- **Hypophosphatemia forward prediction:** none found in any dataset. The
  MIMIC-IV CRRT phosphate paper (Li et al. 2025, *PLoS One*, PMID 40531977) is
  associational and uses the minimum over the whole CRRT course. That is the
  plan's own leakage example.
- **Plan claims not verified as stated:**
  - "Median filter life 17–21 h by mode." Nearest sources: Sansom 2022 gives
    CVVHDF 16.8 h and CVVHD 16.4 h; Brain 2017 gives a pooled mean of 21.9 h.
  - The 78% upper bound on hypophosphatemia incidence.
- **Competition on the same data:** Kim/Gil et al. use MIMIC-IV TMP surges with
  mortality as the outcome. It appears to be in review; the code is public at
  `github.com/5454dls/CRRT_TMP`.

## 6. Proposed changes to the plan

Each item names the Part it amends.

1. **Part 5.1, label source.** Label a circuit's termination from `224146`.
   - Primary event: class 1, documented `Clotted` (or reason = Clotted).
   - Sensitivity analysis: add class 2.
   - Drop "extract the documented reason" as step 1.
   - Keep steps 3–5, but pressure goes into **validation, never into the
     label**.
2. **Part 4.4, unit definition.** Define the *circuit* by filter identity
   (§2.2), with *G*<sub>max</sub> as the paper-level parameter.
   - Sensitivity analysis at 4 h and 12 h.
   - The 2 h gap rule survives only as the definition of downtime within a
     circuit.
3. **Part 5.1 step 5, unclear cases.** Excluding class 9 removes 15% of
   circuits, of which about a quarter are probably clots.
   - Proposed primary: classes 4–9 are non-events.
   - Proposed sensitivity: class 9 excluded.
   - Censor at death (class 3) under the Part 5.3 competing-risk framing.
4. **Part 5.1 step 4, adjudication.**
   - **The mentor must hold their own PhysioNet credential to look at rows.**
     Start that now.
   - Use a stratified sample instead of 150 random circuits. A random sample
     contains about 30 clots and 20 class-9 circuits, which says little about
     the hard cases. Suggested: 50 class 1, 50 class 9, 25 class 2, and 25 from
     classes 4/7/8.
   - Be explicit that adjudication reads the same structured charting as the
     algorithm. It measures rule fidelity, not ground truth, and §2.4 is the
     independent check.
5. **Parts 0, 3.1 and 16, framing.** Cite Yang 2024 and differentiate it.
   - The contribution: the first dynamic circuit-level early warning on a
     public database, compared against two simple rules (Hu 2026 pressure,
     nurse `Clots Increasing`), with an alert-budget evaluation.
6. **Part 5.2 and CLAUDE.md, secondary outcome.**
   - Model incident phosphate <2.0 mg/dL.
   - Sensitivity analysis at <1.5.
   - Report <1.0 descriptively only (75 events < `min_events_for_modeling`).
   - Use phosphate repletion before the first low value, and Phoxillum, as
     explicit competing interventions.
7. **Part 3, citrate accumulation.** Move it out of this paper, since it is
   partly taken (Hu 2025). That reduces scope for two part-time authors.
8. **Part 7, feature windows.** Charting is hourly, so a 1 h window has one
   point.
   - Use 3/6/12 h windows; require ≥3 points for slope and variance.
   - Derive TMP and Δp from the raw pressures for all eras, calibrated on
     2014+.
   - Anticoagulation = chartevents ∪ inputevents.
9. **Part 7 and config, cleaning first.** Fill `plausibility_bounds` before any
   feature work. 0.2% of pressure rows turn r = 0.91 into r = 0.08.
10. **Part 10, subgroups.** Drop CRRT mode (96% of mode-charted stays are CVVHDF). Anticoagulation is
    feasible, but heparin-only is small (683 circuits, 367 patients).
11. **Part 9.2, temporal split.** Keep train ≤2019 / test 2020–22, but name the
    known drift in the test era: Phoxillum, COVID-era volume, and complete TMP
    charting.
12. **Part 4.2, ESRD.** Keep these patients, add a flag, and run a sensitivity
    analysis that excludes them. Excluding them up front costs 22% of circuits.
    The clotting question is not specific to AKI. This one is for the authors
    to decide.
13. **Config.** Revisit `expected_median_lifespan_hours: [17, 21]`: the
    observed value is 38.8 h and the source is unverified. Also revisit
    `features.window_hours: [1, 3, 6]`.

The two kill checkpoints in Part 13 are effectively passed already:

- **Week-14 event count:** 1,674 events, far above 100.
- **Week-9 label quality:** §2.4 gives objective support ahead of κ.

The critical path moves to circuit identity, the definition this section turns
on, plus credentialing the mentor.

## 7. Compliance note (Part 1.4)

PhysioNet's 24 Sept 2025 post on LLMs and online services makes three points:

- The DUA "explicitly prohibits sharing access to the data with third parties,
  including sending it through APIs or using it on online platforms".
- Hosted services must provide verified zero data retention, no training use
  and no human review.
- Local models are strongly recommended.

Neither the post nor DUA 1.5.0 distinguishes row-level data from aggregate
statistics.

**Team position, 2026-10-02.** Aggregate results are exempt; row-level data is
not. The full statement is in plan Part 1.4, and the reasoning is in
`docs/decisions.md`.

The queries behind this document printed only aggregates, with cells under 10
suppressed. The one exception was a CSV-parser error message that echoed a
single raw `chartevents` line from an unrelated item; error output was then
sanitised.
