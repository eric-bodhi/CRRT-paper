#!/usr/bin/env bash
#
# Set up the label adjudication app on the adjudicator's own Mac or Linux
# machine (Part 5.1 step 4). Read docs/adjudication_guide.md first.
#
# Needs: the adjudicator's own PhysioNet credential, with the MIMIC-IV 3.1
# data use agreement signed, uv, and the pages package that
# `crrt.adjudication_viewer export` writes on a team member's machine,
# copied into this folder (docs/decisions.md 2026-10-04, "Hand the pages to
# a credentialed adjudicator").
#
# The steps are in crrt.adjudication_setup, so Windows runs the same ones
# from adjudicate.bat: unpack the pages, keeping any verdict sheet already
# here, then put an Adjudicate launcher on the desktop. With no package, it
# offers to download MIMIC-IV with the adjudicator's own login and build
# the pages here instead.
#
# Usage: ./adjudicate.sh
# Then double-click Adjudicate on the desktop.

set -euo pipefail

cd "$(dirname "$0")"
uv run python -m crrt.adjudication_setup
