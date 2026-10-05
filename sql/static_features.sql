-- static_features: the static feature group (Part 7, eighth bullet) for
-- every circuit, from data available at CRRT start.
--
-- Decision in docs/decisions.md (2026-10-05, "Static features").
-- Every column is defined in docs/data_dictionary.md.
--
-- Rows: one per circuit of circuit_failure_labels (circuit_id); join on
-- circuit_id. Every value is the stay's at CRRT start, the start of its
-- first included circuit (crrt_cohort's CRRT start), so the circuits of a
-- stay share them. A value counts only if it was charted and stored by
-- CRRT start, the earliest prediction time of the stay, so it is known at
-- every prediction time.
--
-- age_years from crrt_cohort; sex is patients.gender.
--
-- Body size (chartevents, `weight_items`, `height_items`): the earliest
-- measurement charted in the stay, among those stored by CRRT start and
-- inside their bound. Values are converted to kg and cm first; values of
-- one charttime are averaged and available at the latest storetime. bmi is
-- weight_kg / height in metres squared, when both are known.
--
-- admission_type (admissions) and service (services, the admission's
-- curr_service at its latest transfertime at or before CRRT start) are
-- mapped to the groups of `admission_type_groups` and `service_groups`.
-- A value with no group is null.
--
-- Scores, from the mimic-code concepts that crrt.concepts builds on
-- availability times:
--   sofa_no_cv: mimiciv_derived.sofa at the stay's last hour ending at or
--     before CRRT start, the sum of its 24 h respiration, coagulation,
--     liver, CNS and renal scores. The cardiovascular score is left out.
--   sepsis3: the stay's mimiciv_derived.sepsis3 row has its antibiotic,
--     culture and SOFA times all at or before CRRT start. False otherwise.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.features. Expects crrt_circuits, crrt_cohort,
-- circuit_failure_labels, patients, admissions, services, chartevents,
-- mimiciv_derived.sofa and mimiciv_derived.sepsis3.

CREATE OR REPLACE TABLE static_features AS
WITH weight_items AS (
    SELECT unnest(getvariable('weight_items'), recursive := true)
),

height_items AS (
    SELECT unnest(getvariable('height_items'), recursive := true)
),

admission_type_groups AS (
    SELECT unnest(getvariable('admission_type_groups'), recursive := true)
),

service_groups AS (
    SELECT unnest(getvariable('service_groups'), recursive := true)
),

circ AS (
    SELECT c.circuit_id, c.subject_id, c.hadm_id, c.stay_id
    FROM crrt_circuits AS c
    WHERE c.circuit_id IN (SELECT circuit_id FROM circuit_failure_labels)
),

-- CRRT start: the stay's first included circuit.
anchor AS (
    SELECT c.stay_id, c.hadm_id, min(c.circuit_start) AS crrt_start
    FROM crrt_circuits AS c
    JOIN crrt_cohort AS k USING (circuit_id)
    WHERE k.included
      AND c.stay_id IN (SELECT stay_id FROM circ)
    GROUP BY c.stay_id, c.hadm_id
),

-- Bounded measurements of the stay, one per charttime, in kg or cm.
weights AS (
    SELECT
        x.stay_id, x.charttime,
        avg(x.valuenum * i.to_kg) AS value,
        max(greatest(x.charttime, x.storetime)) AS available_at
    FROM chartevents AS x
    JOIN weight_items AS i ON i.itemid = x.itemid
    WHERE list_contains(getvariable('weight_itemids'), x.itemid)
      AND x.stay_id IN (SELECT stay_id FROM anchor)
      AND x.valuenum BETWEEN i.low AND i.high
    GROUP BY x.stay_id, x.charttime
),

heights AS (
    SELECT
        x.stay_id, x.charttime,
        avg(x.valuenum * i.to_cm) AS value,
        max(greatest(x.charttime, x.storetime)) AS available_at
    FROM chartevents AS x
    JOIN height_items AS i ON i.itemid = x.itemid
    WHERE list_contains(getvariable('height_itemids'), x.itemid)
      AND x.stay_id IN (SELECT stay_id FROM anchor)
      AND x.valuenum BETWEEN i.low AND i.high
    GROUP BY x.stay_id, x.charttime
),

body AS (
    SELECT
        a.stay_id,
        (SELECT arg_min(w.value, w.charttime) FROM weights AS w
         WHERE w.stay_id = a.stay_id AND w.available_at <= a.crrt_start) AS weight_kg,
        (SELECT arg_min(h.value, h.charttime) FROM heights AS h
         WHERE h.stay_id = a.stay_id AND h.available_at <= a.crrt_start) AS height_cm
    FROM anchor AS a
),

service AS (
    SELECT a.stay_id, arg_max(s.curr_service, s.transfertime) AS curr_service
    FROM anchor AS a
    JOIN services AS s
      ON s.hadm_id = a.hadm_id
     AND s.transfertime <= a.crrt_start
    GROUP BY a.stay_id
),

sofa AS (
    SELECT
        a.stay_id,
        arg_max(s.respiration_24hours + s.coagulation_24hours + s.liver_24hours
                + s.cns_24hours + s.renal_24hours, s.endtime) AS sofa_no_cv
    FROM anchor AS a
    JOIN mimiciv_derived.sofa AS s
      ON s.stay_id = a.stay_id
     AND s.endtime <= a.crrt_start
    GROUP BY a.stay_id
),

sepsis AS (
    SELECT
        a.stay_id,
        bool_or(s.sepsis3 AND greatest(s.antibiotic_time, s.culture_time, s.sofa_time)
                <= a.crrt_start) AS sepsis3
    FROM anchor AS a
    JOIN mimiciv_derived.sepsis3 AS s USING (stay_id)
    GROUP BY a.stay_id
)

SELECT
    c.circuit_id,
    k.age_years,
    p.gender AS sex,
    b.weight_kg,
    b.height_cm,
    b.weight_kg / ((b.height_cm / getvariable('cm_per_m'))
                   * (b.height_cm / getvariable('cm_per_m'))) AS bmi,
    ag.grp AS admission_type,
    sg.grp AS service,
    so.sofa_no_cv,
    coalesce(se.sepsis3, false) AS sepsis3
FROM circ AS c
JOIN crrt_cohort AS k USING (circuit_id)
JOIN patients AS p ON p.subject_id = c.subject_id
JOIN admissions AS adm ON adm.hadm_id = c.hadm_id
LEFT JOIN body AS b ON b.stay_id = c.stay_id
LEFT JOIN service AS sv ON sv.stay_id = c.stay_id
LEFT JOIN admission_type_groups AS ag ON ag.value = adm.admission_type
LEFT JOIN service_groups AS sg ON sg.value = sv.curr_service
LEFT JOIN sofa AS so ON so.stay_id = c.stay_id
LEFT JOIN sepsis AS se ON se.stay_id = c.stay_id
ORDER BY c.circuit_id;
