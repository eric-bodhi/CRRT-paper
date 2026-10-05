-- lab_features: the coagulation/hematology and chemistry feature groups
-- (Part 7, fourth and seventh bullets) for every prediction row, from data
-- available at the prediction time.
--
-- Decision in docs/decisions.md (2026-10-04, "Laboratory features").
-- Every column is defined in docs/data_dictionary.md.
--
-- Rows: one per circuit_failure_labels row (circuit_id, pred_time), scored
-- or not, the same grid as machine_features.
--
-- Labs (labevents, `labs`): the patient's results, so not limited to the
-- circuit, under the calcium labs' rules in anticoag_features. A result
-- counts at t if charttime <= t, storetime <= t, charttime >= t -
-- `lab_lookback`, and it is inside its bound. Results of one item at one
-- charttime are averaged and available at the latest storetime. Each lab
-- gives <name>_last and <name>_hours_since_last, and, from the latest two
-- results that count ([1] the last, [2] the one before it), <name>_delta
-- (last - previous) and <name>_delta_hours (hours between their draws).
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.features. Expects crrt_circuits, circuit_failure_labels and
-- labevents.

CREATE OR REPLACE TABLE lab_features AS
WITH labitems AS (
    SELECT unnest(getvariable('labs'), recursive := true)
),

grid AS (
    SELECT l.circuit_id, l.pred_time
    FROM circuit_failure_labels AS l
),

circ AS (
    SELECT c.circuit_id, c.subject_id
    FROM crrt_circuits AS c
    WHERE c.circuit_id IN (SELECT circuit_id FROM grid)
),

-- Bounded lab results of the circuits' patients, one per item and charttime.
labs AS (
    SELECT
        l.subject_id, b.name, l.charttime,
        avg(l.valuenum) AS value,
        max(greatest(l.charttime, l.storetime)) AS available_at
    FROM labevents AS l
    JOIN labitems AS b ON b.itemid = l.itemid
    WHERE list_contains(getvariable('lab_itemids'), l.itemid)
      AND l.subject_id IN (SELECT subject_id FROM circ)
      AND l.valuenum BETWEEN b.low AND b.high
    GROUP BY ALL
),

-- The latest two results that count at each prediction time, newest first.
latest AS (
    SELECT
        g.circuit_id, g.pred_time, v.name,
        arg_max(v.value, v.charttime, 2) AS vals,
        max(v.charttime, 2) AS times
    FROM grid AS g
    JOIN circ AS c USING (circuit_id)
    JOIN labs AS v
      ON v.subject_id = c.subject_id
     AND v.charttime BETWEEN g.pred_time - getvariable('lab_lookback') AND g.pred_time
     AND v.available_at <= g.pred_time
    GROUP BY g.circuit_id, g.pred_time, v.name
),

latest_filled AS (
    SELECT
        g.circuit_id, g.pred_time, b.name AS key,
        la.vals[1] AS last,
        epoch(g.pred_time - la.times[1]) / epoch(INTERVAL '1 hour') AS hours_since_last,
        la.vals[1] - la.vals[2] AS delta,
        epoch(la.times[1] - la.times[2]) / epoch(INTERVAL '1 hour') AS delta_hours
    FROM grid AS g
    CROSS JOIN labitems AS b
    LEFT JOIN latest AS la
      ON la.circuit_id = g.circuit_id AND la.pred_time = g.pred_time AND la.name = b.name
)

SELECT lf.*
FROM (PIVOT latest_filled ON key
      USING first(last) AS last, first(hours_since_last) AS hours_since_last,
            first(delta) AS delta, first(delta_hours) AS delta_hours
      GROUP BY circuit_id, pred_time) AS lf
ORDER BY lf.circuit_id, lf.pred_time;
