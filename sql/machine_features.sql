-- machine_features: the machine/circuit feature group (Part 7, first bullet)
-- for every prediction row, from data available at the prediction time.
--
-- Decision in docs/decisions.md (2026-10-03, "Machine features"). Every
-- column is defined in docs/data_dictionary.md.
--
-- Rows: one per circuit_failure_labels row (circuit_id, pred_time), scored
-- or not. hypophos_labels has the same grid, so both outcomes read this
-- table.
--
-- A charted value counts at prediction time t only if all of these hold
-- (Part 6.4):
--   - charttime <= t;
--   - storetime <= t. 15-19% of machine values are stored more than an hour
--     after their charttime, and 226457 Ultrafiltrate Output is stored a
--     median 75 min after it;
--   - charttime >= circuit_start. Values from an earlier filter never enter;
--   - its itemid is in `machine_items`, and its value is inside the item's
--     plausibility bound, or within `clip_margin` of it and then set to the
--     bound. Further out it is missing, not clipped.
--
-- Derived signals, at a charttime where every component is charted. Each is
-- available at the latest storetime among its components:
--   pressure_drop                 filter - return                        mmHg
--   tmp                           mean(filter, return) - effluent        mmHg
--   uf_rate                       pbp + replacement + fluid removal      ml/hr
--   pressure_drop_per_blood_flow  pressure_drop / blood_flow     mmHg/(ml/min)
--   tmp_per_uf_rate               tmp / uf_rate, null if uf_rate is 0  mmHg/(ml/hr)
-- The pressure formulas are the Prismaflex manual's. They use the bounded
-- raw pressures, so they fall inside the 229248 / 229247 bounds by
-- construction. They are not calibrated to the charted 229248 / 229247.
--
-- For each signal and each window w in `windows`, over the values charted
-- in [t - w, t]: <signal>_<w>h_n, _mean, _min, _max, _slope (per hour,
-- least squares on charttime) and _var (sample variance). Slope and
-- variance need at least `min_points_for_trend` values and are null with
-- fewer. n is 0, never null, when nothing was charted.
-- Over the longest window only: <signal>_last, the latest-charted value,
-- and <signal>_hours_since_last.
-- Plus crrt_mode_last (Text, latest-charted in the longest window) and
-- circuit_hours, the time since circuit_start.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.features. Expects crrt_circuits, circuit_failure_labels and
-- chartevents.

CREATE OR REPLACE TABLE machine_features AS
WITH items AS (
    SELECT unnest(getvariable('machine_items'), recursive := true)
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
    SELECT c.circuit_id, c.stay_id, c.circuit_start, c.circuit_end
    FROM crrt_circuits AS c
    WHERE c.circuit_id IN (SELECT circuit_id FROM grid)
),

-- Bounded raw values, at the circuit they were charted in.
raw AS (
    SELECT
        c.circuit_id, x.charttime,
        greatest(x.charttime, x.storetime) AS available_at,
        i.name,
        CASE
            WHEN x.valuenum BETWEEN i.low AND i.high THEN x.valuenum
            WHEN x.valuenum BETWEEN i.low - i.clip_margin AND i.low THEN i.low
            WHEN x.valuenum BETWEEN i.high AND i.high + i.clip_margin THEN i.high
        END AS value
    FROM chartevents AS x
    JOIN items AS i ON i.itemid = x.itemid
    JOIN circ AS c
      ON c.stay_id = x.stay_id
     AND x.charttime BETWEEN c.circuit_start AND c.circuit_end
    WHERE list_contains(getvariable('machine_itemids'), x.itemid)
      AND x.valuenum IS NOT NULL
),

-- One row per charttime, with each component and when it became available.
wide AS (
    SELECT
        circuit_id, charttime,
        max(value) FILTER (WHERE name = 'filter_pressure') AS f,
        max(available_at) FILTER (WHERE name = 'filter_pressure') AS f_at,
        max(value) FILTER (WHERE name = 'return_pressure') AS r,
        max(available_at) FILTER (WHERE name = 'return_pressure') AS r_at,
        max(value) FILTER (WHERE name = 'effluent_pressure') AS e,
        max(available_at) FILTER (WHERE name = 'effluent_pressure') AS e_at,
        max(value) FILTER (WHERE name = 'blood_flow') AS bf,
        max(available_at) FILTER (WHERE name = 'blood_flow') AS bf_at,
        max(value) FILTER (WHERE name = 'pbp_rate') AS pbp,
        max(available_at) FILTER (WHERE name = 'pbp_rate') AS pbp_at,
        max(value) FILTER (WHERE name = 'replacement_rate') AS rep,
        max(available_at) FILTER (WHERE name = 'replacement_rate') AS rep_at,
        max(value) FILTER (WHERE name = 'fluid_removal_rate') AS fr,
        max(available_at) FILTER (WHERE name = 'fluid_removal_rate') AS fr_at
    FROM raw
    WHERE value IS NOT NULL
    GROUP BY circuit_id, charttime
),

derived AS (
    SELECT circuit_id, charttime, 'pressure_drop' AS name,
           f - r AS value, greatest(f_at, r_at) AS available_at
    FROM wide WHERE f IS NOT NULL AND r IS NOT NULL
    UNION ALL
    SELECT circuit_id, charttime, 'tmp',
           list_avg([f, r]) - e, greatest(f_at, r_at, e_at)
    FROM wide WHERE f IS NOT NULL AND r IS NOT NULL AND e IS NOT NULL
    UNION ALL
    SELECT circuit_id, charttime, 'uf_rate',
           pbp + rep + fr, greatest(pbp_at, rep_at, fr_at)
    FROM wide WHERE pbp IS NOT NULL AND rep IS NOT NULL AND fr IS NOT NULL
    UNION ALL
    SELECT circuit_id, charttime, 'pressure_drop_per_blood_flow',
           (f - r) / bf, greatest(f_at, r_at, bf_at)
    FROM wide WHERE f IS NOT NULL AND r IS NOT NULL AND bf IS NOT NULL
    UNION ALL
    SELECT circuit_id, charttime, 'tmp_per_uf_rate',
           (list_avg([f, r]) - e) / nullif(pbp + rep + fr, 0),
           greatest(f_at, r_at, e_at, pbp_at, rep_at, fr_at)
    FROM wide
    WHERE f IS NOT NULL AND r IS NOT NULL AND e IS NOT NULL
      AND pbp IS NOT NULL AND rep IS NOT NULL AND fr IS NOT NULL
),

vals AS (
    SELECT circuit_id, charttime, available_at, name, value FROM raw WHERE value IS NOT NULL
    UNION ALL
    SELECT circuit_id, charttime, available_at, name, value FROM derived WHERE value IS NOT NULL
),

signals AS (
    SELECT name FROM items
    UNION ALL
    SELECT unnest(['pressure_drop', 'tmp', 'uf_rate',
                   'pressure_drop_per_blood_flow', 'tmp_per_uf_rate'])
),

-- Each value, at every prediction time on the circuit's grid that can see
-- it: from the first one at or after it became available to the last one
-- whose longest window still reaches back to it. The grid is
-- circuit_start + k * step, as in circuit_failure_labels.
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

latest AS (
    SELECT
        circuit_id, pred_time, name,
        arg_max(value, charttime) AS last,
        epoch(pred_time - max(charttime)) / epoch(INTERVAL '1 hour') AS hours_since_last
    FROM seen
    GROUP BY circuit_id, pred_time, name
),

latest_filled AS (
    SELECT g.circuit_id, g.pred_time, sg.name AS key, la.last, la.hours_since_last
    FROM grid AS g
    CROSS JOIN signals AS sg
    LEFT JOIN latest AS la
      ON la.circuit_id = g.circuit_id AND la.pred_time = g.pred_time AND la.name = sg.name
),

-- CRRT mode, Text: the latest-charted value in the longest window that is
-- available at the prediction time.
mode AS (
    SELECT g.circuit_id, g.pred_time, arg_max(x.value, x.charttime) AS crrt_mode_last
    FROM grid AS g
    JOIN circ AS c USING (circuit_id)
    CROSS JOIN longest AS lw
    JOIN chartevents AS x
      ON x.stay_id = c.stay_id
     AND x.itemid = getvariable('crrt_mode_itemid')
     AND x.value IS NOT NULL
     AND x.charttime BETWEEN greatest(c.circuit_start, g.pred_time - lw.span) AND g.pred_time
     AND x.storetime <= g.pred_time
    GROUP BY ALL
)

SELECT
    g.circuit_id, g.pred_time,
    epoch(g.pred_time - c.circuit_start) / epoch(INTERVAL '1 hour') AS circuit_hours,
    m.crrt_mode_last,
    lf.* EXCLUDE (circuit_id, pred_time),
    wf.* EXCLUDE (circuit_id, pred_time)
FROM grid AS g
JOIN circ AS c USING (circuit_id)
LEFT JOIN mode AS m USING (circuit_id, pred_time)
JOIN (PIVOT latest_filled ON key
      USING first(last) AS last, first(hours_since_last) AS hours_since_last
      GROUP BY circuit_id, pred_time) AS lf USING (circuit_id, pred_time)
JOIN (PIVOT filled ON key
      USING first(n) AS n, first(mean) AS mean, first(min) AS min, first(max) AS max,
            first(slope) AS slope, first(var) AS var
      GROUP BY circuit_id, pred_time) AS wf USING (circuit_id, pred_time)
ORDER BY g.circuit_id, g.pred_time;
