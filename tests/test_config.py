"""Guards on config/config.yaml, the single source of truth for thresholds.

Plan Part 2.4 forbids magic numbers in code, which only works if the config
actually parses and actually contains the parameters the pipeline will reach
for. These tests fail loudly if a key is renamed or dropped.
"""

import re
from pathlib import Path

import pytest
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
ITEMID_REVIEW_PATH = CONFIG_PATH.with_name("itemid_review.yaml")

# Dotted paths every downstream stage depends on. Adding a threshold to the
# config does not require touching this list; removing or renaming one does.
REQUIRED_KEYS = [
    "reproducibility.random_seed",
    "reproducibility.grouping_key",
    "cohort.min_age_years",
    "cohort.min_session_duration_hours",
    "cohort.min_events_for_modeling",
    "cohort.esrd_handling_primary",
    "cohort.esrd_handling_sensitivity",
    "sessionization.gap_hours",
    "sessionization.gap_hours_sensitivity",
    "circuits.machine_itemids",
    "circuits.system_integrity_itemid",
    "circuits.filter_change_reason_itemid",
    "circuits.max_downtime_hours",
    "circuits.max_downtime_hours_sensitivity",
    "circuits.new_filter_min_hours_after_segment_start",
    "circuits.windows_hours",
    "circuits.reached_limit_hours",
    "reporting.small_cell_threshold",
    "prediction.step_hours",
    "prediction.horizon_hours",
    "prediction.horizon_hours_sensitivity",
    "prediction.blanking_minutes",
    "prediction.warmup_hours",
    "outcomes.circuit_failure.scheduled_change_interval_hours",
    "outcomes.circuit_failure.adjudication_strata",
    "outcomes.circuit_failure.adjudication_min_kappa",
    "outcomes.circuit_failure.adjudication_sample_sha256",
    "outcomes.circuit_failure.adjudication_practice_per_stratum",
    "outcomes.circuit_failure.adjudication_view_hours",
    "outcomes.circuit_failure.adjudication_verdicts",
    "outcomes.circuit_failure.adjudication_port",
    "outcomes.circuit_failure.adjudication_windows_python",
    "outcomes.circuit_failure.event_classes_primary",
    "outcomes.circuit_failure.event_classes_sensitivity",
    "outcomes.circuit_failure.competing_risk_classes",
    "outcomes.circuit_failure.unclear_classes",
    "outcomes.circuit_failure.unclear_handling_primary",
    "outcomes.circuit_failure.unclear_handling_sensitivity",
    "outcomes.hypophosphatemia.moderate_mg_dl",
    "outcomes.hypophosphatemia.severe_mg_dl",
    "outcomes.hypophosphatemia.sensitivity_mg_dl",
    "outcomes.hypophosphatemia.phosphate_itemid",
    "outcomes.hypophosphatemia.horizon_hours",
    "outcomes.hypophosphatemia.known_value_max_age_hours",
    "outcomes.hypophosphatemia.repletion_orders",
    "outcomes.hypophosphatemia.repletion_handling_primary",
    "outcomes.hypophosphatemia.repletion_handling_sensitivity",
    "outcomes.citrate_accumulation.total_to_ionized_calcium_ratio",
    "features.window_hours",
    "features.min_points_for_trend",
    "features.plausibility_bounds",
    "features.pressure_clip_margin_mmhg",
    "features.pressure_clip_itemids",
    "features.machine_signals",
    "features.crrt_mode_itemid",
    "features.anticoag_signals",
    "features.calcium_labs",
    "features.calcium_pair_minutes",
    "features.calcium_mg_dl_per_mmol_l",
    "features.lab_groups",
    "features.lab_lookback_hours",
    "evaluation.alert_budget_alerts",
    "evaluation.alert_budget_hours",
    "paths.mimic_dir",
    "paths.mimic_url",
    "paths.duckdb",
    "paths.parquet_dir",
    "itemid_inventory.seed_category",
    "itemid_inventory.label_patterns",
    "itemid_inventory.percentiles",
    "itemid_inventory.max_units_listed",
    "itemid_inventory.max_text_values_listed",
    "itemid_inventory.mimic_code_crrt_itemids",
    "itemid_inventory.crrt_procedure_itemids",
]


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load(CONFIG_PATH.read_text())


@pytest.mark.parametrize("dotted", REQUIRED_KEYS)
def test_required_key_present(config, dotted):
    node = config
    for part in dotted.split("."):
        assert part in node, f"missing config key: {dotted}"
        node = node[part]
    assert node is not None, f"config key is null: {dotted}"


def test_hypophosphatemia_severe_below_moderate(config):
    """Severe is a lower phosphate than moderate (Part 5.2: <1.0 vs <2.0)."""
    thresholds = config["outcomes"]["hypophosphatemia"]
    assert thresholds["severe_mg_dl"] < thresholds["moderate_mg_dl"]


def test_adjudication_strata_cover_every_labelled_class_once(config):
    """The strata partition every termination_class except the censored ones
    (decisions.md 2026-10-04, "Adjudication sample"). A class added to
    crrt_circuits.sql without a stratum would silently leave the frame."""
    cf = config["outcomes"]["circuit_failure"]
    sql = (Path(__file__).parents[1] / "sql" / "crrt_circuits.sql").read_text()
    end = sql.index("END AS termination_class")
    case = sql[sql.rindex("CASE", 0, end):end]
    every_class = set(re.findall(r"(?:THEN|ELSE) '(\w+)'", case))
    strata = [s["classes"] for s in cf["adjudication_strata"].values()]
    in_strata = [c for classes in strata for c in classes]
    assert len(in_strata) == len(set(in_strata))
    assert set(in_strata) == every_class - set(cf["competing_risk_classes"])
    assert all(s["circuits"] > 0 for s in cf["adjudication_strata"].values())


def test_warmup_and_blanking_fit_inside_the_horizon(config):
    """Warm-up and blanking must leave a scorable window (Parts 6.1-6.3)."""
    prediction = config["prediction"]
    assert prediction["warmup_hours"] > 0
    assert 0 < prediction["blanking_minutes"] < prediction["horizon_hours"] * 60


def test_plausibility_bounds_are_ordered_and_reviewed(config):
    """Each bound is [low, high] with low < high, on an itemid the hand
    review included (Part 2.3): a bound on an unreviewed item is a bound on
    a variable no feature may read. Labevents itemids are outside the review
    by design (labs come from labevents, not its chartevents copies); they
    are allowed only as a named calcium lab or a lab in a lab group."""
    reviewed = yaml.safe_load(ITEMID_REVIEW_PATH.read_text())["items"]
    features = config["features"]
    labs = set(features["calcium_labs"].values()) | {
        itemid for group in features["lab_groups"].values() for itemid in group.values()}
    for itemid, (low, high) in features["plausibility_bounds"].items():
        assert low < high, itemid
        assert itemid in labs or reviewed[itemid]["verdict"] == "include", itemid


@pytest.mark.parametrize("group", ["machine_signals", "anticoag_signals", "calcium_labs"])
def test_feature_signals_are_bounded(config, group):
    """Every feature signal is read through its plausibility bound (Part 7);
    an item without one would reach the features uncleaned."""
    features = config["features"]
    assert set(features[group].values()) <= set(features["plausibility_bounds"])


def test_lab_groups_are_bounded_and_named_once(config):
    """Every lab is read through its bound, and a name is one column pair of
    lab_features, so it may appear in only one group."""
    features = config["features"]
    groups = features["lab_groups"].values()
    names = [name for group in groups for name in group]
    assert len(names) == len(set(names))
    assert {itemid for group in groups for itemid in group.values()} <= set(
        features["plausibility_bounds"])


def test_clipped_pressures_are_bounded(config):
    features = config["features"]
    assert set(features["pressure_clip_itemids"]) <= set(features["plausibility_bounds"])
    assert features["pressure_clip_margin_mmhg"] > 0
