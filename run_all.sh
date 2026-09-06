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
# STUB — no stage is implemented yet.

set -euo pipefail

CONFIG="config/config.yaml"

echo "run_all.sh is a stub. Config: ${CONFIG}"

# Stages, in the order Parts 4-11 build them. Uncomment as each lands.
#
# 1. Extraction        (Part 2.3, 4)   itemid derivation + validation, cohort
# 2. Sessionization    (Part 4.4)      stitch hourly rows into sessions/circuits
# 3. STROBE counts     (Part 4.6)      exact N at every exclusion step
# 4. Outcome labels    (Part 5)        circuit failure + hypophosphatemia
# 5. Features          (Part 7)        windowed machine/clinical features
# 6. Leakage checks    (Part 6.4-6.5)  checklist + shuffled-label control
# 7. Models            (Part 8)        baseline -> LR -> GBM -> temporal
# 8. Evaluation        (Part 9, 10)    nested CV, calibration, subgroups
# 9. Figures + tables  (Part 16)
