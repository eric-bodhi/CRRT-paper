-- crrt_cohort: every crrt_circuits row, with the cohort rules applied.
--
-- Plan Parts 4.1, 4.2 and 4.6; decisions in docs/decisions.md (2026-10-02,
-- "Cohort rules" and "Chronic dialysis flag"). Every column is defined in
-- docs/data_dictionary.md.
--
-- No row is dropped. Each exclusion is a flag, and `exclusion_reason` names
-- the first rule a circuit fails, in STROBE order, so the flow diagram
-- (Part 4.6) is a count over this table. Downstream stages read
-- `WHERE included`.
--
-- Exclusions, in order:
--   1. under_min_age: age at ICU admission below `min_age_years`.
--   2. under_min_duration: circuit shorter than `min_duration_hours`.
-- Part 4.2 also lists comfort measures only before CRRT start. It is not
-- applied: it would remove fewer than 10 circuits, and see decisions.md.
--
-- Chronic dialysis is a flag, not an exclusion (cohort.esrd_handling_*).
-- Only evidence from before CRRT counts in the primary flag. CRRT start is
-- the stay's first circuit of at least `min_duration_hours`: shorter
-- circuits are mostly documentation artifacts.
--
-- Parameters are DuckDB variables, set from config/config.yaml by
-- crrt.cohort. Expects crrt_circuits, icustays, patients, admissions,
-- diagnoses_icd, chartevents and datetimeevents.

CREATE OR REPLACE TABLE crrt_cohort AS
WITH circ AS (
    SELECT
        c.circuit_id, c.subject_id, c.hadm_id, c.stay_id, c.circuit_start,
        c.duration_hours,
        -- MIMIC-IV shifts dates per patient. anchor_age is the age in
        -- anchor_year, so this is age in the year of ICU admission (the
        -- mimic-code `age` concept).
        p.anchor_age + (year(i.intime) - p.anchor_year) AS age_years
    FROM crrt_circuits AS c
    JOIN icustays AS i USING (stay_id)
    JOIN patients AS p ON p.subject_id = c.subject_id
),

crrt_start AS (
    SELECT stay_id, hadm_id, min(circuit_start) AS first_circuit_start
    FROM circ
    WHERE duration_hours >= getvariable('min_duration_hours')
    GROUP BY ALL
),

-- ── Chronic dialysis evidence ─────────────────────────────────────────────
admission_history AS (
    SELECT DISTINCT stay_id
    FROM chartevents
    WHERE itemid = getvariable('admission_history_itemid')
      AND valuenum = getvariable('admission_history_value')
),

last_dialysis AS (
    SELECT DISTINCT d.stay_id
    FROM datetimeevents AS d
    JOIN crrt_start AS s USING (stay_id)
    WHERE d.itemid = getvariable('last_dialysis_itemid')
      AND d.value < s.first_circuit_start
),

tunneled_catheter AS (
    SELECT DISTINCT x.stay_id
    FROM chartevents AS x
    JOIN crrt_start AS s USING (stay_id)
    WHERE list_contains(getvariable('tunneled_catheter'), x.itemid::VARCHAR || '=' || x.value)
      AND x.charttime < s.first_circuit_start
),

dialysis_codes AS (
    SELECT DISTINCT hadm_id
    FROM diagnoses_icd
    WHERE list_contains(getvariable('chronic_dialysis_icd_codes'), icd_code)
),

prior_admission_icd AS (
    SELECT DISTINCT s.stay_id
    FROM crrt_start AS s
    JOIN admissions AS a0 ON a0.hadm_id = s.hadm_id
    JOIN admissions AS a1
      ON a1.subject_id = a0.subject_id AND a1.admittime < a0.admittime
    JOIN dialysis_codes AS k ON k.hadm_id = a1.hadm_id
),

dialysis_flags AS (
    SELECT
        s.stay_id,
        s.stay_id IN (SELECT stay_id FROM admission_history) AS src_admission_history,
        s.stay_id IN (SELECT stay_id FROM last_dialysis) AS src_last_dialysis,
        s.stay_id IN (SELECT stay_id FROM tunneled_catheter) AS src_tunneled_catheter,
        s.stay_id IN (SELECT stay_id FROM prior_admission_icd) AS src_prior_admission_icd,
        s.hadm_id IN (SELECT hadm_id FROM dialysis_codes) AS src_same_admission_icd
    FROM crrt_start AS s
),

flagged AS (
    SELECT
        circ.circuit_id, circ.subject_id, circ.hadm_id, circ.stay_id, circ.age_years,
        circ.age_years >= getvariable('min_age_years') AS adult,
        circ.duration_hours >= getvariable('min_duration_hours') AS meets_min_duration,
        coalesce(f.src_admission_history, false) AS src_admission_history,
        coalesce(f.src_last_dialysis, false) AS src_last_dialysis,
        coalesce(f.src_tunneled_catheter, false) AS src_tunneled_catheter,
        coalesce(f.src_prior_admission_icd, false) AS src_prior_admission_icd,
        coalesce(f.src_same_admission_icd, false) AS src_same_admission_icd
    FROM circ
    LEFT JOIN dialysis_flags AS f USING (stay_id)
),

dialysis AS (
    SELECT
        *,
        src_admission_history OR src_last_dialysis OR src_tunneled_catheter
            OR src_prior_admission_icd AS pre_crrt_evidence
    FROM flagged
)

SELECT
    circuit_id, subject_id, hadm_id, stay_id, age_years,
    adult, meets_min_duration,
    src_admission_history, src_last_dialysis, src_tunneled_catheter,
    src_prior_admission_icd, src_same_admission_icd,
    pre_crrt_evidence
        OR (src_same_admission_icd AND getvariable('same_admission_icd_primary'))
        AS chronic_dialysis,
    pre_crrt_evidence
        OR (src_same_admission_icd AND getvariable('same_admission_icd_sensitivity'))
        AS chronic_dialysis_sensitivity,
    CASE
        WHEN NOT adult THEN 'under_min_age'
        WHEN NOT meets_min_duration THEN 'under_min_duration'
    END AS exclusion_reason,
    exclusion_reason IS NULL AS included
FROM dialysis
ORDER BY circuit_id;
