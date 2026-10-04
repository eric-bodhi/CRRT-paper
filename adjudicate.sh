#!/usr/bin/env bash
#
# Set up the label adjudication app on the adjudicator's own Mac or Linux
# machine (Part 5.1 step 4). Read docs/adjudication_guide.md first.
#
# Needs: the adjudicator's own PhysioNet credential, with the MIMIC-IV 3.1
# data use agreement signed, and uv. Under the DUA nobody can send them the
# data or the pages; they are built here, from their own download.
#
# The steps are in crrt.adjudication_setup, so Windows runs the same ones
# from adjudicate.bat: download MIMIC-IV with the adjudicator's own login
# (only the files the pipeline reads, checksum-verified), build the database
# if there is none, the circuits, cohort, frozen sample and pages, then put
# an Adjudicate launcher on the desktop. Rerunning carries on a stopped
# download and never overwrites the verdict sheets.
#
# Usage: ./adjudicate.sh
# Then double-click Adjudicate on the desktop.

set -euo pipefail

cd "$(dirname "$0")"
uv run python -m crrt.adjudication_setup
