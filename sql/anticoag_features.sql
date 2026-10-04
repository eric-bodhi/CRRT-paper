-- anticoag_features: the anticoagulation feature group (Part 7, third
-- bullet) for every prediction row, from data available at the prediction
-- time.
--
-- Decision in docs/decisions.md (2026-10-04, "Anticoagulation features").
-- Every column is defined in docs/data_dictionary.md.
--
-- Rows: one per circuit_failure_labels row (circuit_id, pred_time), scored
-- or not, the same grid as machine_features.
--
-- Hourly signals (chartevents, `anticoag_items`): citrate_rate and
-- heparin_dose. A value counts at prediction time t under the machine
-- features' rules: charttime <= t, storetime <= t, charttime >=
-- circuit_start, and inside its plausibility bound (never clipped). For
-- each and each window w in `windows`, over [t - w, t]: <signal>_<w>h_n,
-- _mean, _min, _max, _slope (per hour) and _var, with slope and variance
-- null below `min_points_for_trend`. Over the longest window:
-- <signal>_last and <signal>_hours_since_last.
--
-- Calcium (labevents, `calcium_labs`): ionized_calcium and total_calcium,
-- the patient's results, so not limited to the circuit. A result counts at
-- t if charttime <= t, storetime <= t, charttime >= t - the longest window,
-- and it is inside its bound. Results of one item at one charttime are
-- averaged and available at the latest storetime. Each total calcium is
-- paired with the ionized calcium drawn nearest to it within
-- `calcium_pair`, ties to the earlier draw; calcium_ratio is total (in
-- mmol/L) / ionized, timed at the total's charttime and available once both
-- are. Each of the three gives <name>_last and <name>_hours_since_last.
--
-- anticoag_class, from citrate_rate_last and heparin_dose_last:
-- citrate_heparin, citrate, heparin (each > 0), else none if citrate_rate_last
-- is 0, else null.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.features. Expects crrt_circuits, circuit_failure_labels, chartevents
-- and labevents.

CREATE OR REPLACE TABLE anticoag_features AS
WITH items AS (
    SELECT unnest(getvariable('anticoag_items'), recursive := true)
),

labitems AS (
    SELECT unnest(getvariable('calcium_labs'), recursive := true)
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

-- Bounded hourly values, at the circuit they were charted in.
vals AS (
    SELECT
        c.circuit_id, x.charttime,
        greatest(x.charttime, x.storetime) AS available_at,
        i.name, x.valuenum AS value
    FROM chartevents AS x
    JOIN items AS i ON i.itemid = x.itemid
    JOIN circ AS c
      ON c.stay_id = x.stay_id
     AND x.charttime BETWEEN c.circuit_start AND c.circuit_end
    WHERE list_contains(getvariable('anticoag_itemids'), x.itemid)
      AND x.valuenum BETWEEN i.low AND i.high
),

-- Each value, at every prediction time on the circuit's grid that can see
-- it, as in machine_features.
seen AS (
    SELECT v.*, c.circuit_start + getvariable('step') * k AS pred_time
    FROM vals AS v
    JOIN circ AS c USING (circuit_id)
    CROSS JOIN longest AS lw,
    LATERAL unnest(generate_series(
        ceil(epoch(v.available_at - c.circuit_start) / epoch(getvariable('step')))::BIGINT,
        floor(epoch(v.charttime + lw.span - c.circuit_start) / epoch(getvariable('step')))::BIGINT
    )) AS t(k)
    WHERE c.circuit_start + getvariable('step') * k <= c.circuit_end
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

filled AS (
    SELECT
        g.circuit_id, g.pred_time,
        i.name || '_' || w.hours || 'h' AS key,
        coalesce(st.n, 0) AS n,
        st.mean, st.min, st.max,
        CASE WHEN st.n >= getvariable('min_points_for_trend') THEN st.slope END AS slope,
        CASE WHEN st.n >= getvariable('min_points_for_trend') THEN st.var END AS var
    FROM grid AS g
    CROSS JOIN items AS i
    CROSS JOIN windows AS w
    LEFT JOIN stats AS st
      ON st.circuit_id = g.circuit_id AND st.pred_time = g.pred_time
     AND st.name = i.name AND st.hours = w.hours
),

-- Bounded lab results of the circuits' patients, one per item and charttime.
labs AS (
    SELECT
        l.subject_id, b.name, l.charttime,
        avg(l.valuenum) AS value,
        max(greatest(l.charttime, l.storetime)) AS available_at
    FROM labevents AS l
    JOIN labitems AS b ON b.itemid = l.itemid
    WHERE l.subject_id IN (SELECT subject_id FROM circ)
      AND l.valuenum BETWEEN b.low AND b.high
    GROUP BY ALL
),

pairs AS (
    SELECT
        t.subject_id, 'calcium_ratio' AS name, t.charttime,
        t.value / getvariable('calcium_mg_dl_per_mmol_l') / i.value AS value,
        greatest(t.available_at, i.available_at) AS available_at
    FROM labs AS t
    JOIN labs AS i
      ON i.subject_id = t.subject_id
     AND i.name = 'ionized_calcium'
     AND i.charttime BETWEEN t.charttime - getvariable('calcium_pair')
                         AND t.charttime + getvariable('calcium_pair')
    WHERE t.name = 'total_calcium'
    QUALIFY row_number() OVER (
        PARTITION BY t.subject_id, t.charttime
        ORDER BY abs(epoch(i.charttime - t.charttime)), i.charttime) = 1
),

lab_vals AS (
    SELECT subject_id, name, charttime, value, available_at FROM labs
    UNION ALL
    SELECT subject_id, name, charttime, value, available_at FROM pairs
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
        g.circuit_id, g.pred_time, v.name,
        arg_max(v.value, v.charttime),
        epoch(g.pred_time - max(v.charttime)) / epoch(INTERVAL '1 hour')
    FROM grid AS g
    JOIN circ AS c USING (circuit_id)
    CROSS JOIN longest AS lw
    JOIN lab_vals AS v
      ON v.subject_id = c.subject_id
     AND v.charttime BETWEEN g.pred_time - lw.span AND g.pred_time
     AND v.available_at <= g.pred_time
    GROUP BY g.circuit_id, g.pred_time, v.name
),

names AS (
    SELECT name FROM items
    UNION ALL
    SELECT name FROM labitems
    UNION ALL
    SELECT 'calcium_ratio'
),

latest_filled AS (
    SELECT g.circuit_id, g.pred_time, nm.name AS key, la.last, la.hours_since_last
    FROM grid AS g
    CROSS JOIN names AS nm
    LEFT JOIN latest AS la
      ON la.circuit_id = g.circuit_id AND la.pred_time = g.pred_time AND la.name = nm.name
)

SELECT
    g.circuit_id, g.pred_time,
    CASE
        WHEN lf.citrate_rate_last > 0 AND lf.heparin_dose_last > 0 THEN 'citrate_heparin'
        WHEN lf.citrate_rate_last > 0 THEN 'citrate'
        WHEN lf.heparin_dose_last > 0 THEN 'heparin'
        WHEN lf.citrate_rate_last = 0 THEN 'none'
    END AS anticoag_class,
    lf.* EXCLUDE (circuit_id, pred_time),
    wf.* EXCLUDE (circuit_id, pred_time)
FROM grid AS g
JOIN (PIVOT latest_filled ON key
      USING first(last) AS last, first(hours_since_last) AS hours_since_last
      GROUP BY circuit_id, pred_time) AS lf USING (circuit_id, pred_time)
JOIN (PIVOT filled ON key
      USING first(n) AS n, first(mean) AS mean, first(min) AS min, first(max) AS max,
            first(slope) AS slope, first(var) AS var
      GROUP BY circuit_id, pred_time) AS wf USING (circuit_id, pred_time)
ORDER BY g.circuit_id, g.pred_time;
