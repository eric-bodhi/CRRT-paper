-- hypophos_labels: one row per circuit per prediction time, with the
-- incident hypophosphatemia label (Parts 3.2, 5.2, 5.3, 6.1).
--
-- Decision in docs/decisions.md (2026-10-03, "Hypophosphatemia prediction
-- rows"). Every column is defined in docs/data_dictionary.md.
--
-- Rows: the same grid as circuit_failure_labels, every included crrt_cohort
-- circuit at circuit_start + k * `step` up to circuit_end. Phosphate is
-- cleared while the filter runs, whichever filter it is, so the circuit
-- rules (warm-up, blanking, maximum age, downtime) do not apply. No row is
-- dropped; the model stages read `WHERE scored`.
--
-- The event is the first phosphate below `threshold` charted at or after
-- the stay's CRRT start (its first included circuit). The event time is
-- charttime: when the blood was drawn. A result is known at t only once
-- stored (storetime <= t, Part 6.4).
--
-- Scoring rules, in order (the row must be at risk of an INCIDENT event):
--   1. already_low: the event was drawn at or before t, even if its result
--      is not yet stored. The patient is already below threshold.
--   2. no_known_value: no result drawn in the `max_age` before t is stored
--      by t, so whether the patient is below threshold is unknown.
--   3. known_low: the latest known result is below threshold (drawn before
--      CRRT start, or the row would be already_low).
--
-- Label, for scored rows, over the window (t, t + horizon]:
--   NULL   repletion: an IV phosphate dose, or a new oral phosphate order,
--          starts in the window before any low value. It is a competing
--          intervention (Part 5.2) that can prevent the event. Oral doses
--          under an order that started before t are not new: the patient
--          is already on supplements at t, which is a feature.
--   true   the event is drawn in the window.
--   NULL   competing_risk: the patient dies in the window (Part 5.3).
--   NULL   unmeasured: no phosphate is drawn in the window, so its absence
--          is not evidence of a normal value.
--   false  otherwise.
-- censor_reason says which NULL a row is.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.outcomes. Expects crrt_circuits, crrt_cohort, labevents, inputevents,
-- prescriptions and admissions.

CREATE OR REPLACE TABLE hypophos_labels AS
WITH circ AS (
    SELECT c.circuit_id, c.subject_id, c.hadm_id, c.stay_id, c.circuit_start, c.circuit_end
    FROM crrt_circuits AS c
    JOIN crrt_cohort AS k USING (circuit_id)
    WHERE k.included
),

crrt_start AS (
    SELECT stay_id, subject_id, min(circuit_start) AS crrt_start
    FROM circ
    GROUP BY stay_id, subject_id
),

phos AS (
    SELECT subject_id, charttime, storetime, valuenum
    FROM labevents
    WHERE itemid = getvariable('phosphate_itemid')
      AND valuenum IS NOT NULL
      AND subject_id IN (SELECT subject_id FROM circ)
),

first_low AS (
    SELECT s.stay_id, min(p.charttime) AS first_low_at
    FROM crrt_start AS s
    JOIN phos AS p
      ON p.subject_id = s.subject_id
     AND p.charttime >= s.crrt_start
     AND p.valuenum < getvariable('threshold')
    GROUP BY s.stay_id
),

grid AS (
    SELECT c.*, f.first_low_at,
           unnest(generate_series(c.circuit_start, c.circuit_end, getvariable('step'))) AS pred_time
    FROM circ AS c
    LEFT JOIN first_low AS f USING (stay_id)
),

-- The latest result drawn in the `max_age` before t and stored by t.
known AS (
    SELECT g.circuit_id, g.pred_time,
           arg_max(p.valuenum, p.charttime) AS known_value,
           max(p.charttime) AS known_drawn_at
    FROM grid AS g
    JOIN phos AS p
      ON p.subject_id = g.subject_id
     AND p.storetime <= g.pred_time
     AND p.charttime <= g.pred_time
     AND p.charttime >= g.pred_time - getvariable('max_age')
    GROUP BY g.circuit_id, g.pred_time
),

repletion AS (
    SELECT subject_id, starttime
    FROM inputevents
    WHERE list_contains(getvariable('repletion_itemids'), itemid)
    UNION ALL
    SELECT subject_id, starttime
    FROM prescriptions
    WHERE list_contains(getvariable('oral_repletion_drugs'), lower(drug))
      AND list_contains(getvariable('oral_repletion_routes'), route)
      AND starttime IS NOT NULL
),

-- The first draw and the first repletion dose after t.
next_draw AS (
    SELECT g.*, d.charttime AS next_drawn_at
    FROM grid AS g
    ASOF LEFT JOIN phos AS d
      ON d.subject_id = g.subject_id AND d.charttime > g.pred_time
),

next_dose AS (
    SELECT a.*, r.starttime AS next_repletion_at
    FROM next_draw AS a
    ASOF LEFT JOIN repletion AS r
      ON r.subject_id = a.subject_id AND r.starttime > a.pred_time
),

flagged AS (
    SELECT
        a.*, k.known_value, k.known_drawn_at, adm.deathtime,
        a.pred_time + getvariable('horizon') AS window_end,
        CASE
            WHEN a.first_low_at <= a.pred_time THEN 'already_low'
            WHEN k.known_value IS NULL THEN 'no_known_value'
            WHEN k.known_value < getvariable('threshold') THEN 'known_low'
        END AS not_scored_reason
    FROM next_dose AS a
    LEFT JOIN known AS k USING (circuit_id, pred_time)
    LEFT JOIN admissions AS adm ON adm.hadm_id = a.hadm_id
),

censoring AS (
    SELECT
        *,
        CASE
            WHEN not_scored_reason IS NOT NULL THEN NULL
            WHEN next_repletion_at <= window_end
             AND (first_low_at IS NULL OR next_repletion_at < first_low_at) THEN 'repletion'
            WHEN first_low_at <= window_end THEN NULL
            WHEN deathtime > pred_time AND deathtime <= window_end THEN 'competing_risk'
            WHEN next_drawn_at IS NULL OR next_drawn_at > window_end THEN 'unmeasured'
        END AS censor_reason
    FROM flagged
)

SELECT
    circuit_id, subject_id, stay_id, pred_time,
    known_value, known_drawn_at, first_low_at,
    not_scored_reason,
    not_scored_reason IS NULL AS scored,
    CASE
        WHEN not_scored_reason IS NOT NULL OR censor_reason IS NOT NULL THEN NULL
        ELSE coalesce(first_low_at <= window_end, false)
    END AS label,
    censor_reason
FROM censoring
ORDER BY circuit_id, pred_time;
