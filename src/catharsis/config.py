"""Configuration loading for Claude Catharsis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from catharsis.paths import CONFIG_PATH

DEFAULT_CONFIG: dict[str, Any] = {
    "lookback_days": 7,
    "token_ceiling_pct": 5.0,
    "max_analysis_sessions": 20,
    "excluded_projects": [],
    "excluded_sessions": [],
    "instruction_budget_lines": 200,
    "top_n_patterns": 5,
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config from YAML, falling back to defaults."""
    config = dict(DEFAULT_CONFIG)
    p = path or CONFIG_PATH
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            config.update(user_config)
        except Exception:
            pass
    return config
