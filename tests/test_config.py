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
    "sessionization.gap_hours",
    "sessionization.gap_hours_sensitivity",
    "prediction.horizon_hours",
    "prediction.horizon_hours_sensitivity",
    "prediction.blanking_minutes",
    "prediction.warmup_hours",
    "outcomes.circuit_failure.scheduled_change_interval_hours",
    "outcomes.circuit_failure.adjudication_sample_size",
    "outcomes.circuit_failure.adjudication_min_kappa",
    "outcomes.hypophosphatemia.moderate_mg_dl",
    "outcomes.hypophosphatemia.severe_mg_dl",
    "outcomes.citrate_accumulation.total_to_ionized_calcium_ratio",
    "features.window_hours",
    "evaluation.alert_budget_alerts",
    "evaluation.alert_budget_hours",
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
