#!/usr/bin/env bash
#
# Reproduce every number in the paper from the raw MIMIC-IV CSVs.
#
# Plan Part 2.4 requires this file to be the whole pipeline: a reader who has
# credentialed, downloaded the data, and run `uv sync` should be able to run
# this one script and land on the manuscript's figures and tables. Keep it
# that way — a step that only ever ran in a notebook does not count.
#
# Usage: ./run_all.sh
#
# Implemented so far: database build, the itemid evidence sweep, circuits, the
# cohort with its STROBE flow, the adjudication sample, the outcome labels, the machine,
# anticoagulation, coagulation/hematology and chemistry features, and the
# sensitivity analyses.

set -euo pipefail

CONFIG="config/config.yaml"

echo "config: ${CONFIG}"

# 0. Load the CSVs into DuckDB; convert chartevents to Parquet (Part 2.1).
uv run python -m crrt.build_db

# 1a. Itemid evidence sweep -> docs/itemids.md (Part 2.3). Inclusion is then
#     decided BY HAND in that file; this only gathers the evidence.
uv run python -m crrt.itemid_inventory

# 2. Circuits (Parts 4.3, 4.4, 5.1): one row per filter, with how it ended
#    -> table crrt_circuits. Prints aggregate counts only.
uv run python -m crrt.circuits

# 3. Cohort (Parts 4.1, 4.2, 4.6): every circuit with its exclusion flags and
#    the chronic dialysis flag -> table crrt_cohort; STROBE flow -> docs/strobe.md.
uv run python -m crrt.cohort

# 3b. Label adjudication sample (Part 5.1 step 4): stratified by how each
#     circuit ended, drawn with the fixed seed -> table adjudication_sample.
#     Frozen before any model is fit; prints aggregate counts and the
#     sample's fingerprint, which must match docs/decisions.md.
uv run python -m crrt.adjudication

# 4. Outcome labels (Parts 5, 6.1-6.3): one row per circuit per prediction
#    time with its label -> tables circuit_failure_labels and hypophos_labels.
#    Prints aggregate counts only.
uv run python -m crrt.outcomes

# 5. Features (Part 7): one row per prediction row, from data stored by the
#    prediction time -> tables machine_features, anticoag_features and
#    lab_features (coagulation/hematology and chemistry). The other clinical
#    groups to follow.
#    Prints aggregate coverage only.
uv run python -m crrt.features

# 6. Sensitivity analyses: every `*_sensitivity` value in the config, each in
#    its own schema (e.g. horizon_12h.circuit_failure_labels). Label analyses
#    rebuild one label table and share the primary features; circuit
#    analyses (max downtime, segment gap) rebuild stages 2-5. Prints
#    aggregate counts and a comparison with the primary only.
uv run python -m crrt.sensitivity

# Stages below are not implemented yet. Uncomment as each lands.
#
# 7. Leakage checks    (Part 6.4-6.5)  checklist + shuffled-label control,
#                                      for the primary and every analysis
# 8. Models            (Part 8)        baseline -> LR -> GBM -> temporal
# 9. Evaluation        (Part 9, 10)    nested CV, calibration, subgroups
# 10. Figures + tables (Part 16)
