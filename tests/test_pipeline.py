from pathlib import Path

import pytest

from daily_digest_agent.config import AppConfig
from daily_digest_agent.exceptions import DiscoveryHealthError, ProviderBudgetExceeded, ProviderOutputError
from daily_digest_agent.models import DiscoveryResult, SourceRecord, StoryClassification, TokenUsage
from daily_digest_agent.pipeline import DigestPipeline
from daily_digest_agent.storage.sqlite import SQLiteStateStore
from tests.fakes import FakeClassifier, FakeDelivery, FakeDiscoveryProvider, FakeWriter, candidate


def pipeline(tmp_path: Path, valid_config, *, results=None, failures=None,
             writer=None, delivery=None, classifier=None, discovery=None):
    valid_config["storage"]["sqlite_path"] = str(tmp_path / "state.db")
    config = AppConfig.model_validate(valid_config)
    store = SQLiteStateStore(config.storage.sqlite_path)
    return DigestPipeline(config, store, discovery or FakeDiscoveryProvider(results, failures),
                          classifier or FakeClassifier(), writer or FakeWriter(),
                          delivery or FakeDelivery()), store


def test_successful_normal_run(tmp_path, valid_config):
    value, _ = pipeline(tmp_path, valid_config, results={"general": [candidate()]})
    result = value.run(dry_run=True)
    assert result.status == "success" and result.accepted_stories == 1


def test_quiet_day(tmp_path, valid_config):
    writer = FakeWriter()
    value, _ = pipeline(tmp_path, valid_config, writer=writer)
    result = value.run(dry_run=True)
    assert "Quiet day" in result.digest.plain_text
    assert writer.calls == 0


def test_degraded_and_total_discovery_failure(tmp_path, valid_config):
    value, _ = pipeline(tmp_path, valid_config, failures={"general"})
    with pytest.raises(DiscoveryHealthError):
        value.run()
    value, _ = pipeline(tmp_path / "other", valid_config, failures={"general", "business"})
    with pytest.raises(DiscoveryHealthError):
        value.run()


def test_writer_failure_is_recorded(tmp_path, valid_config):
    value, store = pipeline(
        tmp_path, valid_config, results={"general": [candidate()]}, writer=FakeWriter(fail=True)
    )
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


def test_persisted_story_is_not_reclassified_on_second_run(tmp_path, valid_config):
    item = candidate(url="https://example.com/story?utm_source=google", title="Persistent Story")
    assert item.grounding_sources == []
    classifier = FakeClassifier()
    writer = FakeWriter()
    pipeline_one, store_one = pipeline(
        tmp_path, valid_config, results={"general": [item]}, classifier=classifier, writer=writer,
    )

    first = pipeline_one.run(dry_run=True)

    assert first.accepted_stories == 1
    assert classifier.calls == 1
    assert writer.calls == 1
    story = store_one.get_recent_stories(first.digest.generated_at.replace(year=2000))[0]
    assert story.canonical_url == "https://example.com/story"

    pipeline_two, store_two = pipeline(
        tmp_path, valid_config, results={"general": [item]}, classifier=classifier, writer=writer,
    )
    assert store_one.path == store_two.path == tmp_path / "state.db"

    second = pipeline_two.run(dry_run=True, force=True)

    assert second.accepted_stories == 0
    assert second.digest is not None
    assert "Quiet day" in second.digest.plain_text
    assert classifier.calls == 1
    assert writer.calls == 1


def test_grounded_canonical_story_is_not_reclassified_on_second_run(tmp_path, valid_config):
    item = candidate(
        url="https://news.example.com/article?utm_source=google",
        title="Grounded Persistent Story",
    )
    item.grounding_sources = [
        SourceRecord(title="Grounded Persistent Story", url="https://news.example.com/article")
    ]
    classifier = FakeClassifier()
    pipeline_one, store_one = pipeline(
        tmp_path, valid_config, results={"general": [item]}, classifier=classifier,
    )

    first = pipeline_one.run(dry_run=True)

    assert first.accepted_stories == 1
    assert classifier.calls == 1
    story = store_one.get_recent_stories(first.digest.generated_at.replace(year=2000))[0]
    assert story.canonical_url == "https://news.example.com/article"

    pipeline_two, store_two = pipeline(
        tmp_path, valid_config, results={"general": [item]}, classifier=classifier,
    )
    assert store_one.path == store_two.path == tmp_path / "state.db"

    second = pipeline_two.run(dry_run=True, force=True)

    assert second.accepted_stories == 0
    assert classifier.calls == 1


def test_new_story_on_second_run_is_still_classified(tmp_path, valid_config):
    story_a = candidate(url="https://example.com/a", title="Story A")
    story_b = candidate(url="https://example.com/b", title="Story B")
    classifier = FakeClassifier()
    writer = FakeWriter()
    pipeline_one, store_one = pipeline(
        tmp_path, valid_config, results={"general": [story_a]}, classifier=classifier, writer=writer,
    )

    first = pipeline_one.run(dry_run=True)

    assert first.accepted_stories == 1
    assert classifier.calls == 1

    pipeline_two, store_two = pipeline(
        tmp_path, valid_config, results={"general": [story_a, story_b]}, classifier=classifier, writer=writer,
    )
    assert store_one.path == store_two.path == tmp_path / "state.db"

    second = pipeline_two.run(dry_run=True, force=True)

    assert second.accepted_stories == 1
    assert classifier.calls == 2
    assert "Story B" in second.digest.plain_text
    assert "Story A" not in second.digest.plain_text


def test_empty_discovery_records_request_usage_and_cost(tmp_path, valid_config):
    discovery = FakeDiscoveryProvider(
        {"general": DiscoveryResult(stories=[], token_usage=TokenUsage(input_tokens=100, output_tokens=20))}
    )
    value, store = pipeline(tmp_path, valid_config, discovery=discovery)
    value.run(dry_run=True)
    with store._connect() as db:
        row = db.execute(
            "SELECT input_tokens,output_tokens,estimated_cost_usd FROM usage ORDER BY id LIMIT 1"
        ).fetchone()
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 20
    assert row["estimated_cost_usd"] > 0


def test_unknown_pricing_blocks_provider_execution(tmp_path, valid_config):
    valid_config["pricing"]["google"] = {}
    discovery = FakeDiscoveryProvider()
    value, _ = pipeline(tmp_path, valid_config, discovery=discovery)
    with pytest.raises(Exception, match="No pricing is configured"):
        value.run(dry_run=True)
    assert discovery.calls == 0


def test_pipeline_uses_candidate_url_when_grounding_sources_are_empty(tmp_path, valid_config):
    item = candidate(url="https://example.com/story?utm_source=google")
    value, store = pipeline(tmp_path, valid_config, results={"general": [item]})

    result = value.run(dry_run=True)

    story = store.get_recent_stories(result.digest.generated_at.replace(year=2000))[0]
    assert story.canonical_url == "https://example.com/story"
    assert len(story.sources) == 1
    assert str(story.sources[0].url) == str(item.url)


def test_pipeline_uses_matched_grounding_source_as_authoritative(tmp_path, valid_config):
    item = candidate(url="https://news.example.com/article?utm_source=x")
    item.grounding_sources = [SourceRecord(title=item.title, url="https://news.example.com/article")]
    value, store = pipeline(tmp_path, valid_config, results={"general": [item]})

    result = value.run(dry_run=True)

    story = store.get_recent_stories(result.digest.generated_at.replace(year=2000))[0]
    assert story.canonical_url == "https://news.example.com/article"
    assert story.sources == item.grounding_sources


def test_unknown_category_rejects_candidate_and_run_continues(tmp_path, valid_config):
    invalid = StoryClassification(
        relevant=True, relevance_score=0.9, importance=4, category="not-configured",
        story_key="invalid-story", reasoning_summary="Relevant", factual_summary="Fact",
        token_usage=TokenUsage(input_tokens=30, output_tokens=10),
    )
    valid = StoryClassification(
        relevant=True, relevance_score=0.9, importance=4, category="major_news",
        story_key="valid-story", reasoning_summary="Relevant", factual_summary="Fact",
        token_usage=TokenUsage(input_tokens=25, output_tokens=8),
    )
    candidate_a = candidate(url="https://example.com/a", title="Candidate A")
    candidate_b = candidate(url="https://example.com/b", title="Candidate B")
    classifier = FakeClassifier(results={str(candidate_a.url): invalid, str(candidate_b.url): valid})
    value, store = pipeline(
        tmp_path, valid_config, results={"general": [candidate_a, candidate_b]}, classifier=classifier,
    )

    result = value.run(dry_run=True)

    assert result.status == "success"
    assert result.accepted_stories == 1
    assert result.classification.attempted == 2
    assert result.classification.successful == 1
    assert result.classification.rejected == 1
    assert result.classification.invalid_output == 1
    assert "Candidate B" in result.digest.plain_text
    assert "Candidate A" not in result.digest.plain_text
    with store._connect() as db:
        classification_usage = db.execute(
            "SELECT input_tokens,output_tokens FROM usage WHERE model=? ORDER BY id",
            (value.config.models.classification.model,),
        ).fetchall()
    assert [(row["input_tokens"], row["output_tokens"]) for row in classification_usage] == [(30, 10), (25, 8)]


def test_classifier_provider_output_error_records_usage_and_continues(tmp_path, valid_config):
    candidate_a = candidate(url="https://example.com/a", title="Candidate A")
    candidate_b = candidate(url="https://example.com/b", title="Candidate B")
    classifier = FakeClassifier(results={str(candidate_a.url): ProviderOutputError("malformed classifier response")})
    value, store = pipeline(
        tmp_path, valid_config, results={"general": [candidate_a, candidate_b]}, classifier=classifier,
    )

    result = value.run(dry_run=True)

    assert result.status == "success"
    assert result.accepted_stories == 1
    assert result.classification.invalid_output == 1
    with store._connect() as db:
        usage_rows = db.execute(
            "SELECT input_tokens,output_tokens FROM usage WHERE model=? ORDER BY id",
            (value.config.models.classification.model,),
        ).fetchall()
    assert len(usage_rows) == 2
    assert (usage_rows[0]["input_tokens"], usage_rows[0]["output_tokens"]) == (0, 0)


def test_classifier_provider_failure_is_not_treated_as_candidate_rejection(tmp_path, valid_config):
    value, store = pipeline(
        tmp_path, valid_config, results={"general": [candidate()]}, classifier=FakeClassifier(fail=True),
    )

    with pytest.raises(RuntimeError, match="classifier failed"):
        value.run(dry_run=True)

    assert store.get_last_run()["status"] == "failed"
