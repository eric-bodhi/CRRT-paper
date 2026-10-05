-- access_features: the vascular access feature group (Part 7, sixth bullet)
-- for every prediction row, from data available at the prediction time.
--
-- Decision in docs/decisions.md (2026-10-04, "Access features"). Every
-- column is defined in docs/data_dictionary.md.
--
-- Rows: one per circuit_failure_labels row (circuit_id, pred_time), scored
-- or not, the same grid as machine_features.
--
-- Both items are charted on the dialysis catheter's rows of the ICU
-- flowsheet, about once a shift. They describe the catheter, not the
-- filter, so they are the stay's: a value counts at t if charttime <= t and
-- storetime <= t, however long before circuit_start, and the latest
-- charttime wins.
--
--   catheter_type (chartevents, Text): the value harmonised by
--   `catheter_types` to tunneled / temporary. A value not listed is skipped.
--   catheter_age_days (datetimeevents, a date): whole days from the
--   insertion date to the date of pred_time. An insertion date after the
--   date it was charted on is skipped.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.features. Expects crrt_circuits, circuit_failure_labels, chartevents
-- and datetimeevents.

CREATE OR REPLACE TABLE access_features AS
WITH catheter_types AS (
    SELECT unnest(getvariable('catheter_types'), recursive := true)
),

grid AS (
    SELECT l.circuit_id, l.pred_time
    FROM circuit_failure_labels AS l
),

circ AS (
    SELECT c.circuit_id, c.stay_id
    FROM crrt_circuits AS c
    WHERE c.circuit_id IN (SELECT circuit_id FROM grid)
),

types AS (
    SELECT x.stay_id, x.charttime, x.storetime, t.type
    FROM chartevents AS x
    JOIN catheter_types AS t ON t.itemid = x.itemid AND t.value = x.value
    WHERE list_contains(getvariable('catheter_type_itemids'), x.itemid)
      AND x.stay_id IN (SELECT stay_id FROM circ)
),

insertions AS (
    SELECT d.stay_id, d.charttime, d.storetime, d.value::DATE AS inserted_on
    FROM datetimeevents AS d
    WHERE d.itemid = getvariable('insertion_date_itemid')
      AND d.stay_id IN (SELECT stay_id FROM circ)
      AND d.value::DATE <= d.charttime::DATE
),

type_last AS (
    SELECT g.circuit_id, g.pred_time,
           arg_max(t.type, t.charttime) AS type, max(t.charttime) AS charttime
    FROM grid AS g
    JOIN circ AS c USING (circuit_id)
    JOIN types AS t
      ON t.stay_id = c.stay_id
     AND t.charttime <= g.pred_time
     AND t.storetime <= g.pred_time
    GROUP BY ALL
),

insertion_last AS (
    SELECT g.circuit_id, g.pred_time,
           arg_max(i.inserted_on, i.charttime) AS inserted_on, max(i.charttime) AS charttime
    FROM grid AS g
    JOIN circ AS c USING (circuit_id)
    JOIN insertions AS i
      ON i.stay_id = c.stay_id
     AND i.charttime <= g.pred_time
     AND i.storetime <= g.pred_time
    GROUP BY ALL
)

SELECT
    g.circuit_id, g.pred_time,
    tl.type AS catheter_type_last,
    epoch(g.pred_time - tl.charttime) / epoch(INTERVAL '1 hour') AS catheter_type_hours_since_last,
    date_diff('day', il.inserted_on, g.pred_time::DATE) AS catheter_age_days,
    epoch(g.pred_time - il.charttime) / epoch(INTERVAL '1 hour')
        AS catheter_insertion_date_hours_since_last
FROM grid AS g
LEFT JOIN type_last AS tl USING (circuit_id, pred_time)
LEFT JOIN insertion_last AS il USING (circuit_id, pred_time)
ORDER BY g.circuit_id, g.pred_time;
