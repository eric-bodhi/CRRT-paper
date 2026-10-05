#!/usr/bin/env bash
#
# Set up the label adjudication app on the adjudicator's own Mac or Linux
# machine (Part 5.1 step 4). Read docs/adjudication_guide.md first.
#
# The fallback. Usually the adjudicator needs none of this: a team member
# exports the pages as a package that runs on Python alone
# (docs/decisions.md 2026-10-04, "The package runs on Python alone").
#
# This builds the pages here instead, from the adjudicator's own download.
# Needs: their own PhysioNet credential, with the MIMIC-IV 3.1 data use
# agreement signed, and uv, which Windows 11's Smart App Control blocks.
#
# The steps are in crrt.adjudication_setup, so Windows runs the same ones
# from adjudicate.bat: download MIMIC-IV with the adjudicator's own login,
# build the database and the pages, then put an Adjudicate launcher on the
# desktop.
#
# Usage: ./adjudicate.sh
# Then double-click Adjudicate on the desktop.

set -euo pipefail

cd "$(dirname "$0")"
uv run python -m crrt.adjudication_setup
