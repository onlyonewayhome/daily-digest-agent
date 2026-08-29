from pathlib import Path

import pytest

from daily_digest_agent.config import AppConfig
from daily_digest_agent.exceptions import DiscoveryHealthError, ProviderBudgetExceeded
from daily_digest_agent.pipeline import DigestPipeline
from daily_digest_agent.storage.sqlite import SQLiteStateStore
from tests.fakes import FakeClassifier, FakeDelivery, FakeDiscoveryProvider, FakeWriter, candidate


def pipeline(tmp_path: Path, valid_config, *, results=None, failures=None,
             writer=None, delivery=None):
    valid_config["storage"]["sqlite_path"] = str(tmp_path / "state.db")
    config = AppConfig.model_validate(valid_config)
    store = SQLiteStateStore(config.storage.sqlite_path)
    return DigestPipeline(config, store, FakeDiscoveryProvider(results, failures),
                          FakeClassifier(), writer or FakeWriter(), delivery or FakeDelivery()), store


def test_successful_normal_run(tmp_path, valid_config):
    value, _ = pipeline(tmp_path, valid_config, results={"general": [candidate()]})
    result = value.run(dry_run=True)
    assert result.status == "success" and result.accepted_stories == 1


def test_quiet_day(tmp_path, valid_config):
    value, _ = pipeline(tmp_path, valid_config)
    result = value.run(dry_run=True)
    assert "Quiet day" in result.digest.plain_text


def test_degraded_and_total_discovery_failure(tmp_path, valid_config):
    value, _ = pipeline(tmp_path, valid_config, failures={"general"})
    with pytest.raises(DiscoveryHealthError):
        value.run()
    value, _ = pipeline(tmp_path / "other", valid_config, failures={"general", "business"})
    with pytest.raises(DiscoveryHealthError):
        value.run()


def test_writer_failure_is_recorded(tmp_path, valid_config):
    value, store = pipeline(tmp_path, valid_config, writer=FakeWriter(fail=True))
    with pytest.raises(RuntimeError):
        value.run()
    assert store.get_last_run()["status"] == "failed"


def test_delivery_failure_is_recorded(tmp_path, valid_config):
    value, store = pipeline(tmp_path, valid_config, delivery=FakeDelivery(fail=True))
    with pytest.raises(RuntimeError):
        value.run()
    assert store.get_last_run()["status"] == "failed"


def test_budget_exceeded(tmp_path, valid_config):
    valid_config["budget"]["gemini"]["max_calls_per_run"] = 2
    value, _ = pipeline(tmp_path, valid_config, results={"general": [candidate()]})
    with pytest.raises(ProviderBudgetExceeded):
        value.run()


def test_duplicate_suppression(tmp_path, valid_config):
    item = candidate()
    value, _ = pipeline(tmp_path, valid_config, results={"general": [item, item]})
    assert value.run(dry_run=True).accepted_stories == 1
