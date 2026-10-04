@echo off
rem The fallback: build the adjudication pages on this Windows computer from
rem the adjudicator's own MIMIC-IV download (Part 5.1 step 4), the same steps
rem as adjudicate.sh, in crrt.adjudication_setup. It needs uv, which Windows
rem 11's Smart App Control blocks. Usually use the exported package instead,
rem which runs on Python alone: read docs\adjudication_guide.md first.
cd /d "%~dp0"
uv run python -m crrt.adjudication_setup
pause
