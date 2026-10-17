# Before OSF pre-registration — checklist

Plan Part 12 and the 2026-10-02 decision ("Novelty rests on the task and the
outcome definition") require pre-registration on OSF **before any model is
fit**. Every box below is closed before the registration is submitted. Written
2026-10-04.

## 0. Hold the line until submission

Part 12 originally said "before you look at outcome data". That point has
passed: stages 2–6 of `run_all.sh` print aggregate label counts for both
outcomes, primary and every sensitivity variant. The binding deadline is now
the one in `docs/decisions.md`: before any model is fit. Until the
registration is submitted:

- [ ] No model is fit (stages 7–9 stay unimplemented on `main`).
- [ ] No feature–outcome association is computed: no univariate AUROC, no
      event-rate-by-feature-bin table, no plot of a feature split by label.
- [ ] No comparator is scored against the label: not the Hu 2026 pressure
      rule, not nurse-charted `Clots Increasing`.

## 1. Disclosure of prior knowledge of the data

The registration states what was seen before it was written. Disclosing only
`docs/feasibility.md` is no longer enough.

- [ ] **Seen** — list each:
  - feasibility counts and event rates (`docs/feasibility.md`)
  - the STROBE flow (`docs/strobe.md`)
  - label counts and distributions for circuit failure and hypophosphatemia,
    primary and every sensitivity variant (stages 4 and 6)
  - feature coverage (stage 5)
  - itemid value distributions (`docs/itemids.md`)
- [ ] **Not seen** — state explicitly: any feature–outcome association, and
      any model or comparator performance.

## 2. Gates from the decision log

- [x] Yang 2024 (PMID 38704337) read in full; their clotting and circuit
      definitions confirmed and logged in `docs/decisions.md`
      (2026-10-02, "Before locking"). Done 2026-10-05: see "Yang 2024 read
      in full: the framing stands".

## 3. Lock every open value in `config/config.yaml`

Each one gets a dated entry in `docs/decisions.md` (Part 14). Done
2026-10-07: see "Validation and leakage values locked".

- [x] `validation.outer_folds` (5)
- [x] `validation.inner_folds` (3)
- [x] `validation.bootstrap_iterations` (2,000; CIs only, no optimism
      correction — for the authors to confirm)
- [x] `validation.temporal_split_anchor_year_group` (`2020 - 2022`)
- [x] `evaluation.shuffled_label_control.auroc_tolerance` (0.02, two-sided).
      This is the leakage tripwire; it is fixed before any result exists to
      tune it against.
- [x] `blanking_minutes` — 30 with 60 as sensitivity, locked and the
      UNLOCKED marker removed.
- [x] `grep -n "UNLOCKED\|: null" config/config.yaml` returns nothing that
      shapes the cohort, a label, a feature window or an evaluation cut-point
      (only the header's explanation of the marker).

## 4. Pre-specify contribution 3: "does ML add anything"

This is the claim a reviewer will hold against the registration. Done
2026-10-07: see "Contribution 3 pre-specified" in `docs/decisions.md`.

- [x] One primary performance metric named: event-level sensitivity at
      matched alert volume, for gradient boosting on the primary label and
      horizon, pooled out-of-fold. AUPRC stays the headline discrimination
      metric and does not decide.
- [x] The test that decides "beats the comparator" named: a
      patient-clustered bootstrap CI on the paired difference, with a lower
      bound above 0. The model must beat all three arms (intersection–union,
      no correction).
- [x] Hu 2026 rule: reported both as published (derived BFR/TFR, which
      match Hu's formulas, so no offset) and recalibrated. Recalibration
      picks one Youden-optimal threshold per Δ inside each outer training
      set.
- [x] `Clots Increasing` comparator: alerts from its first entry on the
      circuit until the circuit ends.
- [x] Stated in advance: if the model does not beat both comparators, that is
      reported as the finding.

## 5. Decision rules written as rules

- [ ] Label adjudication: the ~150-circuit sample, who adjudicates, and the
      kill rule — κ < 0.6 drops circuit failure to secondary and promotes
      hypophosphatemia (Part 13, week 9). There is no clinical mentor yet,
      so adjudication follows model development (decision 2026-10-04,
      "Clinical review waits for a clinical mentor"). The registration says
      so, names the role (clinical co-investigator, to be named), and
      states the two safeguards:
  - [ ] the sample is drawn and frozen with the fixed seed before any
        model is fit;
  - [ ] the adjudicator is blinded to model scores and comparator alerts.
- [x] Adjudication sample: stratified, 40 / 25 / 45 / 40 by ending class,
      κ weighted back to the frame (decision 2026-10-04, "Adjudication
      sample"). Drawn and frozen 2026-10-04.
- [ ] Quote the sample's fingerprint
      (`a1d751af9f20e8cf6579c1ea290f062bd56c0b8ad022dcb18663885dffc99d24`) in
      the registration, and check that stage 3b still prints it.
- [x] κ rules (decision 2026-10-04, "Kappa rules for adjudication"). Copy
      them into the registration:
  - the kill rule reads the point estimate of the frame-weighted κ for the
    primary label, from the primary adjudicator; the CI is reported, and
    does not decide;
  - an "unclear" verdict counts as not a clot; the unclear share per
    stratum and κ without them are reported as secondary numbers;
  - κ for the sensitivity label, the PPV of `clotted` and the clot share
    among `undocumented` and `clots_increasing` are reported, and none of
    them can replace the primary label;
  - κ is weighted back to the frame of the four strata, every included
    circuit that does not end in death. Death endings are labelled
    non-events but not adjudicated (decision 2026-10-17, "Death is a
    competing ending").
- [ ] Plausibility bounds: data-derived until clinical review; a bound
      changed after registration is reported as a deviation.
- [ ] Event-count kill rule: the minimum event count below which the paper
      becomes descriptive epidemiology (Part 13, week 14). Give the number.
- [ ] Unclear terminations: primary and sensitivity handling
      (`unclear_handling_sensitivity`).

## 6. Confirmatory vs exploratory

Done 2026-10-17: see "Confirmatory, secondary and exploratory analyses" in
`docs/decisions.md`. Copy its three lists into the registration.

- [x] **Confirmatory:** the comparison against both comparators on circuit
      failure at the primary horizon (contribution 3); the frame-weighted κ
      and its kill rule; incident hypophosphatemia below 2.0 mg/dL, as an
      estimate. Not *severe* hypophosphatemia, which is descriptive only.
- [x] **Exploratory:** contribution 4 (AUROC inflation from circuit-level
      splits and from pressure in the label), SHAP, subgroups, group
      ablation. The ablation stays exploratory, with its feature split fixed.
- [x] Hypophosphatemia registered in full regardless of packaging, so that
      splitting it into its own short paper at drafting does not break the
      registration.
- [ ] Decide whether hypophosphatemia gets a simple comparator (ranking by
      the last known phosphate). Optional; if yes, before registration.

## 7. Every sensitivity analysis listed by name

One line each in the registration, so none reads as post hoc. Current
`*_sensitivity` keys in `config/config.yaml`:

- [ ] `esrd_handling_sensitivity`
- [ ] `same_admission_icd_sensitivity`
- [ ] `gap_hours_sensitivity`
- [ ] `max_downtime_hours_sensitivity`
- [ ] `horizon_hours_sensitivity`
- [ ] `blanking_minutes_sensitivity`
- [ ] `event_classes_sensitivity`
- [ ] `unclear_handling_sensitivity`
- [ ] `repletion_handling_sensitivity`
- [ ] `death_handling_sensitivity` (decision 2026-10-17): death censored
      instead of competing, both outcomes.
- [ ] `inputevents` anticoagulation (decision 2026-10-04): circuit
      failure, eras 2008–10 to 2017–19 only, compared with the primary
      feature set on the same eras and folds. It also carries the
      norepinephrine-equivalent dose (decision 2026-10-04, "Hemodynamic
      features"). Its config key lands with stage 8, so it is not in the
      grep below — list it by hand.
- [ ] Re-run the grep before submitting in case keys were added.

## 8. Documents to attach

- [ ] `docs/crrt_protocol.pdf` rebuilt as **v1.0** from the decision log.
      v0.1 is stale: it still defines sessions by a >2 h gap (superseded by
      filter identity, 2026-10-02) and predates the phosphate repletion
      handling (2026-10-03).
- [ ] TRIPOD+AI checklist filled in as a design specification (Part 12).
- [ ] PROBAST+AI self-assessment (Part 12).
- [ ] `config/config.yaml` and an export of `docs/decisions.md`.
- [ ] A git tag (e.g. `prereg-v1`) on `main`; its commit hash quoted in the
      registration. Optionally a Zenodo DOI for that tag.
- [ ] Files uploaded directly to OSF storage, not only linked through the
      GitHub add-on, so the registered snapshot is unambiguous.

## 9. Data and anonymity rules

- [ ] Only aggregate counts appear, every cell under
      `reporting.small_cell_threshold` suppressed. No row-level values, no
      identifiers, no timestamps (Part 1.4, DUA).
- [ ] Authors are the two investigators only. No tool attribution in the
      registration text, the attached files, or their metadata (check the
      PDF's Author/Creator fields).

## 10. Submission choices

- [ ] Template: OSF **Preregistration for Secondary Data Analysis**
      (van den Akker et al.) — it has the prior-knowledge questions section 1
      answers.
- [ ] Embargo or public now decided and logged. An embargo (up to 4 years)
      keeps the circuit definition private until submission; public now
      strengthens the priority claim. The timestamp counts either way.

## 11. The survival framing

Added 2026-10-13: see "Survival framing adopted, independent censoring
declined" in `docs/decisions.md`.

- [ ] The faculty mentor has answered on competing endings in place of
      independent censoring, and the answer is logged.
- [x] Death decided and logged: censored (as now) or a competing ending,
      with the other choice as a sensitivity analysis listed in §7. Done
      2026-10-17: a competing ending, censored as the sensitivity
      analysis (see "Death is a competing ending").
- [ ] The registration states the estimand: the H-hour cumulative incidence
      of documented clotting, with other endings competing.
- [ ] The registration specifies rung 2 as the landmark, competing-risks
      discrete-time model.

## After submission

- Any change goes in as an OSF update with a dated rationale, mirrored in
  `docs/decisions.md`.
- The manuscript reports every deviation from the registration.
