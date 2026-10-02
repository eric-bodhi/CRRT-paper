# Decision log

Every judgment call, with its date (plan Part 14). Newest first.

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
