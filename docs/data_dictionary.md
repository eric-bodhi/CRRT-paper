# Data dictionary

Every derived variable: definition, source itemids, unit, cleaning rule (plan
Part 2.4). Thresholds are named by their `config/config.yaml` key rather than
restated, so this file cannot drift from the config.

## `crrt_circuits`

One row per CRRT circuit (filter). Built by `sql/crrt_circuits.sql`, run from
`uv run python -m crrt.circuits` (stage 2 of `run_all.sh`). Derivation and
evidence: `docs/feasibility.md` §2.2–2.3; decision: `docs/decisions.md`
2026-10-02.

**Sources.**

| Role | Table | itemid / column | Config key |
|---|---|---|---|
| Machine running | `chartevents` | 224144 Blood Flow (ml/min), 224149 Access Pressure, 224150 Filter Pressure, 224151 Effluent Pressure, 224152 Return Pressure | `circuits.machine_itemids` |
| Filter events | `chartevents` | 224146 System Integrity (`value`) | `circuits.system_integrity_itemid` |
| Documented reason | `chartevents` | 225956 Reason for CRRT Filter Change (`value`) | `circuits.filter_change_reason_itemid` |
| Death | `admissions` | `deathtime`, via `icustays.hadm_id` | — |
| ICU discharge | `icustays` | `outtime` | — |

**Cleaning rules.**

- A machine row counts when `valuenum` is not null. Only its charttime is
  used, never its value, so plausibility bounds do not apply here.
- Duplicate charttimes across the five machine items collapse to one.
- System Integrity and reason rows with null `value` are ignored.
- A New Filter with no machine charting before the next piece start produces
  no circuit (40 in MIMIC-IV 3.1, none of them ≥4 h).
- No row is dropped for duration. The ≥4 h floor
  (`cohort.min_session_duration_hours`) is a cohort step, applied downstream.

**Construction.** *Segments* are runs of machine charting with no gap longer
than `sessionization.gap_hours`. Each segment is cut into *pieces* at every
New Filter charted more than `circuits.new_filter_min_hours_after_segment_start`
after the segment start. Consecutive pieces of a stay are the same circuit
unless `start_reason` below is set.

| Column | Type / unit | Definition |
|---|---|---|
| `circuit_id` | integer | Row number ordered by `stay_id`, `circuit_no`. Stable for a given input and config. |
| `subject_id` | integer | Patient. The grouping key for every split and CI (Part 4.3). |
| `hadm_id` | integer | From `icustays`. |
| `stay_id` | integer | ICU stay. |
| `circuit_no` | integer | 1, 2, … in time order within the stay. |
| `circuit_start` | timestamp | Start of the circuit's first piece: the first machine charttime of a segment, or the New Filter charttime that cut a segment. |
| `circuit_end` | timestamp | Last machine charttime of the circuit's last piece. |
| `duration_hours` | hours | `circuit_end − circuit_start`, including downtime. |
| `running_hours` | hours | Sum of piece durations, i.e. `duration_hours` minus gaps longer than `sessionization.gap_hours`. |
| `n_pieces` | count | Pieces stitched into the circuit. >1 means at least one pause on the same filter. |
| `start_reason` | text | Why this circuit is not a continuation of the one before. The first of these that applies: `first_of_stay`; `new_filter` (a New Filter cut the segment, or one is charted within `circuits.windows_hours.new_filter_at_start` of the start); `after_clotted` (the previous piece has `end_clotted`); `after_reason` (the previous piece has an `end_reason`); `after_long_gap` (the gap from the previous piece exceeds `circuits.max_downtime_hours`). |
| `starts_new_filter` | boolean | A New Filter documents this circuit's start (window `new_filter_at_start`). |
| `end_clotted` | boolean | System Integrity `Clotted` within `windows_hours.clotted_at_end` of `circuit_end`. |
| `end_clots_increasing` | boolean | `Clots Increasing` within `windows_hours.clots_increasing_at_end`. |
| `end_stopped` | boolean | `Discontinued` or `Recirculating` within `windows_hours.stopped_at_end`. |
| `end_reason` | text | 225956 value within `windows_hours.reason_at_end` (lexical max if several). Observed values: `Clotted`, `Procedure`, `Line changed`. |
| `end_death` | boolean | `admissions.deathtime` within `windows_hours.death_after_end`. |
| `end_icu_discharge` | boolean | `icustays.outtime` within `windows_hours.icu_discharge_after_end`. |
| `last_of_stay` | boolean | No later circuit in the stay. |
| `termination_class` | text | How the circuit ended. Hierarchical: the first rule that applies wins (feasibility §2.3, classes 1–9). The table below gives the rules. |

Every window is `[hours before, hours after]` the anchor time. Each `end_*`
flag is taken from the circuit's last piece.

| `termination_class` | Rule (first match wins) | Feasibility class |
|---|---|---|
| `clotted` | `end_clotted`, or `end_reason = 'Clotted'` | 1 |
| `clots_increasing` | `end_clots_increasing` | 2 |
| `death` | `end_death` | 3 |
| `reached_limit` | `duration_hours ≥ circuits.reached_limit_hours` | 4 |
| `procedure_or_line_change` | `end_reason` is `Procedure` or `Line changed` | 5 |
| `icu_discharge` | `end_icu_discharge` | 6 |
| `crrt_ended` | `last_of_stay` | 7 |
| `stopped_then_restarted` | `end_stopped` | 8 |
| `undocumented` | none of the above | 9 |

`termination_class` reads documentation and circuit age only, **never a
pressure**. Pressure is used to validate the label (feasibility §2.4), and a
label built from pressure would grade a pressure-based model on its own
inputs. Which classes count as events, non-events or censored is an outcome
decision (Part 5.1 step 5, Part 5.3), not part of this table.
