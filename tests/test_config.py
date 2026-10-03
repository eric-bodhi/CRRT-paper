"""Guards on config/config.yaml, the single source of truth for thresholds.

Plan Part 2.4 forbids magic numbers in code, which only works if the config
actually parses and actually contains the parameters the pipeline will reach
for. These tests fail loudly if a key is renamed or dropped.
"""

from pathlib import Path

import pytest
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.yaml"

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
    "outcomes.circuit_failure.adjudication_sample_size",
    "outcomes.circuit_failure.adjudication_min_kappa",
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
    "outcomes.hypophosphatemia.repletion_itemids",
    "outcomes.citrate_accumulation.total_to_ionized_calcium_ratio",
    "features.window_hours",
    "features.min_points_for_trend",
    "evaluation.alert_budget_alerts",
    "evaluation.alert_budget_hours",
    "paths.mimic_dir",
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


def test_warmup_and_blanking_fit_inside_the_horizon(config):
    """Warm-up and blanking must leave a scorable window (Parts 6.1-6.3)."""
    prediction = config["prediction"]
    assert prediction["warmup_hours"] > 0
    assert 0 < prediction["blanking_minutes"] < prediction["horizon_hours"] * 60
