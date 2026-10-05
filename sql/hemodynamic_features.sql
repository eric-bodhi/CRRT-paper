-- hemodynamic_features: the hemodynamics feature group (Part 7, fifth
-- bullet) for every prediction row, from data available at the prediction
-- time.
--
-- Decision in docs/decisions.md (2026-10-04, "Hemodynamic features").
-- Every column is defined in docs/data_dictionary.md.
--
-- Rows: one per circuit_failure_labels row (circuit_id, pred_time), scored
-- or not, the same grid as machine_features.
--
-- Vitals (chartevents, `vital_items`): map, heart_rate, temperature. The
-- stay's values, so not limited to the circuit: a value counts at t if
-- charttime <= t, storetime <= t, and it is inside its item's bound (never
-- clipped). Each is put in its signal's unit, (valuenum - shift) / scale,
-- and values of one signal at one charttime are averaged and available at
-- the latest storetime.
--
-- The norepinephrine-equivalent dose (Part 7) is not here: its
-- inputevents rows are missing for half the stays of 2020-22 and are stored
-- around the end of each bag. See the decision.
--
-- For each vital and each window w in `windows`, over the values
-- charted in [t - w, t]: <signal>_<w>h_n, _mean, _min, _max, _slope (per
-- hour) and _var, with slope and variance null below
-- `min_points_for_trend`. Over the longest window: <signal>_last and
-- <signal>_hours_since_last.
--
-- Lactate (labevents, `hemodynamic_labs`): under lab_features' rules,
-- <name>_last, <name>_hours_since_last, <name>_delta and
-- <name>_delta_hours.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.features. Expects crrt_circuits, circuit_failure_labels,
-- chartevents and labevents.

CREATE OR REPLACE TABLE hemodynamic_features AS
WITH vitalitems AS (
    SELECT unnest(getvariable('vital_items'), recursive := true)
),

labitems AS (
    SELECT unnest(getvariable('hemodynamic_labs'), recursive := true)
),

windows AS (
    SELECT unnest(getvariable('windows'), recursive := true)
),

longest AS (
    SELECT max(span) AS span FROM windows
),

grid AS (
    SELECT l.circuit_id, l.pred_time
    FROM circuit_failure_labels AS l
),

circ AS (
    SELECT c.circuit_id, c.subject_id, c.stay_id, c.circuit_start, c.circuit_end
    FROM crrt_circuits AS c
    WHERE c.circuit_id IN (SELECT circuit_id FROM grid)
),

-- Bounded vitals of the circuits' stays that a window can reach, in the
-- signal's unit, one per signal and charttime.
vitals AS (
    SELECT
        c.circuit_id, x.charttime, i.name,
        avg((x.valuenum - i.shift) / i.scale) AS value,
        max(greatest(x.charttime, x.storetime)) AS available_at
    FROM chartevents AS x
    JOIN vitalitems AS i ON i.itemid = x.itemid
    CROSS JOIN longest AS lw
    JOIN circ AS c
      ON c.stay_id = x.stay_id
     AND x.charttime BETWEEN c.circuit_start - lw.span AND c.circuit_end
    WHERE list_contains(getvariable('vital_itemids'), x.itemid)
      AND x.valuenum BETWEEN i.low AND i.high
    GROUP BY ALL
),

signals AS (
    SELECT DISTINCT name FROM vitalitems
),

-- Each value, at every prediction time on the circuit's grid that can see
-- it, as in machine_features. A value from before circuit_start is seen
-- from the first prediction time.
seen AS (
    SELECT v.*, c.circuit_start + getvariable('step') * k AS pred_time
    FROM vitals AS v
    JOIN circ AS c USING (circuit_id)
    CROSS JOIN longest AS lw,
    LATERAL unnest(generate_series(
        ceil(epoch(v.available_at - c.circuit_start) / epoch(getvariable('step')))::BIGINT,
        floor(epoch(v.charttime + lw.span - c.circuit_start) / epoch(getvariable('step')))::BIGINT
    )) AS t(k)
    WHERE c.circuit_start + getvariable('step') * k BETWEEN c.circuit_start AND c.circuit_end
),

stats AS (
    SELECT
        s.circuit_id, s.pred_time, s.name, w.hours,
        count(*) AS n,
        avg(s.value) AS mean,
        min(s.value) AS min,
        max(s.value) AS max,
        regr_slope(s.value, epoch(s.charttime - s.pred_time) / epoch(INTERVAL '1 hour')) AS slope,
        var_samp(s.value) AS var
    FROM seen AS s
    JOIN windows AS w ON s.charttime >= s.pred_time - w.span
    GROUP BY ALL
),

-- Every row x signal x window, so that every column exists and n is 0
-- rather than null when nothing was charted.
filled AS (
    SELECT
        g.circuit_id, g.pred_time,
        sg.name || '_' || w.hours || 'h' AS key,
        coalesce(st.n, 0) AS n,
        st.mean, st.min, st.max,
        CASE WHEN st.n >= getvariable('min_points_for_trend') THEN st.slope END AS slope,
        CASE WHEN st.n >= getvariable('min_points_for_trend') THEN st.var END AS var
    FROM grid AS g
    CROSS JOIN signals AS sg
    CROSS JOIN windows AS w
    LEFT JOIN stats AS st
      ON st.circuit_id = g.circuit_id AND st.pred_time = g.pred_time
     AND st.name = sg.name AND st.hours = w.hours
),

-- Bounded lab results of the circuits' patients, one per item and
-- charttime, as in lab_features.
labs AS (
    SELECT
        l.subject_id, b.name, l.charttime,
        avg(l.valuenum) AS value,
        max(greatest(l.charttime, l.storetime)) AS available_at
    FROM labevents AS l
    JOIN labitems AS b ON b.itemid = l.itemid
    WHERE list_contains(getvariable('hemodynamic_lab_itemids'), l.itemid)
      AND l.subject_id IN (SELECT subject_id FROM circ)
      AND l.valuenum BETWEEN b.low AND b.high
    GROUP BY ALL
),

-- The latest two lab results that count at each prediction time, newest
-- first.
lab_latest AS (
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

latest AS (
    SELECT
        circuit_id, pred_time, name,
        arg_max(value, charttime) AS last,
        epoch(pred_time - max(charttime)) / epoch(INTERVAL '1 hour') AS hours_since_last
    FROM seen
    GROUP BY circuit_id, pred_time, name
    UNION ALL
    SELECT
        circuit_id, pred_time, name,
        vals[1],
        epoch(pred_time - times[1]) / epoch(INTERVAL '1 hour')
    FROM lab_latest
),

names AS (
    SELECT name FROM signals
    UNION ALL
    SELECT name FROM labitems
),

latest_filled AS (
    SELECT g.circuit_id, g.pred_time, nm.name AS key, la.last, la.hours_since_last
    FROM grid AS g
    CROSS JOIN names AS nm
    LEFT JOIN latest AS la
      ON la.circuit_id = g.circuit_id AND la.pred_time = g.pred_time AND la.name = nm.name
),

delta_filled AS (
    SELECT
        g.circuit_id, g.pred_time, b.name AS key,
        ll.vals[1] - ll.vals[2] AS delta,
        epoch(ll.times[1] - ll.times[2]) / epoch(INTERVAL '1 hour') AS delta_hours
    FROM grid AS g
    CROSS JOIN labitems AS b
    LEFT JOIN lab_latest AS ll
      ON ll.circuit_id = g.circuit_id AND ll.pred_time = g.pred_time AND ll.name = b.name
)

SELECT
    g.circuit_id, g.pred_time,
    lf.* EXCLUDE (circuit_id, pred_time),
    df.* EXCLUDE (circuit_id, pred_time),
    wf.* EXCLUDE (circuit_id, pred_time)
FROM grid AS g
JOIN (PIVOT latest_filled ON key
      USING first(last) AS last, first(hours_since_last) AS hours_since_last
      GROUP BY circuit_id, pred_time) AS lf USING (circuit_id, pred_time)
JOIN (PIVOT delta_filled ON key
      USING first(delta) AS delta, first(delta_hours) AS delta_hours
      GROUP BY circuit_id, pred_time) AS df USING (circuit_id, pred_time)
JOIN (PIVOT filled ON key
      USING first(n) AS n, first(mean) AS mean, first(min) AS min, first(max) AS max,
            first(slope) AS slope, first(var) AS var
      GROUP BY circuit_id, pred_time) AS wf USING (circuit_id, pred_time)
ORDER BY g.circuit_id, g.pred_time;
