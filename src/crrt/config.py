"""Access to config/config.yaml.

Plan Part 2.4 makes that file the only place a threshold may live. Every
module reads its numbers through here so there is exactly one definition of
"the repo root" and exactly one parse of the config.
"""

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"


def load() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text())


def path(config: dict[str, Any], key: str) -> Path:
    """Resolve one entry of the config `paths:` block against the repo root."""
    return REPO_ROOT / config["paths"][key]
