-- circuit_failure_labels: one row per circuit per prediction time, with the
-- circuit-failure label (Parts 5.1, 5.3, 6.1-6.3).
--
-- Decisions in docs/decisions.md (2026-10-02, "Primary event, unclear and
-- death handling"; 2026-10-03, "Circuit-failure prediction rows"). Every
-- column is defined in docs/data_dictionary.md.
--
-- Rows: every included crrt_cohort circuit, at circuit_start + k * `step`
-- up to circuit_end. No row is dropped. A row that is not scored names the
-- first rule it fails in `not_scored_reason`; the model stages read
-- `WHERE scored`.
--
-- The filter ends at `end_time`: the earlier of the last machine charting
-- and the System Integrity entry that documents the circuit's termination
-- class (`Clotted`, or `Clots Increasing`), searched in the same window
-- crrt_circuits used to classify it. A clot charted before the machine stops
-- is the moment the filter failed; scoring after it predicts the present.
--
-- Scoring rules, in order:
--   1. unclear_excluded: the circuit's class is in `unclear_classes` and
--      `unclear_handling` is 'exclude' (a sensitivity analysis).
--   2. warmup: less than `warmup` since circuit_start (Part 6.3).
--   3. blanking: within `blanking` of end_time, or after it (Part 6.2).
--      Applied at every circuit end, whatever its class, so that which rows
--      are scored does not depend on the label.
--   4. downtime: no machine charting in the `running_gap` before the row.
--      The filter is paused; there is nothing to alert on.
--
-- Label, for scored rows: did the filter end as an event in (t, t + horizon]?
--   true   an `event_classes` end_time falls in the window.
--   NULL   a `competing_risk_classes` end_time falls in the window. The
--          circuit was censored by death (Part 5.3); censor_reason says so.
--   false  otherwise: the filter ran through the window, or came down in it
--          for a reason that is not an event.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.outcomes. Expects crrt_circuits, crrt_cohort and chartevents.

CREATE OR REPLACE TABLE circuit_failure_labels AS
WITH circ AS (
    SELECT c.circuit_id, c.subject_id, c.stay_id, c.circuit_start, c.circuit_end,
           c.termination_class
    FROM crrt_circuits AS c
    JOIN crrt_cohort AS k USING (circuit_id)
    WHERE k.included
),

documented_end AS (
    SELECT c.circuit_id, min(x.charttime) AS documented_at
    FROM circ AS c
    JOIN chartevents AS x
      ON x.stay_id = c.stay_id
     AND x.itemid = getvariable('system_integrity_itemid')
    WHERE (c.termination_class = 'clotted' AND x.value = 'Clotted'
           AND x.charttime BETWEEN c.circuit_end - getvariable('clotted_at_end_before')
                               AND c.circuit_end + getvariable('clotted_at_end_after'))
       OR (c.termination_class = 'clots_increasing' AND x.value = 'Clots Increasing'
           AND x.charttime BETWEEN c.circuit_end - getvariable('clots_increasing_at_end_before')
                               AND c.circuit_end + getvariable('clots_increasing_at_end_after'))
    GROUP BY c.circuit_id
),

ends AS (
    SELECT
        c.*,
        -- least() skips NULL: circuits with no documenting entry end at
        -- circuit_end.
        least(c.circuit_end, d.documented_at) AS end_time,
        list_contains(getvariable('event_classes'), c.termination_class) AS is_event,
        list_contains(getvariable('competing_risk_classes'), c.termination_class) AS is_competing,
        list_contains(getvariable('unclear_classes'), c.termination_class)
            AND getvariable('unclear_handling') = 'exclude' AS is_excluded
    FROM circ AS c
    LEFT JOIN documented_end AS d USING (circuit_id)
),

grid AS (
    SELECT *, unnest(generate_series(circuit_start, circuit_end, getvariable('step'))) AS pred_time
    FROM ends
),

machine AS (
    SELECT DISTINCT stay_id, charttime
    FROM chartevents
    WHERE list_contains(getvariable('machine_itemids'), itemid)
      AND valuenum IS NOT NULL
),

-- The last machine charting at or before each prediction time.
running AS (
    SELECT g.*, m.charttime AS last_machine_at
    FROM grid AS g
    ASOF LEFT JOIN machine AS m
      ON m.stay_id = g.stay_id AND m.charttime <= g.pred_time
),

flagged AS (
    SELECT
        *,
        CASE
            WHEN is_excluded THEN 'unclear_excluded'
            WHEN pred_time - circuit_start < getvariable('warmup') THEN 'warmup'
            WHEN pred_time + getvariable('blanking') >= end_time THEN 'blanking'
            WHEN last_machine_at IS NULL
              OR pred_time - last_machine_at > getvariable('running_gap') THEN 'downtime'
        END AS not_scored_reason
    FROM running
)

SELECT
    circuit_id, subject_id, stay_id, pred_time,
    epoch(pred_time - circuit_start) / epoch(INTERVAL '1 hour') AS hours_since_start,
    termination_class, end_time,
    not_scored_reason,
    not_scored_reason IS NULL AS scored,
    CASE
        WHEN not_scored_reason IS NOT NULL THEN NULL
        WHEN is_event AND end_time <= pred_time + getvariable('horizon') THEN true
        WHEN is_competing AND end_time <= pred_time + getvariable('horizon') THEN NULL
        ELSE false
    END AS label,
    CASE
        WHEN not_scored_reason IS NOT NULL THEN NULL
        WHEN is_competing AND end_time <= pred_time + getvariable('horizon') THEN 'competing_risk'
    END AS censor_reason
FROM flagged
ORDER BY circuit_id, pred_time;
