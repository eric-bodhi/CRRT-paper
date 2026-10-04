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

- [ ] Yang 2024 (PMID 38704337) read in full; their clotting and circuit
      definitions confirmed and logged in `docs/decisions.md`
      (2026-10-02, "Before locking").

## 3. Lock every open value in `config/config.yaml`

Each one gets a dated entry in `docs/decisions.md` (Part 14).

- [ ] `validation.outer_folds` (`null`)
- [ ] `validation.inner_folds` (`null`)
- [ ] `validation.bootstrap_iterations` (`null`)
- [ ] `validation.temporal_split_anchor_year_group` (`null`)
- [ ] `evaluation.shuffled_label_control.auroc_tolerance` (`null`, marked
      UNLOCKED). This is the leakage tripwire; it must be fixed before any
      result exists to tune it against.
- [ ] `blanking_minutes` — 30 with 60 as sensitivity, but still commented
      UNLOCKED. Lock it formally and remove the marker.
- [ ] `grep -n "UNLOCKED\|: null" config/config.yaml` returns nothing that
      shapes the cohort, a label, a feature window or an evaluation cut-point.

## 4. Pre-specify contribution 3: "does ML add anything"

This is the claim a reviewer will hold against the registration.

- [ ] One primary performance metric named (e.g. AUPRC, or false alerts per
      shift at the alert budget `evaluation.alert_budget_alerts` per
      `alert_budget_hours`).
- [ ] The test that decides "beats the comparator" named (e.g. a
      patient-clustered bootstrap CI on the paired difference).
- [ ] Hu 2026 rule: reported both as published and recalibrated to hourly
      Prismaflex charting; recalibration procedure specified and fit inside
      training folds only.
- [ ] `Clots Increasing` comparator: how it is turned into a score or alert
      specified.
- [ ] Stated in advance: if the model does not beat both comparators, that is
      reported as the finding.

## 5. Decision rules written as rules

- [ ] Label adjudication: the ~150-circuit sample, who adjudicates, and the
      kill rule — κ < 0.6 drops circuit failure to secondary and promotes
      hypophosphatemia (Part 13, week 9).
- [ ] Event-count kill rule: the minimum event count below which the paper
      becomes descriptive epidemiology (Part 13, week 14). Give the number.
- [ ] Unclear terminations: primary and sensitivity handling
      (`unclear_handling_sensitivity`).

## 6. Confirmatory vs exploratory

- [ ] **Confirmatory:** circuit failure at the primary horizon; incident
      severe hypophosphatemia; the comparison against both comparators.
- [ ] **Exploratory:** contribution 4 (AUROC inflation from circuit-level
      splits and from pressure in the label), SHAP, subgroups, group
      ablation (unless promoted to confirmatory — decide and say which).
- [ ] Hypophosphatemia registered in full regardless of packaging, so that
      splitting it into its own short paper at drafting does not break the
      registration.

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

## After submission

- Any change goes in as an OSF update with a dated rationale, mirrored in
  `docs/decisions.md`.
- The manuscript reports every deviation from the registration.
