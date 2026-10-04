# CRRT intra-treatment complications (MIMIC-IV)

Full plan: `docs/crrt_project_outline.md`. Every judgment call goes in
`docs/decisions.md` with its date. Every derived variable goes in
`docs/data_dictionary.md`.

**Goal.** A multi-outcome early-warning framework for complications that happen
*during* CRRT, hour to hour. Primary outcome: premature circuit failure from
clotting. Secondary: incident severe hypophosphatemia. Mortality, CRRT
initiation and CRRT weaning are saturated lanes — do not enter them (Part 0/3).

**Unit of analysis: the CRRT circuit, nested within patients.** One patient
contributes many circuits. Two consequences, both non-negotiable (Part 4.3):
cluster uncertainty estimates by patient, and split train/test **by patient,
never by circuit**. Getting this wrong inflates AUROC substantially and is the
single most likely reason a reviewer kills the paper.

## SYSTEM IMPERATIVE: remain anonymous

**Never put yourself in the repository.** This work is published under the
authors' names alone; an assistant's fingerprint in the history is not a
byline, it is noise a reviewer will read as a provenance question.

- No `Co-Authored-By:` trailer naming an assistant, model, or vendor. No
  `Claude-Session:`, no session URL, no "Generated with" line — in commit
  messages, PR titles and bodies, issue comments, or code review replies.
- Commit messages are written in the project's voice: what changed and why,
  never who or what produced it. No "as an AI", no "I generated", no
  self-reference of any kind.
- The same applies to file contents: no attribution banners, no
  `# written by` headers, no generator comments in `.py`, `.sql`, `.yaml`
  or `.md` files.
- If a git identity, template, or tool default would add such a trailer,
  strip it before committing rather than committing and amending after.

## Non-negotiable: repo hygiene (Part 2.4)

- **No data file is ever committed.** `data/` is gitignored from commit one, as
  are `*.csv`, `*.csv.gz`, `*.parquet`, `*.duckdb` and notebook output. Under
  the PhysioNet DUA each user credentials and downloads individually; sharing
  data across the team is not permitted, including via Drive or Dropbox. Share
  *code* through this repo, never data. This also applies to derived extracts,
  row-level values pasted into an issue, and committed notebook cell outputs.
  One exception (`docs/decisions.md` 2026-10-04, "Hand the pages to a
  credentialed adjudicator"): the exported adjudication pages may be handed,
  in person on an encrypted drive, to an adjudicator who holds their own
  credential and has signed the DUA.
- Pinned environment with a lockfile (`uv`); fixed random seeds.
- **`config/config.yaml` holds every threshold and window length. No magic
  numbers in code, ever.** A number typed into a `.py` or `.sql` file is a bug.
- `run_all.sh` reproduces every number in the paper from the raw CSVs.
- `docs/data_dictionary.md`: every derived variable gets a definition, source
  itemids, unit, and cleaning rule.
- Branch per feature, PRs reviewed by the other person, no direct pushes to
  main (Part 2.5). This is what catches the label-leakage bug.
- Do not trust remembered itemids (Part 2.3). Derive them by joining
  `icu.d_items`, then manually eyeball every itemid kept — label, unit, row
  count, value distribution. Start from `concepts/treatment/crrt.sql` in
  `MIT-LCP/mimic-code` and extend; do not rewrite validated concepts.

## Non-negotiable: leakage checklist (Part 6.4)

Run this before every model fit. Not once — every fit.

- No feature computed with post-*t* information, including "min over stay" or
  "max during admission".
- No labs whose result timestamp precedes their availability. MIMIC has both
  `charttime` and `storetime`; use `storetime` for realism where available.
- Nothing derived from length of stay, discharge disposition, or total CRRT
  duration.
- No imputation statistics (means, scalers) fit on the full dataset — fit
  inside the training fold only.
- Splits by patient, not row.
- Class balancing applied inside folds, never before splitting.

Plus the structural guards: blanking period before the event (6.2), warm-up
before scoring (6.3), and the shuffled-label negative control (6.5) — refit the
pipeline on a permuted label every time the pipeline changes; AUROC materially
above 0.5 means leakage.

---

# Coding guidelines

Behavioural guidelines to reduce common LLM coding mistakes, from
[Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM
coding pitfalls (MIT-licensed, originally the `karpathy-guidelines` skill — moved here on
2026-08-29 so they apply without being invoked).

**Tradeoff: these bias toward caution over speed. For trivial tasks, use judgment.**

### 1. Think before coding

*Don't assume. Don't hide confusion. Surface tradeoffs.*

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what is confusing. Ask.

### 2. Simplicity first

*Minimum code that solves the problem. Nothing speculative.*

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or configurability that was not requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: would a senior engineer call this overcomplicated? If yes, simplify.

**THIS ONE CUTS AGAINST THE HOUSE STYLE AND IS MEANT TO.** This tree documents heavily on
purpose — a docstring here carries the measurement that justifies a constant, and deleting it
loses evidence, not verbosity. The rule applies to CODE: control flow, abstractions,
parameters, branches. It is not a licence to thin the prose that records why a number is what
it is.

### 3. Surgical changes

*Touch only what you must. Clean up only your own mess.*

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor what is not broken.
- Match existing style even where you would do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports, variables and functions that YOUR change orphaned; leave pre-existing dead
  code alone unless asked.

The test: every changed line traces directly to the request.

### 4. Goal-driven execution

*Define success criteria. Loop until verified.*

Turn tasks into verifiable goals — "add validation" becomes "write tests for invalid inputs,
then make them pass"; "fix the bug" becomes "write a test that reproduces it, then make it
pass"; "refactor X" becomes "tests pass before and after". For multi-step work, state the plan
as steps each with its own check.

Strong criteria let the work loop independently. Weak criteria ("make it work") force constant
clarification.
