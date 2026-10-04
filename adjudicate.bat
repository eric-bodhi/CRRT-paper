@echo off
rem Set up the label adjudication app on the adjudicator's own Windows
rem computer (Part 5.1 step 4): the same steps as adjudicate.sh, in
rem crrt.adjudication_setup. Read docs\adjudication_guide.md first.
rem Double-click this file, then double-click Adjudicate on the desktop.
cd /d "%~dp0"
uv run python -m crrt.adjudication_setup
pause
