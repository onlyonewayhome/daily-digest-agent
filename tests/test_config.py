from pathlib import Path

import pytest

from daily_digest_agent.config import AppConfig, load_config
from daily_digest_agent.exceptions import ConfigurationError


def test_valid_example_config_loads():
    assert load_config(Path("config/example.yaml")).digest.search_window_hours == 36


def test_invalid_provider_rejected(valid_config):
    valid_config["models"]["writer"]["provider"] = "invalid"
    with pytest.raises(ValueError):
        AppConfig.model_validate(valid_config)


def test_invalid_importance_rejected(valid_config):
    valid_config["filters"]["minimum_importance"] = 6
    with pytest.raises(ValueError):
        AppConfig.model_validate(valid_config)


def test_missing_required_fields_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("digest: {}")
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_budget_safety_buffer_must_be_less_than_cap(valid_config):
    valid_config["budget"]["monthly_safety_buffer_usd"] = 3.0
    with pytest.raises(ValueError):
        AppConfig.model_validate(valid_config)
