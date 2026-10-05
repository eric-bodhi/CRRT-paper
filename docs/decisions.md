# Decision log

Every judgment call, with its date (plan Part 14). Newest first.

## 2026-10-04 — Access features

**Decision.** `sql/access_features.sql` builds the vascular access feature
group (Part 7, sixth bullet) as `access_features`, in stage 5 of
`run_all.sh`. It has one row per `circuit_failure_labels` row, the same grid
as `machine_features`, and 6 columns: the dialysis catheter's type
(tunneled or temporary), its age in whole days, and for each the hours
since it was last charted.

| Signal | Source | itemid |
|---|---|---|
| `catheter_type` | `chartevents`, Text | 227124 and 229536 Dialysis Catheter Type, the older and newer vocabularies |
| `catheter_age_days` | `datetimeevents`, a date | 225322 Dialysis Catheter Insertion Date |

**Site and side are left out.** Part 7 asks for them "if documentable". The
only source is the `location` field of 224270 Dialysis Catheter in
`procedureevents`: 224135 Dialysis Access Site has no rows, and lock volume
does not separate sites (2026-10-02, "Itemid review"). The site is not
documented at *t*:

- A 224270 row is stored when the catheter comes out. Its `storetime` is
  0.00 / 0.01 / 3.4 h after `endtime` (p5 / p50 / p95, included stays).
  Under the `storetime` rule (Part 6.4), the whole row is hidden until
  removal.
- That `storetime` is the row's last edit, not its first. The catheter was
  on the flowsheet from insertion: 97.6% of 224270 catheters in for at
  least 12 h have line charting during their life, stored before the 224270
  row (225322 insertion date, catheter type, site appearance, dressing). So
  the insertion was known in time. The site was not. It is filled in with
  the removal:

  | How the 224270 row ends | Catheters | `location` filled |
  |---|--:|--:|
  | Removed inside the stay | 1,282 | 92.2% |
  | Still in at ICU discharge (`endtime` within 2 h of `outtime`) | 1,489 | 3.7% |
  | Still in at death (`endtime` within 2 h of `deathtime`) | 322 | 8.7% |

  It is filled for 94.6% of catheters with a 225740 Dialysis Catheter
  Discontinued charted within 6 h of the end, and for 30.2% without one.
  Read at *t*, a known site says how the catheter will leave. Among scored
  rows before 2020 with a 224270 catheter in place, the site is known in
  8.0% of rows of circuits that end in death, in none of those that end at
  ICU discharge (23 circuits), and in 38.6–60.1% of the rest.
- It also drifts with the era. A 224270 catheter is in place at 86.5–91.0%
  of scored rows by era before 2020 and at 44.8% in 2020–22. The site is
  known at 38.4–43.7% and 15.9%.

224270 goes from include to exclude in `config/itemid_review.yaml`. Its
`starttime` is not used either: 225322 gives the catheter's age in every
era, and 224270's in-place window would need its `endtime`.

A site source that would hold up is the radiology report of the chest film
after placement (MIMIC-IV-Note), timed at the report. It is not built: it
needs the note module and a text rule run locally (2026-10-02, "Aggregate
results are exempt"). That decision is the authors'.

**The judgment calls.**

- **Type is tunneled or temporary** (`features.access_catheter_types`). The
  two vocabularies name three values each. Their third lumen ("Temporary
  with non-dialysis port (VIP)", "Temporary 3-Lumen") is an infusion port
  that carries no blood for the circuit, so it is not a class. The
  tunneled share by era is in the coverage table below. Both classes are
  charted during one 224270 catheter's life for 192 of 2,986 catheters
  (6.4%). The latest charting wins, as everywhere else. All 140,338 rows
  carry one of the six listed values. A value not listed would be skipped.
- **Age is in whole days**: the date of `pred_time` minus the insertion
  date. 225322 is a date. 5,160 of 130,723 values carry a time, which is
  ignored. Hours would claim a precision the item does not have. Where
  both document a catheter, the insertion date matches 224270's
  `starttime` to the day for 81.2% of catheters (2,368 of 2,918), and is
  within a day for 85.3%. 213 of 107,464 insertion dates in included stays
  are later than the date they were charted on. They are skipped. There is
  no upper bound: a tunneled catheter can be years old. Among scored rows
  with a tunneled type, age is 1 / 10 / 370 days (p5 / p50 / p95); with a
  temporary type, 1 / 4 / 18.
- **The stay, not a lookback.** Both items describe the catheter, not the
  filter, and are charted about once a shift: the last charting is a median
  3.5 h before *t* (p95 15 h). A value counts from anywhere earlier in the
  same stay, and `_hours_since_last` carries its age, as in the other
  groups. A new catheter's type and date replace the old one's at their
  first charting. No new threshold is needed.

**What this costs.** The group says nothing about site, which Part 7 calls a
known driver of filter life. The paper must state that MIMIC-IV does not
document site in real time, with the table above as the reason.

**Coverage, scored circuit-failure rows.**

| Era | Scored rows | Has type | Tunneled (of typed) | Has age | Median age, days |
|---|--:|--:|--:|--:|--:|
| 2008–2010 | 74,057 | 92.5% | 12.3% | 90.4% | 4 |
| 2011–2013 | 48,964 | 94.5% | 8.3% | 93.4% | 3 |
| 2014–2016 | 55,084 | 95.9% | 16.4% | 90.9% | 4 |
| 2017–2019 | 69,048 | 97.5% | 13.8% | 90.9% | 4 |
| 2020–2022 | 69,875 | 97.8% | 6.8% | 92.6% | 5 |
| All | 317,028 | 95.7% | 11.5% | 91.5% | 4 |

Neither is known at 2.9% of scored rows. Coverage does not drift with the
era. The tunneled share moves between eras without a trend.

**Where it applies.** Plan Parts 6.4 and 7. `sql/access_features.sql`.
`config/config.yaml → features.access_catheter_types`,
`access_insertion_date_itemid`. `config/itemid_review.yaml` (224270).
Columns are defined in `docs/data_dictionary.md`, "`access_features`".

## 2026-10-04 — Laboratory features

**Decision.** `sql/lab_features.sql` builds the coagulation/hematology and
chemistry feature groups (Part 7, fourth and seventh bullets) as one table,
`lab_features`, in stage 5 of `run_all.sh`. It has one row per
`circuit_failure_labels` row, the same grid as `machine_features`, and 58
columns. For each of 14 labs: the last value, the hours since its draw, the
change from the previous result, and the hours between the two draws.

| Group | Labs (`hosp.labevents` itemid) |
|---|---|
| `coagulation_hematology` | platelets 51265, INR 51237, PTT 51275, fibrinogen 51214, hemoglobin 51222, hematocrit 51221 |
| `chemistry` | phosphate 50970, potassium 50971, magnesium 50960, bicarbonate 50882, BUN 51006, creatinine 50912, glucose 50931, triglycerides 51000 |

The groups are the keys of `features.lab_groups`, so an ablation by group
(Part 7) reads them from the config.

The calcium labs of `anticoag_features` (ionized, total and their ratio)
now follow the same rules: the 24 h lookback and the change from the
previous result. That table goes from 49 to 55 columns, and the calcium
labs stay in the anticoagulation group. Both changes were confirmed by the
authors 2026-10-04.

**Itemids.** The itemid review (2026-10-02) takes labs from the mimic-code
coagulation, complete_blood_count and chemistry concepts. Fetched
2026-10-04, they supply 11 of the 14. Magnesium, phosphate and
triglycerides are in no concept. Phosphate is the hypophosphatemia
outcome's item: the config aliases one to the other. Every candidate in
`d_labitems` matching these analytes was checked by label, unit, and rows
and circuits inside included circuits. The items kept, and the
alternatives named here, were also checked by era. Each item kept has a
single unit. The blood-gas items are left out: 50822 potassium, 50809
glucose, 50804 total CO2, 50811 hemoglobin, 50810 hematocrit. They are
whole-blood results that mimic-code keeps in a separate concept (`bg`).
Mixing them with the serum results would need a harmonisation rule.

**The judgment calls.**

- **One lookback for every lab: 24 h** (`features.lab_lookback_hours`).
  Platelets, INR and PTT are often drawn once a day: their p90 gap between
  draws inside a circuit is 23–24 h. Share of scored circuit-failure rows
  with a result:

  | Lab | 12 h | 24 h | 48 h |
  |---|--:|--:|--:|
  | platelets | 77.1% | 98.2% | 99.6% |
  | INR | 61.4% | 89.3% | 96.5% |
  | PTT | 66.3% | 89.8% | 96.5% |
  | fibrinogen | 19.0% | 28.9% | 39.7% |
  | hemoglobin, hematocrit | 77–80% | 98–99% | 99.6% |
  | chemistry, except triglycerides | 91–94% | 98.9–99.4% | 99.6% |
  | triglycerides | 4.1% | 11.0% | 19.9% |

  24 h is the same as `hypophosphatemia.known_value_max_age_hours`.
  `_hours_since_last` carries the age of the value, so an old result is not
  read as a fresh one. The calcium labs looked back 12 h, the longest
  feature window (2026-10-04, "Anticoagulation features"). They move to
  24 h so that every lab follows one rule. Ionized calcium goes from 99.4%
  to 99.6% of scored rows, total calcium from 90.8% to 99.2%, and the ratio
  from 87.2% to 97.4%.
- **The last value and the change from the previous result, without window
  statistics.** The median gap between draws inside a circuit is 6.0–7.8 h
  (triglycerides 23.7 h), so a feature window rarely holds the
  `min_points_for_trend` a slope needs. The level alone hides the
  direction: a platelet count of 90 that was 200 the day before (consumption
  in the filter, heparin-induced thrombocytopenia) reads like a stable 90.
  So does a phosphate falling towards the hypophosphatemia threshold.
  `<lab>_delta` is the last value minus the one drawn before it, both among
  the results that count at *t*. `<lab>_delta_hours` is the time between
  the two draws, so the model can weigh a change by how fast it happened.
  The rule is the same for every lab, so no lab is singled out after the
  fact. A result that has been drawn but not yet stored is skipped, not
  waited for.
- **D-dimer is left out.** Part 7 says "where available". 51196 is drawn in
  2.7 / 1.1 / 1.4 / 1.5 / 11.5% of circuits by era (2008–10 … 2020–22).
  50915, a second D-dimer item, is drawn in under 1.5% and never in
  2020–22. In 2008–10 it is reported in two units, ng/mL and ng/mL FEU,
  about twofold apart. A model trained before 2020 would see it in 1–3% of
  circuits and the test era in 11.5%, so its presence would encode the era.
  Charted TMP was left out of the machine group for the same reason.
- **Triglycerides are kept, with era drift.** Part 7 names them for
  lipid-related circuit clotting (propofol). They are present in 7.3 / 6.2 /
  7.6 / 12.3 / 19.6% of scored rows by era, nearly three times as often in
  the test era as in 2008–16. They are also stored a median 258 min after
  the draw (p95 665). Temporal validation (Part 9.2) must report this.
  When the missingness group (Part 7) is built, "measured" encodes
  clinician suspicion more strongly here than for any other lab. Fibrinogen
  drifts less: 22.5% of scored rows in 2008–10, 35.5% in 2017–19, 31.0% in
  2020–22.
- **Bounds come from the data.** They are taken over every result the
  features can read, `circuit_start` − 24 h to `circuit_end`, because
  pre-CRRT labs are where BUN, creatinine and potassium are most extreme.
  They go to the mentor's clinical plausibility review. Unlike
  nursing-charted machine values, these are analyser results. So a value is
  cut only if it is impossible (creatinine 0; mimic-code drops it too) or
  sits alone past an empty stretch of the tail. Every other bound is the
  edge of the data and cuts nothing.

  | itemid | Lab | Bound | Rows | Below (circuits) | Above (circuits) |
  |---|---|---|--:|--:|--:|
  | 51265 | platelets, K/uL | 5 to 1300 | 45,552 | 0 | 0 |
  | 51237 | INR | 0.7 to 27.5 | 34,832 | 0 | 0 |
  | 51275 | PTT, sec | 18 to 150 | 39,761 | 0 | 0 |
  | 51214 | fibrinogen, mg/dL | 25 to 1800 | 12,098 | 0 | 0 |
  | 51222 | hemoglobin, g/dL | 2.5 to 25 | 45,091 | 0 | 0 |
  | 51221 | hematocrit, % | 7 to 72 | 48,212 | 0 | 0 |
  | 50970 | phosphate, mg/dL | 0.5 to 24 | 54,755 | 0 | <10 (<10) |
  | 50971 | potassium, mEq/L | 1.25 to 10 | 63,432 | 0 | 0 |
  | 50960 | magnesium, mg/dL | 0.6 to 8.5 | 55,874 | 0 | <10 (<10) |
  | 50882 | bicarbonate, mEq/L | 2 to 45 | 62,077 | 0 | 0 |
  | 51006 | BUN, mg/dL | 1 to 260 | 55,364 | 0 | <10 (<10) |
  | 50912 | creatinine, mg/dL | 0.1 to 22 | 55,374 | <10 (<10) | <10 (<10) |
  | 50931 | glucose, mg/dL | 10 to 1300 | 60,743 | <10 (<10) | <10 (<10) |
  | 51000 | triglycerides, mg/dL | 15 to 4000 | 2,788 | 0 | 0 |

  The empty stretches are: phosphate 24–27, magnesium 8.5–11, BUN 260–300,
  creatinine 22–32, glucose 6–10 and 1300–1600. No numeric platelet count
  anywhere in MIMIC-IV is below 5. 1,499 platelet results without a number
  carry "<" or "less than", so lower counts are reported as text and are
  missing. 886 PTT results are 150, the analyser's ceiling (">150"). They
  are kept as 150.

  The calcium bounds (2026-10-04, "Anticoagulation features") were set on
  rows inside circuits and are not re-derived here. Over the 24 h lookback
  they cut more: ionized calcium 92 of 78,044 results below 0.6 and 16
  above 2.0 (inside circuits, 74 and under 10); total calcium 11 of 54,607
  below 4 and 21 above 15 (under 10 and 11). The extra results are mostly
  from before CRRT and may be real hypercalcaemia, itself a reason to start
  dialysis. They go to the clinical plausibility review.
- **Duplicates and timing follow the calcium labs.** Results of one item at
  one `charttime` are averaged and are available at the latest `storetime`.
  Inside included circuits, under 30 per item have two different values.
  Every result has a `storetime`, and none is before its draw. The median
  delay is 64–66 min for chemistry, 34–35 min for blood counts and
  54–57 min for INR, PTT and fibrinogen.

**What this costs.** Both draws of a change must fall inside the lookback.
A lab drawn once a day therefore often has a last value and no change: INR
in 43.7% of scored rows has one, fibrinogen in 13.2%, triglycerides in 0.7%
(table below). A longer reach for the previous result would fill these
in, but at the price of a second lookback rule.

**Coverage, scored circuit-failure rows (317,028).**

| Lab | Has last | Median last | Median hours since | Has change |
|---|--:|--:|--:|--:|
| `platelets` | 98.2% | 113 K/uL | 6.1 | 65.5% |
| `inr` | 89.3% | 1.4 | 7.8 | 43.7% |
| `ptt` | 89.8% | 42.1 sec | 6.6 | 51.9% |
| `fibrinogen` | 28.9% | 262 mg/dL | 8.2 | 13.2% |
| `hemoglobin` | 98.3% | 8.6 g/dL | 6.1 | 65.9% |
| `hematocrit` | 98.5% | 26.7% | 5.8 | 69.7% |
| `phosphate` | 99.3% | 3.0 mg/dL | 5.3 | 91.3% |
| `potassium` | 99.2% | 4.2 mEq/L | 4.7 | 93.3% |
| `magnesium` | 99.4% | 2.0 mg/dL | 5.2 | 92.4% |
| `bicarbonate` | 99.4% | 22 mEq/L | 4.8 | 94.0% |
| `bun` | 99.3% | 25 mg/dL | 5.3 | 92.1% |
| `creatinine` | 99.4% | 1.6 mg/dL | 5.3 | 92.1% |
| `glucose` | 98.9% | 144 mg/dL | 4.8 | 90.8% |
| `triglycerides` | 11.0% | 270 mg/dL | 14.6 | 0.7% |
| `ionized_calcium` | 99.6% | 1.11 mmol/L | 3.0 | 98.1% |
| `total_calcium` | 99.2% | 8.9 mg/dL | 5.3 | 90.7% |
| `calcium_ratio` | 97.4% | 2.01 | 5.5 | 83.0% |

**Where it applies.** Plan Parts 6.4, 7 and 9.2. `sql/lab_features.sql`,
`sql/anticoag_features.sql`. `config/config.yaml → features.lab_groups`,
`lab_lookback_hours`, `calcium_labs`, `plausibility_bounds` (the 14 items).
Columns are defined in `docs/data_dictionary.md`, "`lab_features`" and
"`anticoag_features`".

## 2026-10-04 — The package runs on Python alone

**Decision.** The exported package now runs by itself: no uv, no
repository, no installed packages. On Windows it carries its own Python, so
nothing is installed at all.
`crrt.adjudication_viewer build` writes these into the pages folder, and
`export` zips them:

- `adjudication_app.py`: the server and verdict sheets, moved out of the
  viewer into `crrt.adjudication_app`, which imports only the standard
  library;
- `manifest.json`: the settings it needs from config/config.yaml (sample
  fingerprint, sample size, practice size, verdicts, port);
- a double-click launcher for each platform: `Adjudicate.bat`,
  `Adjudicate.command` and `Adjudicate.sh`;
- the guide;
- under `python/`, only in the export: python.org's embeddable Python for
  Windows (`adjudication_windows_python`, 3.14.8). The first export
  downloads it, and every export checks it against the pinned SHA-256,
  which is python.org's published one. `Adjudicate.bat` runs it.

On a Windows computer: unzip the package into the home folder and
double-click Adjudicate. A Mac needs Python 3 from python.org first. The
app refuses to run from a cloud-synced folder.

The package carries no verdict sheet. The app creates the sheets empty the
first time it starts. A newer package unzipped over the folder therefore
cannot overwrite the answers, and the person updating it has nothing to
remember. `crrt.adjudication_setup`, which needs uv,
stays only as the build-it-here fallback; its unpack step is gone.

**Why.**

- On a personal Windows 11 computer, setup failed with an Application
  Control block. That is Smart App Control: it blocks programs that are not
  code-signed and have no Microsoft reputation, and it has no per-app
  exception. uv.exe and the Python uv downloads (python-build-standalone)
  are both unsigned. Python from python.org is signed and allowed. In its
  embeddable build, 31 of the 33 .exe, .dll and .pyd files are signed by
  the Python Software Foundation and 2 (the C runtime) by Microsoft
  (checked 2026-10-04 by reading each file's signature block). Compiled
  packages from PyPI (duckdb, numpy) are unsigned, so the app uses none.
- Python goes inside the package rather than being downloaded when the app
  first runs. The adjudicator then needs no installer, no internet and no
  admin rights. A launcher that downloads and runs a program can also look
  like malware to antivirus. The cost is about 13 MB.
- Turning Smart App Control off would also work. That is the adjudicator's
  decision about their own computer, and the app should not need it.
- Tests run the unpacked package with `python -I -S`, so only the standard
  library can be imported. They also run it on Python 3.9, a Mac's built-in
  python3; that caught a 3.10-only call that would have stopped every save.
  It also passes on 3.14, the packed Windows version.

**For the authors.** Not yet run on the Windows computer that failed. The
first run there is the test. A signature block's presence was checked here,
not its cryptographic validity; Windows checks that when the file runs.

**Where it applies.** `src/crrt/adjudication_app.py`,
`crrt.adjudication_viewer build`/`export`, `crrt.adjudication_setup`,
`docs/adjudication_guide.md`.

## 2026-10-04 — Hand the pages to a credentialed adjudicator

*The setup step described here was replaced the same day by "The package
runs on Python alone", above: the package now runs by itself.*

**Decision.** The authors' position is that handing MIMIC-IV-derived files
to someone who holds their own PhysioNet credential, and has signed the
MIMIC-IV DUA, does not breach the DUA. It is applied to one thing, the
adjudication pages:

- A team member runs `uv run python -m crrt.adjudication_viewer export`. It
  builds the pages, running the frozen-sample check, and packs them with
  empty verdict sheets into `adjudication_pages_<sample>.zip`. That file
  is 1.2 MB, against about 8 GB of download.
- The adjudicator's setup unpacks it. They download nothing and build no
  database.

This supersedes "each adjudicator downloads their own copy" in "Adjudication
viewer", below.

Conditions:

- Before handing it over, confirm the adjudicator's own credential and
  signed MIMIC-IV 3.1 DUA: their PhysioNet account shows access to the
  files.
- Hand it over in person, on an encrypted USB drive. Never by email, cloud
  storage, chat or any other online service: PhysioNet's 24 Sept 2025 post
  rules those out separately.
- The package holds only the blinded pages and empty sheets, never another
  machine's verdicts or notes. Tests check this.
- On the adjudicator's machine the pages fall under the same data rules
  as their own download would (`docs/adjudication_guide.md`).

**Why.**

- The DUA says the licensee "will not share access to PhysioNet restricted
  data with anyone else." The authors read someone who already holds that
  access, under the same DUA, as not someone access is shared with. The
  package gives them nothing they could not download themselves.
- On a Mac test the same day, downloading MIMIC-IV and building the
  database for 150 circuits was too slow for a clinician's laptop. Setup
  from the package takes about a minute.
- Download-and-build stays in setup as the fallback when there is no
  package.

**For the authors.**

- PhysioNet has not confirmed this reading. Consider asking them, for the
  record.
- CLAUDE.md's no-sharing rule now names this one exception. Wider sharing,
  of raw data or any other extract, would be a separate decision.

**Where it applies.** Plan Parts 1.4, 2.4 and 5.1. `crrt.adjudication_viewer
export`, `crrt.adjudication_setup`, `adjudicate.sh`, `adjudicate.bat`,
`.gitignore`, `docs/adjudication_guide.md`, CLAUDE.md.

## 2026-10-04 — Adjudication viewer

*Partly superseded the same day by "Hand the pages to a credentialed
adjudicator", above: a team member now builds the pages and hands them over.
Download-and-build stays as setup's fallback.*

**Decision.** The adjudicator reads each sampled circuit in pages built
**on their own machine, from their own credentialed MIMIC-IV copy**, and
records each verdict by clicking a button on the page
(`crrt.adjudication_viewer`). One command sets the machine up
(`crrt.adjudication_setup`, run by `adjudicate.bat` on Windows and
`adjudicate.sh` on Mac and Linux). After that the adjudicator only
double-clicks **Adjudicate** on the desktop. Pages and verdict sheets go to
`paths.adjudication_dir`, inside the gitignored data/. The guide is
`docs/adjudication_guide.md`.

- **What a page shows.** The circuit as charted, back to its start or at
  most `adjudication_view_hours.before_end` (72 h), and `after_end` (6 h)
  past its end. That covers System Integrity, the filter change reason,
  CRRT mode, the machine signals, citrate and heparin (`chartevents`),
  calcium (`labevents`), and death or ICU discharge inside the window. A
  chart plots the four circuit pressures; every value is also in the
  flowsheet table. The flowsheet fits the window width, with no sideways
  scrolling at 1280 px, and its column names stay in view while scrolling
  down.
- **Blinding.** Times are relative to the circuit end. No page shows the
  stratum, `termination_class`, an identifier, an absolute timestamp or
  model output. The circuits the pipeline cut after this one are not
  shown either, because where the pipeline starts the next circuit
  partly encodes the label rule. The adjudicator still sees raw `Clotted`
  entries: adjudication reads the same charting as the rule (feasibility
  §6, item 4). Tests check all of this.
- **The frozen sample is enforced.** The viewer refuses to build unless
  the sample's fingerprint equals `adjudication_sample_sha256`.
- **Practice.** `adjudication_practice_per_stratum` (1) circuit per
  stratum, drawn by the same generator after the sample, from what it
  left. A test shows that drawing them does not move the sample. The full
  run printed the same fingerprint as before. Practice fingerprint:
  `d9e1a9e4d00fb21c70aa1ed4d8711817b63992febe345533410ea97501a145ec`.
- **Recording verdicts.** `adjudication_viewer serve`, which the launcher
  runs, serves the pages from 127.0.0.1 on `adjudication_port` and opens
  the browser. Each click rewrites `verdicts.csv` at once
  (`practice_verdicts.csv` for practice), so a page shows its saved verdict
  when revisited and nothing is lost when the browser closes. The list
  page shows progress and where to continue.
- **Setup.** `crrt.adjudication_setup` works the same way on all three
  platforms:
  - It refuses to run inside a cloud-synced folder (OneDrive, Dropbox,
    iCloud, Google Drive).
  - It downloads, with the adjudicator's own PhysioNet login, only the
    files `crrt.build_db` reads. The password is never stored. A stopped
    download resumes, and each file is checked against PhysioNet's
    `SHA256SUMS.txt`.
  - It runs the stages the sample needs, as `adjudicate.sh` did, then puts
    the launcher on the desktop.
- **What comes back.** Once every sampled circuit has a verdict, the app
  writes a file with `review_order` and `verdict` only, the same file
  `adjudication_viewer check` writes. Notes stay on the adjudicator's
  machine.

**Why.**

- Under the DUA no row may be sent to the adjudicator. Building the pages
  where they are read is the only way that needs no exception. Viewing
  pages on a credentialed team member's machine was considered and
  rejected the same day. It rests on the team's reading of the DUA, which
  PhysioNet has not confirmed, so each adjudicator downloads their own
  copy.
- The adjudicator is a clinician, not a programmer. After setup, every
  step is a click.
- Why verdicts need a local server:
  - A page opened from disk cannot write a file.
  - Browser storage was rejected: clearing the browser history would erase
    the verdicts, and getting them out would need an export step.
  - The server uses only the Python standard library: no new dependency,
    and it works offline.
  - It listens on 127.0.0.1 only, so nothing outside the machine can reach
    it.
  - It refuses requests naming any other host, which stops another web page
    from reading pages through DNS rebinding.
  - It refuses POSTs from any other origin, or not sent as JSON, which stops
    another web page from changing verdicts.
- The download identifies itself as `Wget/1.21.4 (crrt-adjudication-setup)`.
  On 2026-10-04 PhysioNet answered wget's agent with a Basic login
  challenge (401) and refused Python's and curl's default agents outright
  (403), with or without a login. wget is PhysioNet's documented download
  tool. The adjudicator's own credential is still required. Chosen by the
  authors over a browser download or installing wget.
- Only `review_order, verdict` leaves the adjudicator's machine. It holds
  no MIMIC value, identifier or time. It maps back to circuits only
  through the seeded draw on another credentialed copy.

**For the authors.**

- Agree that `review_order, verdict` is outside the no-sharing rule under
  your reading of the DUA (Part 2.4).
- Consider telling PhysioNet that the setup download names itself as
  wget-compatible, or asking whether they prefer another way.
- No real page has been viewed by any hosted AI tool. Layout was checked
  on synthetic pages only (2026-10-02, aggregate results).
- Setup has not been run on Windows or a Mac. The first run is the setup
  visit; allow time for it.

**Where it applies.** Plan Parts 2.4 and 5.1. `config/config.yaml →
paths.adjudication_dir`, `paths.mimic_url`,
`outcomes.circuit_failure.adjudication_*`. `adjudicate.sh`,
`adjudicate.bat`, `src/crrt/adjudication_setup.py`,
`docs/adjudication_guide.md`.

## 2026-10-04 — Kappa rules for adjudication

**Decision.** This settles the three questions left open by "Adjudication
sample".

1. **The kill rule reads the point estimate.** Circuit failure drops to
   secondary if the frame-weighted κ of the primary label is below
   `adjudication_min_kappa` (0.6). The 95% CI (stratified bootstrap over
   patients) is reported next to it but does not decide.
2. **An adjudicator's "unclear" counts as not a clot.** κ compares
   "clotting" against everything else. The share of unclear verdicts is
   reported for each stratum, with κ recomputed without them as a
   secondary number.
3. **κ is reported for the sensitivity label too, but only the primary
   label's κ decides.** Also reported, all weighted to the frame: κ for
   `clotted` + `clots_increasing`; the PPV of `clotted`; the share of
   `undocumented` and of `clots_increasing` circuits the adjudicator calls
   clots; and agreement in each stratum. If the sensitivity label agrees
   better, it does not replace the primary label.

The kill rule reads the primary adjudicator's verdicts on all 150
circuits. A second adjudicator's subset gives the agreement between the two
raters and decides nothing.

**Why.**

- **Point estimate.** With 150 circuits the CI is about ±0.12 wide.
  - Killing only when the whole CI is below 0.6 would keep circuit failure
    as primary with a κ near 0.48. A reviewer would not accept that, and it
    is not what protocol v0.1 states ("proceeds only if κ ≥ 0.6").
  - Requiring the whole CI to be above 0.6 needs a κ near 0.72. With the
    expected κ of 0.64, that would kill circuit failure most of the time,
    unless the sample were several times larger than one adjudicator can
    review.
  - The point estimate is how a reader will judge it. It fires on noise
    about 1 time in 5 if the true κ is 0.64. That error is cheap: both
    outcomes are modelled anyway, so a false kill changes the framing and
    no work is lost.
- **Unclear as not a clot.** This matches how the label itself works: an
  event is a documented clot, and an end with no evidence is a non-event
  (`unclear_handling_primary: non_event`, 2026-10-02).
  - Dropping unclear verdicts would drop exactly the hardest circuits and
    inflate κ.
  - On a documented clot, an unclear verdict now counts against the rule,
    which is the conservative direction for the PPV. On an `undocumented`
    end it agrees with the label. The per-stratum unclear share and the κ
    without unclear verdicts show how much this choice moves the result.
- **Primary label decides.** Switching to whichever label adjudicates
  better, after seeing the result, is a forking path. The reasons the
  primary leaves out `clots_increasing` still hold: it is the
  nurse-observation comparator and a candidate feature (2026-10-02).

**When.** The config keys for these rules land with the code that computes
κ, as for the `inputevents` analysis. `adjudication_min_kappa` is already
in the config.

**Where it applies.** Plan Parts 5.1 and 13. `config/config.yaml →
outcomes.circuit_failure.adjudication_min_kappa`. `BEFORE_OSF_CHECKLIST.md`
§5.

## 2026-10-04 — Adjudication sample

**Decision.** The ~150 circuits for label adjudication (Part 5.1 step 4)
are a stratified sample by `termination_class`, not a simple random one.
This settles feasibility §6 item 4.

| Stratum | Classes | Circuits |
|---|---|--:|
| `clotted` | `clotted` (the primary event) | 40 |
| `clots_increasing` | `clots_increasing` | 25 |
| `undocumented` | `undocumented` | 45 |
| `other_non_event` | `reached_limit`, `procedure_or_line_change`, `icu_discharge`, `crrt_ended`, `stopped_then_restarted` | 40 |

- **The frame** is every included cohort circuit with a label. `death` is
  censored (Part 5.3), so it has no label to check and is in no stratum.
  A test fails if a class in `sql/crrt_circuits.sql` is neither in a
  stratum nor censored.
- **Within a stratum**, circuits are drawn at random, so
  `other_non_event` is proportional across its five classes.
- **Kappa is weighted back to the frame.** Each circuit counts as its
  stratum's frame size divided by the circuits drawn. The CI comes from a
  bootstrap within strata that resamples patients (Part 4.3).
- **Drawn once** with `reproducibility.random_seed` and frozen before any
  model is fit (2026-10-04, "Clinical review waits for a clinical
  mentor"). The adjudicator is not told the strata or the allocation.
- A second adjudicator, if there is one, reviews a subset drawn by the
  same strata.

**Drawn 2026-10-04**, before any model was fit, by `crrt.adjudication`
(stage 3b) on MIMIC-IV 3.1. `crrt_circuits` and `crrt_cohort` were
rebuilt first; `docs/strobe.md` did not change.

| Stratum | Frame | Drawn | Patients | Weight |
|---|--:|--:|--:|--:|
| `clotted` | 1,674 | 40 | 38 | 41.85 |
| `clots_increasing` | 543 | 25 | 25 | 21.72 |
| `undocumented` | 1,221 | 45 | 44 | 27.13 |
| `other_non_event` | 4,099 | 40 | 38 | 102.47 |
| total | 7,537 | 150 | 137 | |

Fingerprint (SHA-256 of the sorted `stay_id,circuit_start` lines):
`a1d751af9f20e8cf6579c1ea290f062bd56c0b8ad022dcb18663885dffc99d24`.
Stage 3b prints it on every run. A rerun that prints anything else means
the circuits or the cohort changed: the frozen sample is gone, and the
change is a deviation to log and report.

**Why.** Simulated on the feasibility §2.3 class counts, 4,000 draws each,
under planning assumptions for how often an adjudicator calls a circuit a
clot: `clotted` 0.90, `clots_increasing` 0.60, `undocumented` 0.25 (the
§2.4 mixture estimate), `stopped_then_restarted` 0.15,
`procedure_or_line_change` 0.10, others 0.03–0.05.

| Design | SD of κ | SD of hidden-clot share in `undocumented` | SD of PPV of `clotted` |
|---|--:|--:|--:|
| random 150 | 0.070 | 0.091 | 0.053 |
| 50 / 25 / 50 / 25 | 0.065 | 0.061 | 0.043 |
| **40 / 25 / 45 / 40** | **0.059** | **0.065** | **0.048** |

- A random sample is worse on every quantity. It holds about 30
  `clotted` and 20 `undocumented` circuits.
- Across reasonable allocations the SD of κ is flat (0.055–0.059 on a
  grid), so the allocation was chosen for the per-class estimates. It
  measures the PPV of the label and the share of hidden clots among
  `undocumented` ends, which is the label's main known error (§2.4).

**For the authors, before pre-registration.** Under the same assumptions,
the population κ of the primary label is about **0.64**, close to
`adjudication_min_kappa` (0.6). The primary label leaves out
`clots_increasing` and keeps `undocumented` as non-events (2026-10-02), and
an adjudicator will call many of those circuits clots. On sampling noise
alone, the kill rule fires in about 1 run in 5 under every design. Three
things must be fixed in the registration. They are settled in the entry
above, "Kappa rules for adjudication".

**Where it applies.** Plan Parts 5.1 and 13. `config/config.yaml →
outcomes.circuit_failure.adjudication_strata`, which replaces
`adjudication_sample_size`. `BEFORE_OSF_CHECKLIST.md` §5.

## 2026-10-04 — Clinical review waits for a clinical mentor

**Decision.** The project has a faculty mentor but no nephrology or other
clinical mentor yet. Every task that needs clinical judgment is scheduled as
late as it can go. Until then the pipeline runs on the data-derived choices
already logged.

- **Plausibility bounds** (machine items 2026-10-03, calcium 2026-10-04).
  The data-derived bounds stand. Clinical review happens before the final
  model fit. A bound changed after pre-registration is reported as a
  deviation.
- **Clinical plausibility review of the final feature list** (Part 14).
  Last, before the manuscript.
- **Label adjudication** (Part 5.1 step 4; `adjudication_sample_size`,
  `adjudication_min_kappa`). After model development, before any
  circuit-failure result is written up. The week-9 kill checkpoint
  (Part 13) moves with it.

**What makes late adjudication safe.**

- The sample is drawn and frozen with `reproducibility.random_seed`
  before any model is fit, so model output cannot steer which circuits
  are adjudicated.
- The adjudicator is blinded to model scores and comparator alerts.
- Both outcomes are modelled regardless. A κ below the threshold found
  late changes the framing (circuit failure to secondary), not the work.
- The OSF registration says adjudication follows model development and is
  done by a clinical co-investigator to be named.

**What cannot wait.** The adjudicator needs their own PhysioNet credential
to look at rows (feasibility §6, item 4). CITI training and credentialing
take weeks. Start it as soon as someone is named, or it becomes the
critical path.

The faculty mentor covers the monthly checkpoint (Part 14).

**Where it applies.** Plan Parts 5.1, 13 and 14. `config/config.yaml →
outcomes.circuit_failure` adjudication keys and `plausibility_bounds`.
`BEFORE_OSF_CHECKLIST.md` §5.

## 2026-10-04 — `inputevents` anticoagulation sensitivity analysis

**Decision.** Add it. This closes the question "Anticoagulation features"
left to the authors. One analysis, circuit failure only:

- **Features:** the primary set plus, from `inputevents`, CRRT calcium
  (227525), ACD-A (227529, 227528), heparin infusion (225152), argatroban
  (225147) and bivalirudin (225148), all already included by the itemid
  review. `anticoag_class` is rebuilt from both sources, with a direct
  thrombin inhibitor class added.
- **The `storetime` rule still holds** (Part 6.4). A bag or rate segment
  counts from its `storetime`. The running ACD-A bag is then mostly
  invisible, so this measures what the stored record adds. It does not
  measure what the drug does.
- **Eras 2008–10 to 2017–19 only.** Patient-grouped nested CV within those
  eras, on the same folds as the primary feature set refit on the same
  eras. The difference is then the features alone, not the eras. No
  temporal validation: in 2020–22 a missing row would read as "not given".
- The anticoagulation subgroup (Part 10) is also reported with the
  rebuilt class, next to the primary's contaminated `none`.

**Why.**

- Part 7 lists the calcium replacement rate, and the primary does not
  have it. A reviewer will ask what leaving it out cost. This answers with
  a number instead of an argument.
- Either result is reportable. A small difference means the primary
  choice holds, and the model runs on what is recorded in every era. A
  large one quantifies a limitation of the 2020–22 documentation that the
  temporal split cannot show.
- It tests the two weaknesses the primary can only name: `none` rows with
  a 225152 heparin infusion running (18.6% before 2020) and the 241 direct
  thrombin inhibitor circuits.
- Circuit failure only. Anticoagulation is the clotting mechanism. The
  drivers Part 3.2 names for hypophosphatemia are solution phosphate
  content and dialysis intensity, not anticoagulation.

**When.** With the model stage (8), not on the feature branch. It changes
the feature set and an era filter at fit time and rebuilds no label or
circuit table. Its config key comes with its code, because a
`*_sensitivity` key that nothing builds fails `tests/test_sensitivity.py`.
It is pre-registered now (`BEFORE_OSF_CHECKLIST.md` §7).

**Where it applies.** Plan Parts 6.4, 7 and 10. Decision "Anticoagulation
features" (2026-10-04).

## 2026-10-04 — Sensitivity analyses

**Decision.** `crrt.sensitivity` builds every sensitivity analysis in the
config. It is stage 6 of `run_all.sh`. Before it, the `*_sensitivity` keys
were specified but read by nothing except a test that they exist. The
repletion results of 2026-10-03, which the authors confirmed for the
paper, had been computed outside `run_all.sh`. They are now reproduced
exactly: censor 25,703 / 163,674, ignore 28,345 / 183,119, composite
45,372 / 183,343, with the same stays and by-era prevalence.

**How.** Each analysis is the primary config with one key changed. It is
built into a schema named after it, e.g. `horizon_12h`, in the same
database. While it builds, unqualified names resolve to that schema and then
to `main`. The stage SQL runs unchanged, and `main` is never written. It
takes about 11 minutes and 1.6 GB.

- **Label analyses**, which rebuild one label table: horizon 3 / 12 h,
  blanking 60 min, event `clotted` + `clots_increasing`, undocumented ends
  excluded, phosphate < 1.5, repletion `ignore` / `composite`. They share
  `main`'s circuits, cohort and features. The build fails if a label table's
  grid differs from the primary's, because the features join on it.
- **Circuit analyses**, which rebuild stages 2–5: maximum downtime 4 / 12 h,
  segment gap 1 / 4 h. `circuit_id` is a row number, so it names a different
  circuit in each of these schemas. Their tables must never be joined across
  schemas.
- **Handled elsewhere**: the same-admission ICD chronic dialysis flag is a
  column of `crrt_cohort`. Excluding chronic dialysis is a row filter at
  model fitting.

A test lists every sensitivity key in the config. A key added without
being built, or named as handled elsewhere, fails it.

**Results, scored rows** (printed by stage 6):

| Analysis | Circuit failure positive / labelled | Prevalence | Hypophosphatemia positive / labelled | Prevalence |
|---|--:|--:|--:|--:|
| primary | 8,639 / 307,493 | 2.8% | 25,703 / 163,674 | 15.7% |
| horizon 3 h | 4,188 / 312,845 | 1.3% | | |
| horizon 12 h | 16,435 / 297,506 | 5.5% | | |
| blanking 60 min | 7,596 / 303,356 | 2.5% | | |
| + `clots_increasing` | 11,417 / 307,493 | 3.7% | | |
| undocumented excluded | 8,639 / 272,592 | 3.2% | | |
| phosphate < 1.5 | | | 10,154 / 213,833 | 4.7% |
| repletion ignore | | | 28,345 / 183,119 | 15.5% |
| repletion composite | | | 45,372 / 183,343 | 24.7% |
| max downtime 4 h | 8,660 / 309,567 | 2.8% | 25,547 / 162,089 | 15.8% |
| max downtime 12 h | 8,539 / 304,395 | 2.8% | 25,797 / 164,785 | 15.7% |
| segment gap 1 h | 8,597 / 281,488 | 3.1% | 25,338 / 159,755 | 15.9% |
| segment gap 4 h | 8,130 / 310,757 | 2.6% | 25,759 / 164,415 | 15.7% |

**For the authors.**

- **The `clots_increasing` event conflicts with its other two roles.** In
  that analysis, `Clots Increasing` charted up to
  `windows_hours.clots_increasing_at_end` (3 h) before the end defines the
  event. Blanking is 30 min, so any feature that reads it leaks the label
  there. The analysis must drop such a feature, and the nurse-observation
  comparator (Part 8.1) is undefined in it. No feature reads it yet. This
  is now noted next to `event_classes_sensitivity` in the config.
- **Phosphate < 1.5 mostly measures repletion.** 60,464 rows are censored
  for repletion against 10,154 events. Repletion starts below 2.0, so most
  orders come before any draw under 1.5. Prevalence in 2020–22 is 2.7%,
  against 4.6–5.8% before. **Decide** whether this analysis should be
  reported under the `ignore` handling as well.
- **A 1 h segment gap tests charting jitter, not the circuit definition.**
  Machine charting is every 60 min (p90 92 min, feasibility §1), so a 1 h
  gap cuts ordinary intervals. It makes 13,285 circuits (primary 9,729), and
  27,249 rows fall in downtime (primary 4,660). Since 2026-10-02 the gap
  only defines downtime within a circuit, and maximum downtime is the
  circuit-definition analysis. **Decide** whether the gap analyses (Part
  4.4) stay.
- **The shuffled-label control (Part 6.5) runs per analysis.** Each one is
  a different label or row set. Stage 7 must refit the control for every
  schema, not only `main`.

**Where it applies.** Plan Parts 4.4, 5, 6.2, 6.5 and 12.
`src/crrt/sensitivity.py`, `run_all.sh` stage 6, `config/config.yaml`
(every `*_sensitivity` key), `docs/data_dictionary.md`, "Sensitivity
analysis schemas".

## 2026-10-04 — Anticoagulation features

*Partly superseded the same day by "Laboratory features", above: the
calcium labs now look back `features.lab_lookback_hours` (24 h), not the
longest window, and carry the change from the previous result.*

**Decision.** `sql/anticoag_features.sql` builds the anticoagulation feature
group (Part 7, third bullet) as `anticoag_features`, in stage 5 of
`run_all.sh`. It has one row per `circuit_failure_labels` row, the
same grid as `machine_features`, and 49 columns:

- citrate rate (228004) and heparin dose (224145), hourly from
  `chartevents`, with the machine signals' last value and window statistics;
- ionized calcium (50808), total calcium (50893) and the total:ionized
  ratio, last value only;
- `anticoag_class`: citrate / heparin / citrate_heparin / none.

**v1 reads no `inputevents` item.** This departs from feasibility §6
proposal 8 ("chartevents ∪ inputevents") and from Part 7, which lists the
calcium replacement rate. Confirmed by the authors 2026-10-04. The reasons
are two properties of `inputevents`:

- **About half of its rows are lost in 2020–22, the temporal test era.**
  This is the gap that moved the phosphate repletion censor to orders
  (2026-10-03). Circuits with a record, by era (2008–10 … 2020–22):

  | Source | Circuits |
  |---|---|
  | 228004 citrate > 0 (`chartevents`) | 1,217 / 1,071 / 1,036 / 1,404 / 1,462 |
  | 227529/227528 ACD-A (`inputevents`) | 1,251 / 953 / 894 / 1,302 / **696** |
  | 227525 CRRT calcium (`inputevents`) | 1,578 / 1,110 / 1,258 / 1,642 / **829** |

  No new itemid replaces them in 2020–22. A model trained on earlier eras
  would read "not recorded" as "not given" in the test era.
- **A row is stored around the end of its bag or rate segment.** An ACD-A
  row is one bag. It runs a median 298 min and is stored a median 309 min
  after it starts; 13% are stored within an hour of starting. CRRT calcium
  is stored a median 71 min after its start, and 48% within an hour. Under
  the `storetime` rule (Part 6.4), the bag that is running now is
  invisible. The `chartevents` items are stored a median 7–10 min after
  charttime.

**What this costs.**

- **No calcium replacement rate.** Rising calcium requirement is the
  citrate-accumulation signal. Ionized calcium and the total:ionized ratio
  carry part of it.
- **Citrate is unknown, not 0, in 195 circuits of 2008–10.** These circuits
  have ACD-A in `inputevents` but 228004 is never charted. That is why
  `anticoag_class` is null in 18.6% of scored 2008–10 rows, against
  1.2–2.1% in later eras.
- **`none` is contaminated.** Before 2020, where `inputevents` is complete,
  18.6% of scored `none` rows have a 225152 heparin infusion running that
  224145 does not show, and 4.9% argatroban or bivalirudin. Direct thrombin
  inhibitors (241 circuits) are not represented at all. A subgroup analysis
  by anticoagulation (Part 10) must name this. **The authors should
  decide** whether a sensitivity analysis adds `inputevents` in the
  training eras only.

**The judgment calls.**

- **224145 is the heparin signal, and 225152 is its duplicate.** At 77–90%
  of rows with 224145 > 0 before 2020, a 225152 infusion is running, at the
  same rate within 5% in most of them. The co-occurrence falls to 45% in
  2020–22 only because 225152 loses rows. The 2026-10-02 itemid review
  called 224145 a separate circuit dose. That is corrected in
  `config/itemid_review.yaml`. Pre-filter heparin (230044) is in under 10
  stays.
- **0 is a value.** 228004 = 0 means citrate off, which is 24% of rows, and
  224145 = 0 is 71% of rows. `anticoag_class` is `none` only when citrate is
  charted as 0. With citrate not charted, it is null, because "not charted"
  is the 2008–10 gap, not an off pump.
- **Calcium is the patient's, not the filter's.** Results are matched on
  `subject_id` and count from before `circuit_start`, back to the longest
  window (12 h). Both are drawn about every 6 h. A 12 h window rarely holds
  the three points a trend needs, so the labs carry only their last value.
- **The ratio pairs each total calcium with the nearest ionized calcium
  within 60 min,** the feasibility §4 rule. 93% of total calcium results
  inside circuits have one. The pair counts once both are stored; total
  calcium is stored a median 65 min after its draw, ionized 4 min.
- **Calcium bounds come from the data**, cut where the continuous tail ends,
  as for citrate and heparin. They go to the mentor's clinical plausibility
  review. Rows inside included circuits:

  | itemid | Item, unit | Bound | Rows | Below (circuits) | Above (circuits) |
  |---|---|---|--:|--:|--:|
  | 50808 | Free Calcium, mmol/L | 0.6 to 2.0 | 64,778 | 74 (42) | <10 |
  | 50893 | Calcium, Total, mg/dL | 4 to 15 | 42,718 | <10 | 11 (11) |

  Below 0.6 ionized there is a hump around 0.3 mmol/L. That is the
  post-filter target on citrate, so these are circuit samples, not the
  patient. 0.6 is the feasibility §4 cut. A real systemic value of
  0.5–0.6, from severe accumulation, would be lost. That is 24 rows at
  most.

**Coverage, scored circuit-failure rows (317,028).**

| Signal | Has last | Median last | Median hours since |
|---|--:|--:|--:|
| `citrate_rate` | 93.2% | 180 ml/hr | 1 |
| `heparin_dose` | 66.4% | 0 units/hr | 1 |
| `ionized_calcium` | 99.4% | 1.11 mmol/L | 3 |
| `total_calcium` | 90.8% | 9.0 mg/dL | 5 |
| `calcium_ratio` | 87.2% | 2.01 | 5 |

| `anticoag_class` | 2008–10 | 2011–13 | 2014–16 | 2017–19 | 2020–22 |
|---|--:|--:|--:|--:|--:|
| citrate | 55.3% | 70.8% | 62.3% | 59.7% | 62.6% |
| citrate_heparin | 6.9% | 9.1% | 7.3% | 8.6% | 14.2% |
| heparin | 7.7% | 6.3% | 11.8% | 8.2% | 7.2% |
| none | 11.5% | 11.7% | 16.4% | 21.7% | 14.8% |
| unknown | 18.6% | 2.1% | 2.1% | 1.7% | 1.2% |

**Where it applies.** Plan Parts 6.4, 7 and 10. `config/config.yaml →
features.anticoag_signals`, `calcium_labs`, `calcium_pair_minutes`,
`calcium_mg_dl_per_mmol_l`, `plausibility_bounds` (50808, 50893).
`config/itemid_review.yaml` (224145, 225152). Columns are defined in
`docs/data_dictionary.md`, "`anticoag_features`".

## 2026-10-03 — Machine features

**Decision.** `sql/machine_features.sql` builds the machine/circuit feature
group (Part 7, first bullet) as `machine_features`. That is stage 5 of
`run_all.sh`. It has one row per `circuit_failure_labels` row, which is the
same grid as `hypophos_labels`, and 344 columns:

- the 12 machine items in `features.machine_signals`;
- five derived signals: pressure drop, TMP, total UF rate, and the two
  flow-adjusted ratios from the pressure-trend work (Part 3.1);
- for each of the 17 signals: the last value, hours since it, and n / mean /
  min / max / slope / variance over each of `features.window_hours`;
- CRRT mode and circuit runtime.

Anticoagulation (228004 citrate, 224145 heparin) is not in this group. It
has its own group, which must union `chartevents` with `inputevents`
(feasibility §6 proposal 8).

**The judgment calls.**

- **A value counts once it is stored.** It needs `storetime ≤ t` as well as
  `charttime ≤ t` (Part 6.4).
  - Inside included circuits, 15–19% of machine values are stored more than
    an hour after their charttime, and 2–3% more than 3 h after.
  - 226457 Ultrafiltrate Output is stored a median 75 min after its
    charttime, so its charttime comes before the value exists.
  - With charttime alone, 36% of scored rows would take a pressure charted at
    *t* itself as the last value. With `storetime`, 3.2% do.
- **Windows are closed, [t − w, t].** On hourly charting a 3 h window then
  holds up to four values.
  - Even so, gating on `storetime` leaves a median of three values. The 3 h
    slope exists in 54% of scored rows, against 73% without the gate. For
    226457 it exists in 2.4%, because of its late storage.
  - The windows and the three-point minimum (2026-10-02) are kept. A missing
    slope is informative missingness, and the 12 h slope exists in 85–97% of
    rows. **The authors should confirm** that a half-missing 3 h trend is
    acceptable.
- **TMP and pressure drop are derived from the raw pressures in every era.**
  They are not calibrated, and the charted 229247 / 229248 are not used. This
  departs from feasibility §6 proposal 8 ("calibrated on 2014+"):
  - The charted values sit a constant distance from the manual's formulas in
    every `anchor_year_group`: pressure drop −26 to −29 mmHg, TMP −15 to
    −17.5 mmHg (medians, at the same charttime).
    - A calibration would only add that constant. That changes no slope,
      variance or ranking.
    - Estimating it on all the data would be a statistic fit outside the
      training fold (Part 6.4).
  - The charted items exist only from ~2014, so using them where present
    would encode the era.
  - The Hu 2026 rule is defined on machine-computed values. Whether it needs
    the offset is decided at the comparator stage (Part 8.1). The offset
    cancels in a change of Δp/BFR except when blood flow changes.
- **`uf_rate` = PBP + replacement + net fluid removal setting** (228005 +
  224153 + 224191). 224153 is total replacement, not pre-filter only:
  - It is ≥ 228006 Post Filter Replacement Rate at the same charttime in
    99.2% of rows.
  - 228006 is a median 12.5% of it.
  - So adding 228006 would count post-filter replacement twice.
- **Values count only inside their circuit** (`charttime ≥ circuit_start`).
  A window that reaches back past the circuit start would otherwise read
  pressures from the previous filter.
- **`_last` looks back over the longest window only.** A machine value older
  than 12 h falls in downtime, and those rows are not scored.
- **Derived signals need every component at the same charttime.** The four
  raw pressures are charted together in 99.8% of rows.

**Coverage, scored circuit-failure rows (317,028).**

| Signal | Has last | Median n, 3 h | 3 h slope | 12 h slope |
|---|--:|--:|--:|--:|
| Raw pressures, pressure drop, TMP | 99.7% | 3 | 54% | 97% |
| Blood flow | 99.6% | 3 | 52% | 96% |
| `pressure_drop_per_blood_flow` | 99.3% | 2 | 46% | 95% |
| `uf_rate` | 93.1% | 2 | 38% | 87% |
| `tmp_per_uf_rate` | 92.8% | 2 | 34% | 86% |
| Ultrafiltrate output | 98.5% | 2 | 2.4% | 94% |

CRRT mode is missing in 52,121 scored rows (16%). Mode is charted less often
than the machine items.

Last-value medians on scored rows:

- pressure drop 67 mmHg (charted 229248, all rows: 42);
- TMP 97 mmHg (charted 229247, all rows: 81);
- UF rate 3,550 ml/hr;
- pressure drop per blood flow 0.40 mmHg/(ml/min);
- TMP per UF rate 0.028 mmHg/(ml/hr).

**Where it applies.** Plan Parts 6.4 and 7. `config/config.yaml →
features.machine_signals`, `features.crrt_mode_itemid`. Columns are defined
in `docs/data_dictionary.md`, "`machine_features`".

## 2026-10-03 — Plausibility bounds for the CRRT machine items

**Decision.** `features.plausibility_bounds` now bounds the 16 numeric
`chartevents` items that `config/itemid_review.yaml` includes as circuit,
feature or comparator inputs. This settles feasibility §6 proposal 9 for the
machine items. A value outside its bound becomes missing. The exception is
the four raw circuit pressures. A value at most
`features.pressure_clip_margin_mmhg` (50) past a bound is set to the bound,
and only a value further out becomes missing. Medication rates
(`inputevents`), vitals and labs get bounds when their items are validated
for the feature stage.

**Where the numbers come from.** Bounds are the machine's own operating or
settable ranges wherever it has one, not a clinical "normal". These are
taken from the Prismaflex Service Manual (Gambro G5005209, software 7.xx,
§8 Specifications). They are identical on the PrisMax spec sheet, so they
hold whichever machine BIDMC ran in 2020–22. The pressure sensor ranges are
also tabulated in the supplement of Ferrari et al. 2022 (*ASAIO J*), which
must be re-verified before it is cited.

Evidence: chartevents rows inside included circuits, by itemid. "Dropped"
becomes missing and "clipped" is set to the bound. Counts under 10 are
suppressed.

| itemid | Item, unit | Bound | Source | Rows | Dropped (circuits) | Clipped |
|---|---|---|---|--:|--:|--:|
| 224144 | Blood Flow, ml/min | 10 to 450 | device | 311,221 | 229 (163) | — |
| 224149 | Access Pressure, mmHg | −250 to 450 | device | 339,767 | 72 (69) | 87 |
| 224150 | Filter Pressure, mmHg | −50 to 450 | device | 339,797 | 145 (124) | 96 |
| 224151 | Effluent Pressure, mmHg | −350 to 400 | device | 339,504 | 62 (58) | 28 |
| 224152 | Return Pressure, mmHg | −50 to 350 | device | 339,602 | 154 (108) | 245 |
| 229247 | Trans Membrane Pressure, mmHg | −450 to 750 | derived from the sensor ranges | 255,862 | 29 (27) | — |
| 229248 | Pressure Drop, mmHg | −400 to 500 | derived from the sensor ranges | 255,307 | 24 (22) | — |
| 224153 | Replacement Rate, ml/hr | 0 to 8,000 | device | 312,749 | 103 (18) | — |
| 228006 | Post Filter Replacement Rate, ml/hr | 0 to 8,000 | device (replacement) | 292,758 | <10 (<10) | — |
| 228005 | PBP Replacement Rate, ml/hr | 0 to 4,000 | device | 297,299 | 46 (21) | — |
| 224154 | Dialysate Rate, ml/hr | 0 to 8,000 | device | 314,878 | 27 (16) | — |
| 224191 | Hourly Patient Fluid Removal, mL | 0 to 2,000 | device | 333,470 | 415 (190) | — |
| 226457 | Ultrafiltrate Output, mL | 0 to 2,000 | the fluid-removal setting's range | 356,020 | 808 (385) | — |
| 225183 | Current Goal, mL | −2,000 to 2,000 | the fluid-removal setting's range | 326,502 | 32 (<10) | — |
| 228004 | Citrate (ACD-A), ml/hr | 0 to 350 | data: gap | 287,713 | 281 (42) | — |
| 224145 | Heparin Dose (per hour), units | 0 to 4,000 | data: end of continuous tail | 179,586 | 58 (35) | — |

No bound removes more than 0.23% of its item's rows.

**The judgment calls.**

- **Missing, not clipped, by default.** Out-of-range values are
  mostly entry errors. Medians of the far tail are values like 1,142 mmHg
  filter pressure or 1.8 million ml/min blood flow. Clipping these to the
  bound would invent a reading at the extreme.
- **Except pressures just past the sensor limit.** Out-of-range raw
  pressures are 0.63% of pressure rows in the last 3 h of clotted circuits,
  against 0.056% elsewhere. There, most sit just past the limit, such as
  filter pressure charted as 500 against a 450 limit. That is a sensor at
  its limit, charted as a round number. Dropping them would remove 154
  values just before clot events, which is informative missingness in the
  primary outcome. Clipping within 50 mmHg keeps 69 of those 154 as values
  at the limit.

  | Pressure rule | Rows dropped (clot end) | Rows clipped (clot end) | r, derived vs charted Δp / TMP |
  |---|--:|--:|---|
  | No bounds | — | — | 0.08 / 0.17 |
  | Drop all out-of-range | 942 (154) | — | 0.913 / 0.959 |
  | Clip within 25, else drop | 698 (128) | 244 (26) | 0.909 / 0.956 |
  | **Clip within 50, else drop** | 478 (85) | 464 (69) | 0.906 / 0.956 |

  These figures include charted TMP and pressure drop under the drop rule.
  Their bounds are derived, not a sensor's, so they are never clipped.
  The primary rule reproduces the feasibility §1 correlations (0.91 /
  0.96).
- **Blood flow 0 is out of range.** The pump's minimum is 10 ml/min. A zero
  means the pump is stopped, which the circuit definition already treats
  as downtime. It is not a flow to average into a window.
- **Negative settings and outputs are missing.** Fluid removal, rates and
  ultrafiltrate output cannot be set or measured below 0 on the machine.
  Ultrafiltrate output is achieved net removal: its median of 355 mL
  matches the fluid-removal setting's 365 mL. That is why it takes the
  setting's range. It is not total effluent.
- **Current Goal** is a nursing net-balance goal per hour, not a machine
  setting. A positive goal is possible, because other inputs count. It
  takes the fluid-removal range on both sides.
- **Citrate and heparin have no device range in these units.** ACD-A runs
  on an external pump. The Prismaflex syringe (2 to 100 ml/h) does not
  carry it: the median charted rate is 180 ml/hr.
  - Citrate is cut at an empty gap: no row falls in (350, 450] ml/hr. Above
    the gap are 4 circuits at a constant 500 ml/hr, 2.5× blood flow
    against a median ratio of 1.0, plus scattered errors.
  - The heparin tail decays smoothly to 4,000 units/hr. Beyond that, 30
    rows remain, 16 of them above 10,000.
  - Both cuts come from the data. They go to the mentor's clinical
    plausibility review (Part 14).

**Where it applies.** Plan Part 7. `config/config.yaml → features.plausibility_bounds`,
`pressure_clip_margin_mmhg`, `pressure_clip_itemids`. Applied by the
feature stage (not yet built). `docs/data_dictionary.md`, "Plausibility
bounds".

## 2026-10-03 — Repletion sensitivity analysis

**Decision.** `sql/hypophos_labels.sql` now has a switch for what a
repletion order does to a row: a phosphate order, IV or oral, started in the
window before any low draw. Primary: `censor`, as in the entry below.
Two sensitivity analyses bound it from either side:

- `ignore` labels the row from the draws alone. An event the order
  prevented counts as a negative, so this is the lower bound.
- `composite` counts the order as the event. Every repletion counts as an
  averted low, so this is the upper bound. It stays a sensitivity analysis
  for the reason the hypophosphatemia entry rejected it as the primary: it
  would turn a clinician's decision into the label.

Config: `outcomes.hypophosphatemia.repletion_handling_primary` (`censor`)
and `repletion_handling_sensitivity` (`[ignore, composite]`).

**Why build it now.** The censor is informative, and it is uneven across
eras. It removes 6.9 / 8.7 / 8.9 / 9.0 / 16.4% of scored rows across the
five `anchor_year_group` eras, so it weighs most in the temporal test era
(Part 9.2). `crrt.outcomes` now prints each censor reason's share of
scored rows by era, so `run_all.sh` reproduces these numbers.

**Result.** Scored rows, all eras:

| Handling | Positive / labelled rows | Prevalence | Stays with a positive row | Prevalence by era (2008–10 … 2020–22) |
|---|--:|--:|--:|---|
| censor (primary) | 25,703 / 163,674 | 15.7% | 1,298 | 16.6 / 17.1 / 14.9 / 17.5 / **12.6** |
| ignore | 28,345 / 183,119 | 15.5% | 1,302 | 16.5 / 16.7 / 15.0 / 17.5 / **12.2** |
| composite | 45,372 / 183,343 | 24.7% | 1,580 | 22.6 / 24.7 / 23.0 / 25.5 / **27.8** |

Composite labels 224 more rows than ignore. These are repleted rows that
the other two handlings censor for death or for no draw.

**Consequence.** Under the primary and ignore, the test era has the lowest
prevalence. Under composite it has the highest. The 2020–22 era looks
lower-risk partly because repletion there starts before the low draw.
Calibration in the temporal test set must be read with that in mind.
The test-era hypophosphatemia results are reported under all three
handlings (confirmed by the authors 2026-10-03).

**Where it applies.** Plan Parts 5.2, 9.2. `sql/hypophos_labels.sql`,
`src/crrt/outcomes.py` (`summarize_by_era`), `config/config.yaml →
outcomes.hypophosphatemia.repletion_handling_*`, feasibility §6
proposal 11.

## 2026-10-03 — Phosphate repletion is read from orders, oral and IV

**Decision.** The repletion censor (`censor_reason = 'repletion'`) now reads
one source for both routes: a `prescriptions` order for phosphate started in
the label window before any low draw. It replaces the `inputevents` IV doses
of the hypophosphatemia entry below, and adds oral repletion, which that
entry had not counted. Plan Part 5.2 says to account for repletion "via
`inputevents`"; this departs from that for the reason below. Config:
`outcomes.hypophosphatemia.repletion_orders`, a list of routes for each drug.

| Drug (`lower(drug)`) | Routes |
|---|---|
| neutra-phos, phosphorus (K-Phos Neutral tablets) | PO/NG, PO, NG |
| sodium phosphate, potassium phosphate, sodium glycerophosphate | IV |

**Why orders.** The censor has to mean the same thing in every era, because
the temporal split (Part 9.2) tests on 2020–22. Neither administration
record does:

| Era | `emar` charts any medication during the circuit | IV phosphate during circuits: `inputevents` / `emar` / IV orders |
|---|--:|---|
| 2008–10 | 37% of circuits | 418 / 202 / 419 |
| 2011–13 | 37% | 274 / 126 / 268 |
| 2014–16 | 71% | 304 / 247 / 316 |
| 2017–19 | 99% | 456 / 465 / 460 |
| 2020–22 | 98% | **217** / 411 / 426 |

`inputevents` loses about half of IV phosphate in 2020–22, and `emar` is
incomplete before 2017. Orders are steady. Across all drugs, the order
system's volume is 456–523 orders per 1,000 circuit-hours in every era.

**The judgment calls.**

- **Drug list.** Every drug name containing "phos" or "neutra" among cohort
  patients was reviewed by hand. The others are phosphate salts of unrelated
  drugs (codeine, dexamethasone, oseltamivir, cyclophosphamide, ...),
  Caphosol (a mouth rinse) and Fleet Phospho-soda (a bowel prep, under 10
  orders). Phosphate binders do not match the pattern and are not repletion.
  Sodium glycerophosphate (IV, 52 patients) has no `inputevents` item at all.
- **An IV order is one dose.** 4,346 of the 5,554 IV orders among cohort
  patients are for one dose in 24 h. Where a dose in `inputevents` can be
  matched to an order, the order starts a median of 60–62 min earlier in
  every era. The quartiles are 15–23 min and 119–135 min. Censoring at the order is therefore slightly early, which is
  the conservative direction. 23–37% of `inputevents` doses in each era have
  no IV order starting in the 6 h before them. These are probably doses under
  standing protocol orders, and they are not counted.
- **Only new orders count.** Doses under an order that started before *t*
  mean the patient is already on supplements at *t*. That is a feature, not
  a decision made after the prediction.
- `emar` stays the better record of what was actually given (dose times,
  "Not Given"). It can serve as a check in 2017–22. It is not loaded into the
  database.

**Result (primary).** 19,669 rows in 880 circuits are censored for
repletion, 10.1% of scored rows. That compares with 6,766 for `inputevents`
IV only and 17,410 for `inputevents` IV plus oral orders. There are 25,703
positive rows (15.7% of labelled rows; was 27,794, 15.8%). 1,298 of 2,781
at-risk stays have an incident event.

**Consequences.**

- **The censor is informative.** Repletion is started for patients drifting
  toward the threshold, and most of the rows it removes would have been
  negatives. A sensitivity analysis that does not censor on repletion, or
  treats it as part of a composite event, would bound the effect. It is not
  built yet.
- **It is heavier in the test era.** Repletion censors 6.9 / 8.7 / 8.9 /
  9.0 / 16.4% of scored rows across the five eras. Oral orders account for
  most of the rise: 4.1% → 10.1% from 2017–19 to 2020–22. IV goes from 5.3%
  to 7.5%. Oral phosphate orders per circuit-hour rise by about 40% while
  overall order volume is flat, so this is a change in practice, not in
  recording. Name it as test-era drift next to Phoxillum and complete TMP
  charting (feasibility §6 proposal 11).

**Where it applies.** Plan Part 5.2. `sql/hypophos_labels.sql`,
`config/config.yaml → outcomes.hypophosphatemia.repletion_orders`.

## 2026-10-03 — Hypophosphatemia prediction rows

**Decision.** `sql/hypophos_labels.sql` labels the secondary outcome (Part
5.2) on the same hourly grid as circuit failure. This settles feasibility §6
proposal 6. Values are in `config/config.yaml → outcomes.hypophosphatemia`.

| Question | Primary | Sensitivity / other | Config key |
|---|---|---|---|
| Threshold | < 2.0 mg/dL | < 1.5; < 1.0 descriptive only | `moderate_mg_dl`, `sensitivity_mg_dl`, `severe_mg_dl` |
| Horizon | 24 h | — | `horizon_hours` |
| At risk | known result ≥ threshold, drawn ≤ 24 h before | — | `known_value_max_age_hours` |
| IV repletion before the low draw | censored | — | `repletion_itemids` |
| Death in the window | censored | — | — |
| No draw in the window | censored | — | — |

The other judgment calls:

- **Rows are the circuit grid, without the circuit rules.** Warm-up,
  blanking, the 72 h maximum age and downtime exist for the filter. Phosphate
  is cleared by whichever filter is running, so none of them applies.
  Blanking is not needed because the event is a blood draw, not something
  the machine charts, and the result is known only at its `storetime`.
- **The event is the first draw below threshold since the stay's CRRT
  start**, timed at `charttime`. Once it has been drawn the row is no longer
  at risk (`already_low`), even before the result is stored. Scoring such a
  row would ask about an event that has already happened.
- **At risk means known to be above threshold.** The latest result stored by
  *t* and drawn in the previous 24 h must be ≥ 2.0. Without a known result,
  "not already below threshold" (Part 5.2) cannot be checked.
- **Repletion censors; it does not count as an event.** Part 5.2 calls it a
  competing intervention. An IV dose started in the window before any low
  draw may have prevented the event, so the row's outcome is not observed.
  The alternative is a composite event (low draw or repletion). It was
  rejected because it would turn a clinician's decision into the label.
  Cost: 6,766 rows in 305 circuits. Oral phosphate is not counted yet.
- **Phoxillum is a feature and a stratifier, not a censor.** A
  phosphate-containing fluid runs for the whole circuit. Censoring on it
  would remove most Phoxillum stays, all of them in 2020–22, the temporal
  test era (Part 9.2). The feature stage carries it from 230083/230084.
- **A window with no draw is censored, not negative.** The label exists only
  when blood is drawn (feasibility §3). 760 rows.

**Result (primary).** 364,036 rows; 195,343 scored. 27,794 positive rows
(15.8% of labelled rows) in 1,541 circuits and 1,216 patients. 1,301 of 2,781
at-risk stays have an incident event (46.8%), against 1,253 of 2,725 (46.0%)
in feasibility §3. Censored: 11,402 rows by death, 6,766 by repletion, 760
unmeasured. 166,518 rows are past the first low draw.

**Where it applies.** Plan Parts 3.2, 5.2, 5.3. `sql/hypophos_labels.sql`,
`src/crrt/outcomes.py`, `run_all.sh` stage 4.

## 2026-10-03 — Circuit-failure prediction rows

**Decision.** `sql/circuit_failure_labels.sql` turns each included circuit
into prediction rows (Part 6.1) and labels them with the primary event. It
reads the 2026-10-02 outcome keys unchanged. The new judgment calls:

- **Grid.** One row at `circuit_start + k · prediction.step_hours` (1 h),
  up to `circuit_end`. Every row is kept; rows that are not scored carry a
  `not_scored_reason`, so the row flow can be counted like the STROBE flow.
- **The filter ends at the earlier of the last machine charting and the
  System Integrity entry that documents its class.** In 113 of 1,674 clotted
  circuits `Clotted` is charted more than 30 min before the machine stops
  (54 more than an hour before). Taking `circuit_end` as the event time
  would score rows after the clot was charted: prediction of the present,
  the thing blanking (Part 6.2) exists to stop. 440 circuits end earlier
  under this rule.
- **Blanking applies at every circuit end, not only at events.** Which rows
  are scored then does not depend on the label. Blanking only at events
  would drop the last rows of clotted circuits and keep them for every
  other circuit, a difference the model could learn.
- **Rows in downtime are not scored.** A row with no machine charting in
  the preceding `sessionization.gap_hours` falls inside a pause on the same
  filter (`n_pieces` > 1). The rule uses only the past, so it can run in
  real time. 5,034 rows.
- **Fixed-horizon binary labels with censoring (Part 5.3).** A row is
  positive if an event end falls in (*t*, *t* + H]. If a death end falls in
  the window, the label is null with `censor_reason = 'competing_risk'`.
  Otherwise it is negative, including when the filter comes down in the
  window for a reason that is not an event.
- **Follow-up is censored at 72 h of circuit age**
  (`outcomes.circuit_failure.scheduled_change_interval_hours`). This adopts
  the proposal in the cohort entry below. Rows at 72 h or later are not
  scored (`past_max_age`). A window that runs past 72 h with the filter still
  up at 72 h has no observed outcome, so its label is null with
  `censor_reason = 'max_age'`. An end before 72 h is still observed, even
  when the window runs past 72 h. The rule uses only circuit age, which is
  known in real time. Past about 96 h these circuits look like several
  filters stitched together. 1,066 circuits run past 72 h.
  **Cost:** 65 clotted circuits clot after 72 h and lose their positive rows.
- **Blanking stays at 30 min and is still UNLOCKED** (config
  `prediction.blanking_minutes`). The 60 min sensitivity rebinds the same SQL.

**Result (primary, H = 6 h).** 364,036 rows over 8,414 circuits; 317,028
scored. Of the rows that are not scored, 19,719 are past 72 h, 16,828 are in
warm-up, 5,801 are blanked and 4,660 are in downtime. There are 8,639
positive rows (2.8% of labelled rows) in 1,608 circuits and 868 patients.
5,179 rows are censored at 72 h and 4,356 by death. Without the 72 h censor
the numbers are 9,000 positive rows (2.7%) in 1,673 circuits. The
feasibility estimate (§2.6), which had no censor, was 9,230 (2.7%).

**Where it applies.** Plan Parts 5.1, 5.3, 6.1–6.3. `sql/circuit_failure_labels.sql`,
`src/crrt/outcomes.py`, `run_all.sh` stage 4.

## 2026-10-02 — Cohort rules

**Decision.** `sql/crrt_cohort.sql` keeps every circuit and flags the
exclusions. `docs/strobe.md` is the flow diagram (Part 4.6). The steps are:

| Step | Circuits | Stays | Patients |
|---|---:|---:|---:|
| ICU stays with CRRT documented | — | 3,600 | 3,104 |
| Circuits built from machine charting | 9,729 | 2,912 | 2,669 |
| Excluding age < 18 | 9,729 | 2,912 | 2,669 |
| Excluding circuits < 4 h (analysis cohort) | 8,414 | 2,798 | 2,564 |

The judgment calls behind each step:

- **Entry box.** "CRRT documented" means any item of the mimic-code CRRT
  concept or a CRRT procedure. 688 of those stays have no circuit: they have
  CRRT documentation but no machine parameters, the Metavision gap of
  Part 4.2. They are counted in the flow, not silently lost.
- **Age.** It is computed as `anchor_age + year(intime) − anchor_year`,
  the mimic-code `age` concept. MIMIC-IV is adults only, so the step removes
  nothing. It is kept because Part 4.1 names it, and the flow shows the zero.
- **Comfort measures only is not applied.** Part 4.2 lists it. 223758 Code
  Status carries `Comfort measures only` (1,085 rows, 896 stays). Fewer than
  10 circuits start after it is first charted. Applying the rule could not
  change any result. Reporting it exactly would disclose a small cell by
  subtraction, because 8,414 is already published in this log. The methods
  can say so in one sentence.
- **No upper limit on circuit duration.** Part 4.2 mentions "implausible
  CRRT durations". 1,066 circuits run past 72 h and 112 past 120 h. Past
  96 h they look like several filters stitched together: 3.4–4.7 pieces on
  average, and only 58–69% start with a New Filter. Excluding them would
  select on total duration, which is unknown while the circuit runs. That is
  the same objection that reversed the handling of `undocumented` ends, and
  it would also raise the event rate, since their clot rate is 5–12%.
  **Proposal for the outcome stage:** stop scoring a circuit once its age
  passes `outcomes.circuit_failure.scheduled_change_interval_hours`, and
  censor it there. That rule can be applied in real time and avoids
  predicting on rows that may belong to an undocumented second filter.
- **Circuits slightly outside the ICU stay are kept.** 12 start before
  `intime`, and fewer than 10 of those by more than an hour. That is
  charting skew, not an implausible circuit.
- **CRRT start, for the chronic dialysis flag, is the stay's first circuit
  of at least 4 h.** Shorter circuits are mostly documentation artifacts. An
  artifact before the real start must not hide a tunneled catheter charted
  between the two.
- **The flow cannot leak a small cell by subtraction.** `crrt.cohort`
  refuses to write a flow in which an exclusion step changes circuits, stays
  or patients by 1–9. A future step that small must be merged into a
  neighbour or dropped.

**Where it applies.** Plan Parts 4.1, 4.2, 4.6. `sql/crrt_cohort.sql`,
`src/crrt/cohort.py`, `docs/strobe.md`, `run_all.sh` stage 3.

## 2026-10-02 — Chronic dialysis flag from pre-CRRT evidence only

**Decision.** The chronic dialysis flag (Part 4.2) counts only evidence that
exists before the stay's first circuit. A stay is flagged if any of these
holds:

- 225126 "Dialysis patient" = 1 (admission history);
- 225128 "Last dialysis" charted with a date before the first circuit;
- a tunneled catheter (227124 `Tunneled (PermaCath)`, 229536
  `Tunneled 2-Lumen`) charted before the first circuit;
- a dialysis-dependence ICD code on an *earlier* admission of the same
  patient.

ICD codes from the same admission count only in a sensitivity flag. The
handling itself is unchanged: kept and flagged in the primary analysis,
excluded in a sensitivity analysis. Keys: `cohort.chronic_dialysis`.

| Flag | Circuits ≥4 h | Clotted | Patients |
|---|---:|---:|---:|
| Previous: same-admission ICD only | 1,892 (22.5%) | 337 | — |
| **Primary: pre-CRRT evidence** | **1,742 (20.7%)** | **315** | **538** |
| Sensitivity: primary + same-admission ICD | 2,449 (29.1%) | 433 | — |

Contributions to the primary flag: admission history 835 circuits, last
dialysis date 583, tunneled catheter 697, ICD on an earlier admission 971.
The previous flag is reproduced exactly (1,892 circuits, 337 clots), so the
22% in the ESRD entry below was same-admission ICD. 707 circuits carried it
with no pre-CRRT evidence at all.

**Why.**

- Discharge diagnoses are coded after the admission. N18.6 or Z99.2 on the
  same admission can describe a patient who *became* dialysis dependent
  during it, which is AKI non-recovery, an outcome of the CRRT course rather
  than a baseline condition. Among stays where 225126 is charted, at least 68 have
  same-admission ICD ESRD but 225126 = 0.
- Used as a feature, a same-admission discharge code is post-*t*
  information (Part 6.4).
- The ICD list was checked against `d_icd_diagnoses`, not remembered. It
  holds ESRD, renal dialysis status or dependence, and noncompliance with
  renal dialysis. CKD stage 5 and the hypertensive "stage V or ESRD" codes
  are left out: they do not separate dialysis dependence.

**Changed from the proposal in the itemid review entry.** Intermittent HD
earlier in the same stay is *not* a source. AKI patients are often started
on IHD and moved to CRRT when they become unstable, so it would repeat the
same-admission error. 225441 and 226499 stay included, but only to describe
IHD next to CRRT.

**Limits.** "Earlier admission" means an earlier admission to this hospital.
A patient on outpatient dialysis who has never been admitted here before is
caught only by the admission history, last dialysis date or tunneled
catheter. Admission history (225126) records pre-admission status, so it
counts whenever it is charted in the stay. As a model feature, it is
available only from its charttime.

**Where it applies.** Plan Part 4.2. `config/config.yaml →
cohort.chronic_dialysis`, read by `sql/crrt_cohort.sql` (`run_all.sh`
stage 3).

## 2026-10-02 — Itemid review

**Decision.** Every candidate in `docs/itemids.md` was reviewed by hand
against the full MIMIC-IV 3.1 build (Part 2.3): 167 itemids, 40 included and
127 excluded. Each verdict and its evidence is in `config/itemid_review.yaml`.
`crrt.itemid_inventory` copies them into `docs/itemids.md`, which it rewrites
on every run, so a verdict typed into the markdown would not survive. This
closes the "Still open" item of the circuits entry below: the five machine
itemids, 224146 and 225956 are confirmed.

| Role | Included itemids |
|---|---|
| Circuit definition | 224144, 224149–224152 (machine running); 224146, 225956 (filter events) |
| Label | 224146, 225956 |
| Comparators (Part 8.1) | 224146 `Clots Increasing`; 229247 TMP, 229248 pressure drop, and the raw pressures they derive from |
| Features: machine and prescription | 227290 mode, 224153, 228005, 228006, 224154 (replacement and dialysate rates), 224191, 226457, 225183 |
| Features: anticoagulation | 228004 citrate, 227529/227528 ACD-A, 227525 CRRT calcium, 224145 circuit heparin, 225152 systemic heparin, 225147 argatroban, 225148 bivalirudin |
| Features: access | 224270 dialysis catheter (site, insertion), 227124/229536 catheter type, 225322 insertion date |
| Hypophosphatemia | 225834 K Phos, 225835 Na Phos (repletion); 230083, 230084, 225976 (replacement fluid) |
| Cohort | 225126, 225128 (dialysis history), 227124/229536 (tunneled catheter): chronic dialysis flag; 225441, 226499 (intermittent HD, descriptive); 225802 |
| Validation only | 225436 CRRT Filter Change, 225802 CRRT procedure interval |

**Judgment calls.**

- **The sweep had a recall gap.** `phosph` does not match "K Phos" or
  "Na Phos". Those are the phosphate repletion items Part 5.2 requires, with
  418 and 854 stays with a circuit. No pattern matched "clot" either.
  `phos` and `clot` were added to `itemid_inventory.label_patterns`. Two
  other gaps were checked and left alone. A pheresis catheter is in place at
  the start of only 18 circuits. The Prismasate `inputevents` items have no
  rows.
- **Laboratory values come from `hosp.labevents`, never chartevents.** The
  chartevents lab items are copies: 225677 Phosphorous matches labevents
  50970 at the same subject and charttime in 99.6% of rows, and 229375
  Anti-Xa matches 51228 in 99.6%. Labevents carries `storetime`. For
  phosphate, storetime is a median 83 min (p95 248 min) after charttime. The
  `storetime` rule in the leakage checklist (Part 6.4) therefore changes the
  hypophosphatemia features materially; it is not a formality.
- **Pressure drop and TMP can be derived for every era.** The
  machine-computed 229248 and 229247 exist in only 2,090 stays: 38% of
  2008–2013 stays (by `anchor_year_group`), 91% of 2014–2016 and all of
  2017–2022. They track the raw pressures at a fixed offset that is the same
  in every era:
  - pressure drop ≈ filter − return − 27 mmHg, within ±10 mmHg in 75% of
    rows;
  - TMP ≈ (filter + return)/2 − effluent − 16.5 mmHg, within ±10 mmHg in 91%
    of rows.

  (Plain Pearson r is 0.07 and 0.17 because of outliers. Within each decile of
  the derived value the relationship is tight and monotone.) **Proposal for
  the feature stage, not decided here:** derive both from the raw pressures
  for every circuit, so the feature means the same thing in every era, and
  keep the charted values as a check. Report the Hu 2026 rule two ways: on
  charted values in the circuits that have them, and on derived values for
  all circuits. Because Prismaflex's computed values are offset from the
  textbook formulas, Hu's Aquarius thresholds cannot transfer unrecalibrated.
  That reinforces the recalibrated arm already in Part 3.1.
- **Anticoagulation is a core feature group, and citrate dominates it.**
  Across 8,414 circuits:

  | Agent | Circuits |
  |---|---:|
  | Citrate charted > 0 | 6,190 (74%) |
  | Circuit heparin (224145 > 0) | 1,928 |
  | Systemic heparin infusion (225152) | 1,954 |
  | Argatroban | 126 |
  | Bivalirudin | 115 |
  | None documented | 1,101 (13%) |

  228004 is the primary citrate signal. The ACD-A medication record is the
  secondary source. 227526 (citrate in mmol) records the same infusion again
  and is excluded.
- **224191 and 226457 are both kept.** They are different quantities, a
  setting and an achieved output: at the same charttime they agree within
  10 mL in only 44% of rows.
- **Exposure to phosphate-containing fluid is under-ascertained.** Phoxillium
  appears only in 230083 and 230084. Those two items cover 412 stays, two
  thirds of them in 2020–2022. Before them, the only trace is `Other` in
  225976 (2,232 rows). Part 5.2 must either name this as a limitation or
  restrict a sensitivity analysis to stays where 230083/230084 are charted.
- **Catheter site is mostly missing.** The 224270 `location` field is filled
  in 32% of rows. Lock volume (224404/224406) was tested as a proxy for site
  and does not separate sites, so it is excluded. Catheter type (tunneled vs
  temporary) is well populated and is included.

**The chronic dialysis flag.** Settled the same day; see the entry above.
The ESRD entry below flags chronic dialysis dependence from ICD codes. Discharge
diagnoses of the *same* admission (N18.6, Z99.2) can record dialysis
dependence that *began* during that admission, which is AKI non-recovery, an
outcome of the CRRT course. Among stays with a circuit where 225126 "Dialysis
patient" is charted, 68 have ICD ESRD but 225126 = 0. A flag built from
same-admission ICD would mislabel those patients. Used as a feature, it would
also be post-*t* information (Part 6.4).

Proposal for the cohort stage: flag only on evidence that exists before the
first circuit:
- 225126 = 1, or 225128 charted;
- a tunneled catheter (227124/229536) charted before the first circuit;
- intermittent HD (225441/226499) before the first circuit;
- an ESRD ICD code on a *prior* admission.

Same-admission ICD would then be a sensitivity analysis.

**Where it applies.** Plan Parts 2.3, 4.2, 5.2, 6.4 and 7.
`config/itemid_review.yaml`, `config/config.yaml →
itemid_inventory.label_patterns`, `src/crrt/itemid_inventory.py`,
`docs/itemids.md`.

## 2026-10-02 — Small-cell rule extended to percentiles and Text values

**Decision.** Everything committed or printed goes through
`crrt.report.count`, which shows counts from 1 to 9 as `<10`
(`reporting.small_cell_threshold`). Two extensions apply wherever values,
not just counts, are published, starting with `docs/itemids.md`:

- **Percentiles** are shown only when at least 10 numeric values from at
  least 10 stays stand behind them. Otherwise they are shown as —.
- **Text values** charted fewer than 10 times are not listed at all; the
  table only notes that such values exist.

**Why.** The aggregate exemption (entry below) covers counts with small cells
suppressed. A p5 or p95 over a handful of rows is close to a row-level
value. A rare value of a Text item may be free text, and free text is
explicitly not exempt.

**Where it applies.** Plan Part 1.4, `src/crrt/report.py`,
`src/crrt/itemid_inventory.py`. `docs/itemids.md` is now generated from the
full MIMIC-IV 3.1 build. Its `include? / reason` column was empty before
the regeneration, so no review was lost.

## 2026-10-02 — Primary event, unclear and death handling, ESRD, duration floor, feature windows

**Decision.** These settle feasibility §6 proposals 1, 3, 8 and 12, plus the
circuit parameters in the entry below. Values are in `config/config.yaml`.

| Question | Primary | Sensitivity | Config key |
|---|---|---|---|
| Event | `clotted` (1,674 circuits, 900 patients) | `clotted` + `clots_increasing` | `outcomes.circuit_failure.event_classes_*` |
| `undocumented` ends (1,221, 14.5%) | non-event | excluded | `unclear_handling_*` |
| Death within 12 h (877) | censored, competing risk (Part 5.3) | — | `competing_risk_classes` |
| Maximum downtime on one filter | 6 h | 4 h, 12 h | `circuits.max_downtime_hours*` |
| Chronic dialysis dependence (22% of circuits) | kept, flagged | excluded | `cohort.esrd_handling_*` |
| Minimum circuit duration | 4 h | — | `cohort.min_session_duration_hours` |
| Trend-feature windows | 3 / 6 / 12 h, slope and variance need ≥3 points | — | `features.window_hours`, `features.min_points_for_trend` |

**Why.**

- **Event = documented `Clotted` only.** `Clots Increasing` is the
  nurse-observation comparator (Part 8.1) and a candidate feature. If it is
  also in the label, it cannot be either.
- **`undocumented` as non-event.** This reverses the original plan (Part 5.1
  step 5: exclude primary, non-event sensitivity). Exclusion selects circuits
  on how they ended, which is unknowable at prediction time. About a quarter
  of these circuits are probably hidden clots (feasibility §2.4), so the
  primary is biased toward the null rather than inflated. Excluding them
  becomes the sensitivity analysis.
- **Death is censored.** A circuit running when the patient dies did not
  survive (Part 5.3). Counting it as a non-event mixes outcomes, and excluding
  it selects on a future event.
- **6 h downtime.** The event count is insensitive to it (1,657 / 1,674 /
  1,678 at 4 / 6 / 12 h). Only the undocumented bucket moves.
- **ESRD kept.** Circuit clotting is not specific to AKI. Excluding these
  patients up front would cost 22% of circuits and 337 documented clots.
- **4 h floor.** 841 circuits are under 1 h and are documentation artifacts.
  With the 2 h warm-up (Part 6.3), a 4 h circuit still has about 2 h of
  scoreable rows.
- **Windows 3 / 6 / 12 h.** Machine charting is hourly (median 60 min), so the
  old 1 h window held one point and could not produce a slope or variance.

**Where it applies.** Plan Parts 4.1, 4.2, 4.4, 5.1, 5.3 and 7. The
outcome-label stage (`run_all.sh` stage 4) reads these keys.

## 2026-10-02 — Circuits follow filter identity

**Status.** Implements proposals 1–2 of `docs/feasibility.md` §6 (branch
`feat/crrt-circuits`). `max_downtime_hours` was confirmed the same day (entry
above), pending the co-author's PR review. Every parameter below lives
in `config/config.yaml → circuits`.

**Decision.**

- A circuit is one filter, not one run of charting (Part 4.4 amended).
  Segments split at a machine-charting gap longer than
  `sessionization.gap_hours` (2 h). A later segment stays on the same filter
  unless one of these is true: it has a New Filter at its start, the segment
  before ended `Clotted` or with a documented reason, or the gap is longer
  than `circuits.max_downtime_hours`.
- `max_downtime_hours` = 6, with sensitivity analyses at 4 and 12.
- The termination class is the 9-class hierarchy of feasibility §2.3. It
  reads documentation (System Integrity, 225956, death, ICU discharge) and
  circuit age only, never pressure (§2.4).
- The documentation windows and the 66 h `reached_limit_hours` are carried
  over unchanged from the feasibility queries, so that the planning counts
  stay reproducible.
- A New Filter with no machine charting before the next one produces no
  circuit. That removes 40 circuits, none of them ≥4 h.
- `crrt_circuits` keeps every circuit. The ≥4 h floor is applied at the
  cohort step, so the STROBE flow (Part 4.6) can count what it removes.

**Why.** Under the plain 2 h gap rule, 43% of circuits ≥4 h end with no
documentation, and 66% of those resume without a New Filter (feasibility
§2.2). Those are pauses on the same filter. The documented-clot count is
insensitive to `max_downtime_hours` (1,657 / 1,674 / 1,678 at 4 / 6 / 12 h).

**Check.** On MIMIC-IV 3.1 the implementation reproduces the feasibility
prototype circuit for circuit: 9,729 circuits with identical stay, start,
end and class. That is 8,414 circuits ≥4 h (2,798 stays, 2,564 patients),
1,674 of them `clotted`.

**Still open.** The hand review of the five machine itemids and
224146/225956 in `docs/itemids.md` (Part 2.3). The feasibility vocabulary
tables (§2.1) are the evidence so far.

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
