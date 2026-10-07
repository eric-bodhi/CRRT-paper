-- missingness_features: the missingness group (Part 7, ninth bullet) for
-- every prediction row: whether, and how often, each signal was measured,
-- from data available at the prediction time.
--
-- Decision in docs/decisions.md (2026-10-07, "Missingness features").
-- Every column is defined in docs/data_dictionary.md.
--
-- Rows: one per circuit_failure_labels row (circuit_id, pred_time), scored
-- or not, the same grid as machine_features.
--
-- Presence flags: one <name>_measured per <name>_hours_since_last column of
-- the five time-varying groups, true when that column is not null. That is
-- when the group has a value for <name> at t, under the group's own rules
-- (window, lookback, storetime, bound); the flag adds no rule of its own.
-- Read from the built tables, so it follows them if they change.
--
-- Draw counts (labevents, `labs`): every item of the lab groups,
-- calcium_labs and hemodynamic_labs, under the lab groups' rules. A result
-- counts at t if charttime <= t, storetime <= t, charttime >= t -
-- `lab_lookback`, and it is inside its bound; results of one item at one
-- charttime are one draw, available at the latest storetime. So
-- <name>_<lookback>h_n is the number of results <name>_last chose from: 0
-- exactly when <name>_measured is false.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.features. Expects crrt_circuits, circuit_failure_labels, labevents,
-- machine_features, anticoag_features, lab_features, access_features and
-- hemodynamic_features.

CREATE OR REPLACE TABLE missingness_features AS
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
        max(greatest(l.charttime, l.storetime)) AS available_at
    FROM labevents AS l
    JOIN labitems AS b ON b.itemid = l.itemid
    WHERE list_contains(getvariable('lab_itemids'), l.itemid)
      AND l.subject_id IN (SELECT subject_id FROM circ)
      AND l.valuenum BETWEEN b.low AND b.high
    GROUP BY ALL
),

draws AS (
    SELECT
        g.circuit_id, g.pred_time,
        b.name || '_' || getvariable('lab_lookback_hours') || 'h' AS key,
        count(v.charttime) AS n
    FROM grid AS g
    JOIN circ AS c USING (circuit_id)
    CROSS JOIN labitems AS b
    LEFT JOIN labs AS v
      ON v.subject_id = c.subject_id
     AND v.name = b.name
     AND v.charttime BETWEEN g.pred_time - getvariable('lab_lookback') AND g.pred_time
     AND v.available_at <= g.pred_time
    GROUP BY ALL
),

measured AS (
    SELECT
        circuit_id, pred_time,
        COLUMNS('^(.*)_hours_since_last$') IS NOT NULL AS '\1_measured'
    FROM machine_features
    JOIN anticoag_features USING (circuit_id, pred_time)
    JOIN lab_features USING (circuit_id, pred_time)
    JOIN access_features USING (circuit_id, pred_time)
    JOIN hemodynamic_features USING (circuit_id, pred_time)
)

SELECT m.*, d.* EXCLUDE (circuit_id, pred_time)
FROM measured AS m
JOIN (PIVOT draws ON key USING first(n) AS n GROUP BY circuit_id, pred_time) AS d
  USING (circuit_id, pred_time)
ORDER BY m.circuit_id, m.pred_time;
