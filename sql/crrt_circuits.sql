-- crrt_circuits: one row per CRRT circuit (filter), with how it ended.
--
-- Plan Parts 4.3, 4.4 and 5.1; derivation and evidence in
-- docs/feasibility.md §2.2-2.3. Every column is defined in
-- docs/data_dictionary.md.
--
-- A circuit is one filter. It is built in three steps:
--
--   1. Segments. Machine charting (blood flow or any raw circuit pressure)
--      is cut wherever two consecutive charttimes are more than
--      `segment_gap` apart.
--   2. Pieces. A segment is cut again at every New Filter charted at least
--      `new_filter_min_after_start` past the segment start. A piece runs from
--      its start to its last machine charttime.
--   3. Circuits. Consecutive pieces of a stay are stitched onto the same
--      filter unless the later one starts a new filter: it is the stay's
--      first, it has a New Filter at its start, the piece before it ended
--      `Clotted` or with a documented reason, or the gap from the piece
--      before is longer than `max_downtime`.
--
-- The termination class reads only documentation (System Integrity, the
-- reason item, death, ICU discharge) and circuit age. It never reads a
-- pressure: the label is validated against pressure (feasibility §2.4), and
-- folding pressure into it would grade a pressure-based model on its own
-- inputs.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.circuits. Itemids are INTEGER lists or scalars; every window is an
-- INTERVAL. Expects tables/views chartevents, icustays and admissions.

CREATE OR REPLACE TABLE crrt_circuits AS
WITH machine AS (
    SELECT DISTINCT stay_id, subject_id, charttime
    FROM chartevents
    WHERE list_contains(getvariable('machine_itemids'), itemid)
      AND valuenum IS NOT NULL
),

-- 1. Segments of continuous machine charting.
machine_segmented AS (
    SELECT
        *,
        sum(new_segment::INTEGER) OVER (
            PARTITION BY stay_id ORDER BY charttime
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS segment_no
    FROM (
        SELECT
            *,
            coalesce(
                charttime - lag(charttime) OVER (PARTITION BY stay_id ORDER BY charttime)
                    > getvariable('segment_gap'),
                true
            ) AS new_segment
        FROM machine
    )
),

segments AS (
    SELECT stay_id, subject_id, segment_no,
           min(charttime) AS segment_start, max(charttime) AS segment_end
    FROM machine_segmented
    GROUP BY ALL
),

integrity AS (
    SELECT stay_id, charttime, value
    FROM chartevents
    WHERE itemid = getvariable('system_integrity_itemid') AND value IS NOT NULL
),

reasons AS (
    SELECT stay_id, charttime, value
    FROM chartevents
    WHERE itemid = getvariable('filter_change_reason_itemid') AND value IS NOT NULL
),

-- 2. Piece starts: every segment start, and every New Filter inside a
--    segment far enough past its start.
starts AS (
    SELECT stay_id, segment_no, segment_start AS piece_start, 'segment_start' AS kind
    FROM segments
    UNION
    SELECT s.stay_id, s.segment_no, i.charttime, 'new_filter'
    FROM integrity i
    JOIN segments s
      ON s.stay_id = i.stay_id
     AND i.charttime > s.segment_start + getvariable('new_filter_min_after_start')
     AND i.charttime <= s.segment_end
    WHERE i.value = 'New Filter'
),

-- Each machine charttime belongs to the latest piece start at or before it,
-- within its segment. A New Filter followed by no machine charting before
-- the next one gets no rows and so produces no piece: that filter never ran.
pieces AS (
    SELECT m.stay_id, m.subject_id, s.piece_start, s.kind,
           max(m.charttime) AS piece_end
    FROM machine_segmented m
    ASOF JOIN starts s
      ON m.stay_id = s.stay_id
     AND m.segment_no = s.segment_no
     AND m.charttime >= s.piece_start
    GROUP BY ALL
),

-- Documentation around each piece's start and end.
pieces_documented AS (
    SELECT
        p.*,
        p.kind = 'new_filter' OR EXISTS (
            SELECT * FROM integrity i
            WHERE i.stay_id = p.stay_id AND i.value = 'New Filter'
              AND i.charttime BETWEEN p.piece_start - getvariable('new_filter_at_start_before')
                                  AND p.piece_start + getvariable('new_filter_at_start_after')
        ) AS starts_new_filter,
        EXISTS (
            SELECT * FROM integrity i
            WHERE i.stay_id = p.stay_id AND i.value = 'Clotted'
              AND i.charttime BETWEEN p.piece_end - getvariable('clotted_at_end_before')
                                  AND p.piece_end + getvariable('clotted_at_end_after')
        ) AS end_clotted,
        EXISTS (
            SELECT * FROM integrity i
            WHERE i.stay_id = p.stay_id AND i.value = 'Clots Increasing'
              AND i.charttime BETWEEN p.piece_end - getvariable('clots_increasing_at_end_before')
                                  AND p.piece_end + getvariable('clots_increasing_at_end_after')
        ) AS end_clots_increasing,
        EXISTS (
            SELECT * FROM integrity i
            WHERE i.stay_id = p.stay_id AND i.value IN ('Discontinued', 'Recirculating')
              AND i.charttime BETWEEN p.piece_end - getvariable('stopped_at_end_before')
                                  AND p.piece_end + getvariable('stopped_at_end_after')
        ) AS end_stopped,
        (
            SELECT max(r.value) FROM reasons r
            WHERE r.stay_id = p.stay_id
              AND r.charttime BETWEEN p.piece_end - getvariable('reason_at_end_before')
                                  AND p.piece_end + getvariable('reason_at_end_after')
        ) AS end_reason,
        EXISTS (
            SELECT * FROM icustays u JOIN admissions a ON a.hadm_id = u.hadm_id
            WHERE u.stay_id = p.stay_id
              AND a.deathtime BETWEEN p.piece_end - getvariable('death_after_end_before')
                                  AND p.piece_end + getvariable('death_after_end_after')
        ) AS end_death,
        EXISTS (
            SELECT * FROM icustays u
            WHERE u.stay_id = p.stay_id
              AND u.outtime BETWEEN p.piece_end - getvariable('icu_discharge_after_end_before')
                                AND p.piece_end + getvariable('icu_discharge_after_end_after')
        ) AS end_icu_discharge
    FROM pieces p
),

-- 3. Why (if at all) each piece starts a new circuit. NULL = same filter.
pieces_stitched AS (
    SELECT
        *,
        CASE
            WHEN prev_end IS NULL THEN 'first_of_stay'
            WHEN starts_new_filter THEN 'new_filter'
            WHEN prev_clotted THEN 'after_clotted'
            WHEN prev_reason IS NOT NULL THEN 'after_reason'
            WHEN piece_start - prev_end > getvariable('max_downtime') THEN 'after_long_gap'
        END AS start_reason
    FROM (
        SELECT
            *,
            lag(piece_end) OVER w AS prev_end,
            lag(end_clotted) OVER w AS prev_clotted,
            lag(end_reason) OVER w AS prev_reason
        FROM pieces_documented
        WINDOW w AS (PARTITION BY stay_id ORDER BY piece_start)
    )
),

pieces_numbered AS (
    SELECT
        *,
        count(start_reason) OVER (
            PARTITION BY stay_id ORDER BY piece_start
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS circuit_no
    FROM pieces_stitched
),

-- A circuit starts as its first piece starts and ends as its last piece ends.
circuits AS (
    SELECT
        stay_id,
        subject_id,
        circuit_no,
        min(piece_start) AS circuit_start,
        max(piece_end) AS circuit_end,
        count(*) AS n_pieces,
        sum(epoch(piece_end - piece_start)) AS running_seconds,
        arg_min(start_reason, piece_start) AS start_reason,
        arg_min(starts_new_filter, piece_start) AS starts_new_filter,
        arg_max(end_clotted, piece_start) AS end_clotted,
        arg_max(end_clots_increasing, piece_start) AS end_clots_increasing,
        arg_max(end_stopped, piece_start) AS end_stopped,
        arg_max(end_reason, piece_start) AS end_reason,
        arg_max(end_death, piece_start) AS end_death,
        arg_max(end_icu_discharge, piece_start) AS end_icu_discharge
    FROM pieces_numbered
    GROUP BY stay_id, subject_id, circuit_no
)

SELECT
    row_number() OVER (ORDER BY c.stay_id, c.circuit_no) AS circuit_id,
    c.subject_id,
    u.hadm_id,
    c.stay_id,
    c.circuit_no,
    c.circuit_start,
    c.circuit_end,
    epoch(c.circuit_end - c.circuit_start) / epoch(INTERVAL '1 hour') AS duration_hours,
    c.running_seconds / epoch(INTERVAL '1 hour') AS running_hours,
    c.n_pieces,
    c.start_reason,
    c.starts_new_filter,
    c.end_clotted,
    c.end_clots_increasing,
    c.end_stopped,
    c.end_reason,
    c.end_death,
    c.end_icu_discharge,
    c.circuit_no = max(c.circuit_no) OVER (PARTITION BY c.stay_id) AS last_of_stay,
    -- Hierarchical: the first matching rule wins (feasibility §2.3).
    CASE
        WHEN c.end_clotted OR c.end_reason = 'Clotted' THEN 'clotted'
        WHEN c.end_clots_increasing THEN 'clots_increasing'
        WHEN c.end_death THEN 'death'
        WHEN c.circuit_end - c.circuit_start >= getvariable('reached_limit') THEN 'reached_limit'
        WHEN c.end_reason IN ('Procedure', 'Line changed') THEN 'procedure_or_line_change'
        WHEN c.end_icu_discharge THEN 'icu_discharge'
        WHEN c.circuit_no = max(c.circuit_no) OVER (PARTITION BY c.stay_id) THEN 'crrt_ended'
        WHEN c.end_stopped THEN 'stopped_then_restarted'
        ELSE 'undocumented'
    END AS termination_class
FROM circuits c
JOIN icustays u ON u.stay_id = c.stay_id
ORDER BY circuit_id;
