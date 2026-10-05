# Predicting Intra-Treatment Complications in CRRT Patients Using MIMIC-IV

**Full Project Outline**
Eric Floyd & Mason Spurgeon · University of South Carolina
Version 0.1

> Literature claims in Part 3 came from a search of the published record and should be re-verified and properly cited before they go into a manuscript. Treat them as leads, not citations.

---

## Part 0 — The strategic call, before anything else

The niche matters, but be careful where you go looking for it. Novelty in MIMIC work almost never comes from a "notable stat" — it comes from an **outcome definition nobody has operationalized yet**. Reviewers reject "another XGBoost on MIMIC" papers; they accept papers that define a hard label carefully.

Already saturated: mortality after CRRT initiation, prediction of *who will need* CRRT, and CRRT weaning/discontinuation success. All three have multiple recent papers — successful discontinuation of CRRT in AKI patients has been modeled in MIMIC-IV with LR, decision tree, random forest, XGBoost and KNN; CRRT weaning has been modeled across two French hospitals with MIMIC-IV as external validation; a dynamic nomogram predicting CRRT need in septic patients was built on MIMIC-IV 3.0; and mortality after CRRT commencement has been done across nine algorithms with MIMIC-IV as the validation set. **Don't enter these lanes.**

Genuinely open: **intra-treatment complications** — the things that go wrong *during* CRRT, hour to hour. These are under-modeled because they require machine-level data that most databases lack and MIMIC-IV actually has (hourly circuit pressures, blood flow rate, effluent/dialysate/replacement rates, filter change events, anticoagulation).

**Update, 2026-10-02: the clotting part of this lane is now partly occupied on MIMIC.** Yang et al. 2024 (*Intensive Crit Care Nurs* 84:103703, PMID 38704337) built a premature-clotting model on MIMIC-III CareVue plus MIMIC-IV and validated it on eICU. It is a static logistic model with one row per patient, AUROC 0.877. Its predictors are summarised over the whole CRRT run, and its label counts sustained TMP >300 mmHg as clotting (full text read 2026-10-05; `docs/decisions.md`). What is still open is the dynamic version: hour by hour, per circuit. So the novelty has to come from the task and the outcome definition, exactly as the first paragraph says, not from beating anyone's AUROC. Part 3.1 sets out the contributions.

---

## Part 1 — Access and compliance (start today, runs in parallel)

**1.1 CITI training.** PhysioNet requires the CITI Program's "Data or Specimens Only Research" course. Create a CITI account → My Courses → Add affiliation → search "Massachusetts Institute of Technology Affiliates" (you affiliate with MIT because the data is hosted on MIT servers). Do not register as an independent learner — that incurs fees. When you submit, upload the training **report**, not the certificate; it's under Records → View-Print-Share on the Completion Record. This trips up most first-timers.

**1.2 Credentialing.** Submit the PhysioNet credentialing application with your mentor as reference. For students the reference must be a supervisor/PI who can attest to your training and intended use. Your mentor gets an email and must respond — give them a heads-up so it doesn't sit unread. PhysioNet states review is normally completed in 24–48 hours, though that isn't guaranteed.

**1.3 The DUA.** Credentialing alone doesn't unlock every dataset — each resource and each version carries its own DUA you must separately accept. Sign for MIMIC-IV; sign MIMIC-IV-Note too if you might ever want free text (see 5.4).

**1.4 Two constraints people miss.**
- Each user must obtain individual access rights. Sharing data within teams or classes is not permitted. You each credential separately and download separately. **Do not put the data in a shared Drive/Dropbox.** Share *code* through GitHub, never data.
- **LLM tools.** PhysioNet's "Use of MIMIC Data with Large Language Models and Online Services" (24 Sept 2025) says the DUA prohibits sending the data through APIs or online platforms, and requires any hosted service to guarantee zero data retention, no training use and no human review. Local models are unrestricted. **Team position (2026-10-02, `docs/decisions.md`): aggregate results are exempt; row-level data is not.**
  - *Exempt:* counts, rates, percentiles and other summary statistics. They may be used with hosted LLM tools, as long as every cell under 10 is suppressed.
  - *Not exempt:* individual rows, identifiers, timestamps and free-text values. These go only to a local model or to a service whose zero-retention terms have been verified.

**1.5 IRB.** BIDMC and MIT already approved the source database with a consent waiver, but your institution still needs to say something. Ask your mentor to route a non-human-subjects-research determination request — usually a one-page form, usually granted. Get the letter on file *before* you submit anywhere.

**1.6 While you wait.** The MIMIC-IV Clinical Database Demo (100 patients) is openly available with no credentialing and contains similar content excluding free-text notes. Write and debug your entire extraction pipeline against it. When credentials land you should be executing, not learning SQL.

---

## Part 2 — Infrastructure

**2.1 Storage engine.**
- **BigQuery** — MIMIC-IV is hosted there; fastest to start; costs money past the free tier; requires linking your PhysioNet account to a Google account.
- **Local PostgreSQL** — mimic-code has build scripts; ~100 GB; slow on a laptop.
- **DuckDB over the raw CSVs** — recommended for two students. Zero server setup, reads gzipped CSVs directly, fast columnar scans, runs on a laptop. `chartevents` is the only table that will hurt; convert it to Parquet once and partition by `itemid`.

**2.2 The mimic-code repository.** Clone `MIT-LCP/mimic-code`. The `mimic-iv/concepts` directory has validated derivations you should not rewrite: `crrt`, `kdigo_creatinine`, `kdigo_stages`, `sofa`, `charlson`, `vitalsign`, `bg`, `chemistry`, `coagulation`, `complete_blood_count`, `norepinephrine_equivalent_dose`, `ventilation`, `weight_durations`. Using community-validated concepts instead of hand-rolled SQL is a reviewer-satisfying move and saves weeks.

**2.3 Do not trust remembered itemids.** Every CRRT variable lives in `icu.chartevents` and `icu.procedureevents`. Derive the itemid list by joining against `icu.d_items` and filtering on label patterns, then **manually eyeball every itemid you keep** — label, unit, row count, value distribution. Blindly copying itemid lists from a blog post is the single most common source of silent errors in MIMIC papers. Start from `concepts/treatment/crrt.sql` and extend it.

**2.4 Repo hygiene.**
- `data/` in `.gitignore` from commit one
- Pinned environment (uv or conda + lockfile)
- Fixed random seeds
- `config.yaml` holding every threshold and window length — no magic numbers in code
- `Makefile` or `run_all.sh` reproducing every number in the paper from raw CSVs
- `docs/data_dictionary.md` — every derived variable gets a definition, source itemids, unit, cleaning rule

**2.5 Two-person workflow.** Branch-per-feature, PRs reviewed by the other person, no direct pushes to main. Not bureaucracy — it's the only thing that catches the label-leakage bug before it reaches your mentor.

---

## Part 3 — Endpoint selection

Score each candidate on: (a) already published on MIMIC? (b) label extractable and unambiguous? (c) enough event volume? (d) actionable if predicted?

| Candidate endpoint | Occupied? | Label quality | Actionable? | Verdict |
|---|---|---|---|---|
| Circuit/filter failure from clotting in next 6–12h | Hour-ahead work only in small single-centre cohorts; a static, per-patient MIMIC model exists (Yang 2024) | Medium-hard | Yes | **Best niche**, dynamic version only |
| Incident severe hypophosphatemia during CRRT | MIMIC work is prognostic, not predictive | Easy, lab-based | Yes | **Best safety net** |
| Citrate accumulation (total:ionized Ca ratio >2.5) | Barely touched | Medium | Yes | Strong, if citrate volume allows |
| Hemodynamic decompensation within 6h of CRRT start/UF escalation | Partly touched | Medium | Yes | Good secondary |
| CRRT-associated hypothermia | Nearly untouched | Easy | Marginal | Weak alone, fine as secondary |
| Delivered-vs-prescribed dose gap from downtime | Untouched | Medium | Yes | Novel but descriptive |
| Mortality / weaning / initiation | **Saturated** | Easy | — | Avoid |

**3.1 Why circuit failure is still the strongest angle, and where the novelty has to come from.** (Revised 2026-10-02. Evidence is in `docs/feasibility.md` §2 and §5.)

The prior work:
- **Single-centre studies.** Clotting prediction otherwise exists only in small single-centre cohorts: 636 ESKD patients in one Chinese centre, 404 sessions from 135 patients in Sichuan, a 23-patient paediatric cohort, and the pressure-trend study below.
- **On MIMIC: Yang 2024 (Part 0).** It is static and per patient. Its AUROC is for a different unit and a different task, so "beats Yang" is not a claim this paper can make.
- **The pressure-trend rule: Hu et al. 2026** (*Sci Rep* 16:17411, PMID 41981025). Longitudinal trends in blood-flow-adjusted filter pressure drop and ultrafiltration-adjusted TMP predicted clotting one hour ahead.
  - Rule: positive if ΔBFR > 0.075 mmHg/(ml/min) or ΔTFR > 0.115 mmHg/(ml/h).
  - Result: 77.1% sensitivity and 62.9% specificity, irrespective of CRRT mode.
  - Data: 96 circuits from 51 patients on a Baxter Aquarius. The authors call for validation.

The paper rests on three contributions, plus an optional fourth.

1. **A different task.** The question is not "is this patient at risk" but "will this filter clot in the next H hours", re-asked every hour (Part 6.1).
   - This is the version a nurse can act on: adjust anticoagulation, or change the filter on schedule rather than lose the blood in the circuit.
   - The evaluation follows from the task (Part 10): false alerts per shift at a fixed alert budget, lead time, and per-circuit (event-based) detection. A once-per-patient model can report none of these.
2. **The outcome definition, released as a reusable concept.**
   - MIMIC-IV has no usable reason-for-change field (350 rows). The obvious gap-based way of cutting circuits produces about 43% spurious terminations.
   - We define circuits by filter identity and validate the definition against terminal pressure signatures and clinician adjudication (Part 5.1).
   - The definition is contributed upstream to MIT-LCP/mimic-code as a `crrt_circuits` concept. That makes it citable and durable even if someone publishes a model first.
3. **A direct test of whether ML adds anything.** The model must beat two simple comparators (Part 8.1). If it does not, that is reported as the finding.
   - **The Hu 2026 pressure rule.** At about 8,400 circuits this is also the first large-scale external test of it. Report it both as published and recalibrated to hourly Prismaflex charting.
   - **The nurse's own `Clots Increasing` charting.**
4. *(Optional)* **The cost of common design errors.** Measure how much AUROC inflates when train/test is split by circuit instead of patient, and when pressure is used both to define the label and as a feature. This explains why earlier numbers look high without accusing any specific paper.

Two things to do before the protocol is locked (Part 13, weeks 3–4):
- ~~**Get Yang 2024's full text** through the USC library and confirm how they defined clotting and circuits.~~ Done 2026-10-05. The framing above stands: Yang's unit is the patient's first session, and its circuits are never defined (`docs/decisions.md`, "Yang 2024 read in full").
- **Pre-register these contributions on OSF (Part 12) before any model is fit**, so the claim is timestamped. The registration must disclose that the feasibility counts in `docs/feasibility.md` (event rates, label distributions) were seen first.

**3.2 Why you also want the hypophosphatemia arm.** Circuit failure carries real label risk (see 5.1). Hypophosphatemia is insurance: unambiguous label, high event rate — reported as high as 65% with non-phosphate-containing CRRT solutions, and 27–78% depending on dialysis intensity and duration — and the existing MIMIC-IV phosphate work is about the *impact* of phosphate levels on extubation failure and mortality, i.e. association, not forward prediction. Nobody has built "will this patient drop below 2.0 mg/dL in the next 24 hours."

**3.3 Recommended design.** Primary: circuit failure. Secondary: incident severe hypophosphatemia. Frame the paper as **"a multi-outcome early-warning framework for intra-treatment CRRT complications."** If circuit labels turn out to be garbage, you pivot the framing to electrolytes without losing the cohort work.

**Hypophosphatemia is the cleanest "first".** The 2026-10-02 search found no forward-prediction model for it in any dataset.
- Keep it in the protocol: it shares the whole pipeline.
- The outcomes are fixed now. Only the packaging waits until drafting: whether hypophosphatemia is this paper's secondary outcome or a short paper of its own.

**Decide this in week 1 and write it down.** Do not let it drift.

---

## Part 4 — Cohort construction

**4.1 Inclusion.** Adults ≥18 at ICU admission; ≥1 documented CRRT session; session duration above some floor (e.g. ≥4h) to exclude documentation artifacts.

**4.2 Exclusion.** Chronic dialysis dependence before admission (ICD + prior RRT) — unless you deliberately keep them and adjust; flag either way. ICU stays where CRRT is documented but no machine parameters exist (Metavision gaps). Stays with implausible CRRT durations. Comfort-measures-only before CRRT start.

**4.3 Unit of analysis — decide explicitly.** Patient? ICU stay? CRRT *session*? Circuit? For circuit failure the unit is the **circuit**, and one patient contributes many. This means (a) cluster your uncertainty estimates by patient and (b) split train/test **by patient, never by circuit**. Getting this wrong inflates AUROC substantially and is the most likely reason a reviewer kills the paper.

**4.4 Sessionization.** CRRT charting is intermittent. You need a rule that stitches consecutive hourly rows into sessions and defines a gap that starts a new session (e.g. >2h with no machine parameters). This rule is a paper-level decision — document it, and run sensitivity analyses at 1h and 4h.

**4.5 Expected N.** Run `SELECT COUNT(DISTINCT stay_id)` before committing. Expect low thousands of CRRT ICU stays and a larger number of circuits. If your event count is under ~100 for a given outcome, you're in a case-series regime, not a modeling regime — say so honestly rather than fitting XGBoost to it.

**4.6 STROBE flow diagram.** Build it as you go, with exact counts at each exclusion step. Not at the end.

---

## Part 5 — Outcome definition (where your novelty lives — budget 3–4 weeks)

**5.1 Circuit failure — the hard part.** MIMIC-IV charts a reason for filter/circuit change. The problem: elective changes (scheduled 72h swaps, transport, procedure interruption) look similar to clotting failures in the data. Your job is a defensible algorithm separating *premature clotting failure* from *planned termination*.

1. Extract every circuit-termination event with its documented reason.
2. Build a categorization: clotting-related / elective-scheduled / patient-related (death, transport, procedure) / unclear.
3. Support the label with corroborating signal — terminal rise in filter/transmembrane pressure, access/return pressure alarm pattern, or circuit lifespan well short of the scheduled interval. Reported median filter lifespans run roughly 17–21 hours by mode, which gives you a sanity benchmark.
4. **Have your mentor manually adjudicate a random sample of ~150 circuit terminations against your algorithm.** Report agreement (Cohen's κ). This single step converts "a student's heuristic" into "a chart-validated outcome definition" and is the most valuable hour of your mentor's time in the whole project.
5. Pre-specify how "unclear" cases are handled: excluded in primary, included as non-events in sensitivity.

**5.2 Hypophosphatemia.** Incident serum phosphate <2.0 mg/dL (moderate) or <1.0 mg/dL (severe) during CRRT, in a patient not already below threshold at prediction time. Handle repletion explicitly — the MIMIC phosphate literature has flagged unaccounted supplementation as a limitation, so account for it via `inputevents` and treat it as a competing intervention, not ignore it.

**5.3 Censoring and competing risks.** A circuit running when the patient dies did not "survive." A patient discharged from CRRT is not an event. Use time-to-event framing with death and elective discontinuation as competing risks, or be explicit that you're doing a fixed-horizon binary task and how you handle truncation. Do not silently drop censored cases.

**5.4 Notes are optional and probably a trap.** MIMIC-IV-Note could enrich labels, but it adds a DUA, huge NLP scope, and the publication restriction that individual MIMIC clinical notes cannot be published in papers without explicit patient consent. Skip for v1.

---

## Part 6 — Time structure and leakage control

**6.1 Prediction task shape.** Sliding-window: at every hour *t* during an active circuit, using only data available at or before *t*, predict whether the event occurs in (*t*, *t*+H]. Set H = 6h primary, with 3h and 12h as sensitivity.

**6.2 Blanking period.** Exclude the final 30–60 minutes before the event from the feature window. Otherwise you learn "the alarm that fired two minutes before the nurse changed the filter" — prediction of the present, not the future. State the blanking interval prominently; reviewers look for it.

**6.3 Warm-up.** Require ≥2h of circuit runtime before scoring, so trend features exist.

**6.4 The leakage checklist — run before every model fit.**
- No feature computed with post-*t* information (including "min over stay," "max during admission")
- No labs whose result timestamp precedes their `charttime` availability — MIMIC has `charttime` and `storetime`; use `storetime` for realism where available
- Nothing derived from length of stay, discharge disposition, or total CRRT duration
- No imputation statistics (means, scalers) fit on the full dataset — fit inside the training fold only
- Splits by patient, not row
- Class-balancing applied inside folds, never before splitting

**6.5 Sensible negative control.** Fit your pipeline on a shuffled label. If AUROC materially exceeds 0.5, you have leakage. Run this every time the pipeline changes.

---

## Part 7 — Features

Group them, and pre-specify the groups so you can report ablations by group.

- **Machine/circuit (your differentiator):** access pressure, filter pressure, return pressure, effluent pressure, transmembrane pressure, filter pressure drop, blood flow rate, dialysate rate, replacement rate (pre/post), ultrafiltration rate, current fluid goal, hourly net fluid removal, circuit runtime so far, CRRT mode (CVVH / CVVHD / CVVHDF / SCUF)
- **Engineered temporal features:** for each of the above over 1h/3h/6h windows — last value, mean, min, max, slope, variance — plus the flow-adjusted derivatives from the physiology literature (pressure drop normalized to blood flow rate; TMP normalized to ultrafiltration rate). These normalized ratios are exactly what the pressure-trend work found predictive, and reproducing them as engineered inputs is a strong methodological choice.
- **Anticoagulation:** heparin vs regional citrate vs none; dose; citrate rate; calcium replacement rate; ionized calcium; total:ionized calcium ratio
- **Coagulation/hematology:** platelets, INR, PTT, fibrinogen, hemoglobin, hematocrit, D-dimer where available
- **Hemodynamics:** MAP, HR, norepinephrine-equivalent dose, lactate, temperature
- **Vascular access:** site and side if documentable — a known driver of filter life, rarely available in public datasets. Worth the extraction effort.
- **Chemistry:** phosphate, potassium, magnesium, bicarbonate, BUN, creatinine, glucose, triglycerides (relevant to lipid-related circuit failure)
- **Static:** age, sex, weight, BMI, admission type, Charlson, SOFA and SAPS-II at CRRT start, primary diagnosis category, sepsis flag
- **Missingness indicators.** In ICU data, *whether* something was measured is informative. Include measurement-presence flags and time-since-last-measurement — but be aware this encodes clinician suspicion, which is a double-edged sword you should discuss.

Cleaning rules must be pre-specified: physiologic plausibility bounds per variable, unit harmonization, duplicate resolution. Put them in `config.yaml`, not scattered through notebooks.

---

## Part 8 — Modeling

**8.1 Ladder, in order. Do not skip steps.**
1. **Clinical baselines.** Two fixed decision rules. These are your "does ML beat the simple thing" comparators, and what separates a real paper from a leaderboard exercise.
   - The published two-parameter pressure rule (Hu 2026, Part 3.1), reported both as published and recalibrated.
   - The nurse-observation rule: `Clots Increasing` charted.
2. **Penalized logistic regression** on last-value features. Interpretable, cheap, often within a few points of the best model.
3. **Gradient boosting** (LightGBM/XGBoost) on the full engineered feature set. Almost certainly your headline model.
4. **Temporal model** (GRU / temporal CNN / TCN) on raw hourly sequences — only if you have the event volume. With a few hundred events this will overfit; say so rather than force it.

**8.2 Nesting.** Nested CV: outer loop for performance estimation, inner loop for hyperparameter search. Grouped by patient at both levels.

**8.3 Calibration is mandatory.** Report calibration slope, intercept, and a calibration plot for every model. An uncalibrated model cannot be used at a threshold, and a complication-flagging tool is useless without a threshold. Apply Platt scaling or isotonic regression fit inside the training fold.

**8.4 Class imbalance.** Prefer class weights and threshold tuning over SMOTE. Synthetic oversampling of ICU time series is hard to defend and wrecks calibration. If you use it, show calibration before and after.

---

## Part 9 — Validation

**9.1 Internal.** Grouped k-fold + bootstrap optimism correction.

**9.2 Temporal.** MIMIC-IV spans many years and CRRT practice changed over that span (citrate uptake in particular). Train on earlier `anchor_year_group` cohorts, test on later ones. This is a *free* and genuinely informative validation axis that most MIMIC papers ignore.

**9.3 External — pick honestly.**
- **eICU-CRD** — multi-center US, but CRRT machine-parameter granularity is poor. Fine for a coarser model; won't support circuit-pressure features.
- **SICdb**, **AmsterdamUMCdb**, **HiRID** — European, higher-resolution; worth checking whether circuit data exists.
- **MIMIC-III — do not use.** Overlaps in patients and site with MIMIC-IV. Presenting it as external validation is a known reviewer kill shot.

If no external dataset supports your feature set, say plainly that external validation is not possible for the circuit model and validate the reduced feature set externally instead. Honesty here reads as competence.

---

## Part 10 — Evaluation metrics

- **AUROC** — report it, but don't lead with it. With imbalanced outcomes it flatters.
- **AUPRC with the event prevalence stated alongside** — your headline discrimination metric.
- **Calibration** — slope, intercept, plot, Brier score.
- **Clinical operating characteristics** — at a fixed alert rate (say 1 alert per circuit per 12h), report PPV, sensitivity, and number-needed-to-alert. Nurses don't care about AUROC; they care how many false alarms per shift.
- **Event-based (not row-based) evaluation** — did the model fire at any point in the horizon before the event? Row-level metrics overstate usefulness.
- **Median lead time** for true positives. A model that fires 20 minutes ahead is worthless; 4 hours is actionable.
- **Decision curve analysis** for net benefit across thresholds.
- **Subgroup performance** — by CRRT mode, anticoagulation strategy, sex, race, age. Report it even when unflattering. Fairness reporting is increasingly expected and cheap to produce.

---

## Part 11 — Interpretation

SHAP is standard and you should include it, but treat it carefully — many MIMIC papers overclaim here.

- Present SHAP as *model explanation*, never as causal effect. Write that sentence into the paper explicitly.
- Show global importance plus 2–3 individual force plots for illustrative circuits.
- Cross-check against the clinical baseline: if the model ranks the flow-adjusted pressure parameters highly, that's convergent validity worth stating. If it doesn't, that's an interesting finding worth investigating, not something to hide.
- Run a group ablation: machine features only, clinical features only, both. This directly quantifies the value of the circuit telemetry — your central claim.

---

## Part 12 — Reporting standards and registration

- **TRIPOD+AI** — the reporting checklist for prediction models. Fill it out *at the start* as a design specification, not at the end as paperwork. It will tell you what to record.
- **PROBAST+AI** — self-assess your own risk of bias before a reviewer does.
- **Pre-register the protocol** on OSF before you look at outcome data. Timestamped pre-registration is a large credibility gain for a student project and costs an afternoon.
- **Publish the code** on GitHub with a DOI via Zenodo. Code but never data.

---

## Part 13 — Timeline (≈20 weeks, two people part-time)

| Weeks | Milestone |
|---|---|
| 0–2 | CITI, credentialing, DUA, IRB determination. In parallel: demo dataset, environment, repo scaffold. |
| 1–3 | Literature scoping. Build a structured table of ~30 CRRT+MIMIC papers: cohort, outcome, N, events, metrics. This table *is* your Introduction and your gap argument. |
| 3–4 | Lock the protocol. Pre-register. TRIPOD+AI checklist as spec. |
| 4–6 | Cohort extraction, sessionization, STROBE counts. |
| 6–9 | **Outcome definition + mentor adjudication of the 150-circuit sample.** The critical path. |
| 9–11 | Feature pipeline, leakage checklist, shuffled-label control. |
| 11–14 | Model ladder, nested CV, calibration. |
| 14–16 | Temporal validation, external validation attempt, subgroups, ablations. |
| 16–18 | Figures, tables, first full draft. |
| 18–20 | Mentor revision cycles, submission. |

**Two kill checkpoints.**
- *End of week 9:* if adjudicated agreement on circuit labels is poor (κ < 0.6), drop circuit failure to secondary and promote the electrolyte outcome.
- *End of week 14:* if event count is too small for stable estimates, reframe as a rigorous descriptive epidemiology paper on intra-treatment complication burden — still publishable, and better than a bad model.

---

## Part 14 — Division of labor

Two people, one codebase. Split by **layer**, not by task, so both of you understand the whole thing.

- **Person A (data):** SQL/extraction, itemid validation, cohort, sessionization, feature pipeline, data dictionary
- **Person B (modeling):** CV framework, model ladder, calibration, evaluation, figures
- **Both:** outcome definition (do this together — it's the intellectual core), leakage checklist review, manuscript
- **Weekly:** 30-minute sync, one shared decision log (`docs/decisions.md`) recording every judgment call and its date. When a reviewer asks "why 2 hours and not 4," you'll have the answer.
- **Mentor:** monthly checkpoint, plus the label adjudication session, plus clinical plausibility review of your final feature list

---

## Part 15 — Risk register

| Risk | Mitigation |
|---|---|
| Credentialing delayed past week 4 | Full pipeline built on demo data; nothing blocked |
| Circuit labels unreliable | Electrolyte arm already scoped; kill checkpoint at wk 9 |
| Too few events | Widen to all-cause premature circuit termination; or reframe as descriptive |
| Data leakage | Shuffled-label control every run; cross-review PRs |
| Circuit charting sparse in early years | Temporal validation split doubles as a diagnostic; restrict to years with dense charting |
| Scooped mid-project | Monthly PubMed alert on "CRRT" + "machine learning"; your chart-adjudicated label is defensible even if a similar paper appears |
| Single-center generalizability | Named as a limitation up front; attempt eICU on reduced features |

---

## Part 16 — Deliverables

1. Pre-registered protocol (OSF)
2. Public GitHub repo: extraction SQL, feature pipeline, models, `run_all.sh`, environment lockfile, data dictionary, decision log. No data.
3. `crrt_circuits` concept contributed upstream to MIT-LCP/mimic-code (Part 3.1, contribution 2)
4. Completed TRIPOD+AI checklist
5. Manuscript with STROBE flow, Table 1, discrimination + calibration figures, decision curve, subgroup table, SHAP figures, ablation table
6. Target venues, roughly in order of ambition: *Critical Care* / *Intensive Care Medicine Experimental* / *Journal of Critical Care* / *BMC Nephrology* / *Kidney360*; or *AMIA* or *CHIL* for an informatics framing

---

## The two decisions to make first

Before you write a line of SQL, nail down:

1. **Your unit of analysis** (Part 4.3)
2. **Your circuit-failure label rule** (Part 5.1)

Everything else is recoverable. Those two aren't.
