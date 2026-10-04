# Adjudication guide

For the clinician who adjudicates how CRRT circuits ended (plan Part 5.1
step 4), and for the person who sets up their computer (last section). The
category definitions below are a draft. Edit them with the team in the
practice session, before the first counted verdict. After that they are
fixed.

## What you are asked

For each of 150 CRRT circuits in MIMIC-IV, read the chart around the moment
the circuit stopped and decide **why it stopped**. You see the circuit as
charted: System Integrity entries, the filter change reason, CRRT mode,
blood flow, pressures, fluid rates, citrate, heparin and calcium, plus death
or ICU discharge shortly after.

You are not told how the study's algorithm classified any circuit, how the
circuits were chosen, or anything from a model. Please do not look at the
analysis code, `docs/decisions.md` or the config until your verdicts are
sent: they describe how the sample was drawn.

## Categories

Pick exactly one per circuit.

| Button | Use it when |
|---|---|
| **Clotting** | The circuit came down because it clotted, or clotting was making it unusable: changed early for increasing clots, or pressures climbing until it could not run. |
| **Elective scheduled** | A planned change or stop: the filter reached its scheduled life (about 72 h), CRRT was stopped because it was no longer needed or switched to intermittent dialysis, or a routine set change. |
| **Patient related** | It stopped for the patient, not the filter: death, transport off the unit (imaging, OR), a procedure, a dialysis catheter problem or line change, ICU discharge. |
| **Unclear** | The chart does not let you tell. Use it honestly; it is a valid answer. |

Judge from the whole picture, as you would at the bedside. No single entry
decides it.

## How to do it

1. **Open it.** Double-click **Adjudicate** on your desktop. A small window
   with text opens, then your web browser shows the list of circuits. Leave
   that small window open while you work.
2. **Pick up where you left off.** Click **Continue where I left off**.
3. **Read the circuit.** The chart shows the four circuit pressures. The
   table under it, the flowsheet, has every charted value. Scroll down
   through it; the column names stay at the top.
4. **Answer.** At the bottom of the screen, click the button for why the
   circuit stopped. It stays highlighted and **Saved ✓** appears. To change
   your answer, click another button. The note box is optional.
5. **Next.** Click **Next →**. Sessions of 30–50 circuits work well.
6. **Stop whenever you like.** Close the browser and the small window. Every
   answer is already saved. Next time, double-click **Adjudicate** again and
   your answers are still there.
7. **Finish.** When all 150 have an answer, the list page says **All done**
   and names one file. Click **Show me the file**, then email that one file
   to the study team. It holds only the circuit numbers and your answers.

If a page shows a red message, **Answers can't be saved here**, close it and
double-click **Adjudicate** on your desktop. Pages save only when opened that
way.

The **practice** circuits (link at the top of the list) are for the training
session with the team. Practice answers are never counted or sent.

## Reading a page

- **Time** is hours:minutes from the circuit's end (0:00). Negative is
  before it ends; shaded rows are after it ends.
- **The chart** shows the four circuit pressures over the window. Hover
  over a line for the value at that point. Every value is also in the
  flowsheet below.
- **After the end** lists death or ICU discharge in the window.
- A page shows at most the last 72 h of a long circuit, and 6 h after it
  ends.

## Data rules (PhysioNet DUA)

- Do not screenshot, print, copy or share any page or value, with anyone,
  including the team. Do not paste them into AI tools.
- Do not open or edit `verdicts.csv` yourself, in Excel or anything else.
  The buttons write it.
- Your notes stay on this computer, because a note can quote a charted
  value. The file you send holds only the circuit number and your answer.
- Do not discuss individual circuits with the team until your verdicts are
  sent. After that, discuss them only with credentialed team members.
- Do not move the study folder into OneDrive, Dropbox, iCloud or Google
  Drive.

## For the person setting up

Do this once, at the adjudicator's computer, with them there. Windows, Mac
and Linux all work.

**Before the visit.**

- Confirm the adjudicator has their own PhysioNet credential (CITI
  training, then credentialing; outline Parts 1.1–1.3) and has signed the
  MIMIC-IV 3.1 data use agreement: their PhysioNet account shows access to
  the MIMIC-IV files. The pages may go only to someone who has both
  (`docs/decisions.md` 2026-10-04, "Hand the pages to a credentialed
  adjudicator").
- On your own credentialed machine, run
  `uv run python -m crrt.adjudication_viewer export`. It rebuilds the pages,
  checks that the sample is the frozen one, and writes
  `data/adjudication_pages_<sample>.zip`, about 1 MB, with empty verdict
  sheets. Your own clicks and notes are never in it.
- Copy that file to an encrypted USB drive: BitLocker To Go on Windows, or
  a drive erased as encrypted in Disk Utility on a Mac. Never send it by
  email, cloud storage, chat or any other online service.
- About 1 GB free on the adjudicator's disk is enough.

**Steps.**

1. **Install uv.** Windows, in PowerShell:
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
   Mac or Linux, in Terminal: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
   Close and reopen the window afterwards.
2. **Put this repository in the home folder**, for example
   `C:\Users\<name>\crrt` or `~/crrt`, with `git clone` or GitHub's
   Download ZIP. Not on the Desktop, in Documents, or in OneDrive, Dropbox,
   iCloud or Google Drive: those are often synced to a cloud, which the DUA
   forbids. Setup refuses to run in a synced folder.
3. **Copy `adjudication_pages_<sample>.zip`** from the USB drive into that
   folder.
4. **Run setup.** Windows: double-click `adjudicate.bat`. Mac or Linux: run
   `./adjudicate.sh` in Terminal. It unpacks the pages and puts
   **Adjudicate** on the desktop. The first run takes a minute or two while
   it installs Python packages.
5. **Delete the zip** from the folder and from the USB drive.
6. **Check it together.** Double-click **Adjudicate**, open a practice
   circuit, click a button, and see **Saved ✓**. Reload the page: the
   button is still highlighted.

To update the pages later, export again, copy the new zip into the folder
and rerun setup. It replaces the pages and keeps every answer.

**Without a package.** If setup finds no package and no pages, it offers to
build the pages on this computer instead. The adjudicator types their own
PhysioNet username and password, which are used for this download only and
never saved. Only the files the pipeline reads are downloaded, each checked
against PhysioNet's checksums, and a stopped download carries on when setup
is run again. This takes hours and needs at least 35 GB free.

**If something goes wrong.** Setup and the Adjudicate window print what
stopped them. Send that text, and nothing from any page, to the study team.
On Linux, right-click Adjudicate on the desktop and choose Allow Launching
the first time. If Windows says `uv` is not recognized, sign out and back in
so the new PATH applies.
