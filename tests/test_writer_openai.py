import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from daily_digest_agent.config import AppConfig
from daily_digest_agent.exceptions import ProviderOutputError
from daily_digest_agent.models import DigestContext, SourceRecord, Story
from daily_digest_agent.writers.openai import OpenAIDigestWriter


def writer(valid_config, output_text, input_tokens=11, output_tokens=7):
    value = object.__new__(OpenAIDigestWriter)
    value.config = AppConfig.model_validate(valid_config)
    response = SimpleNamespace(
        output_text=output_text,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )
    value.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
    return value


def story():
    now = datetime.now(UTC)
    return Story(
        canonical_url="https://example.com/story",
        title="Example story",
        first_seen_at=now,
        last_seen_at=now,
        relevance_score=0.9,
        importance=4,
        story_key="example-story",
        factual_summary="A documented development occurred.",
        sources=[SourceRecord(title="Example story", url="https://example.com/story")],
    )


def context():
    return DigestContext(
        digest_name="Example Daily",
        digest_date=date(2026, 8, 29),
        editorial_voice="Concise",
        categories=["Major News"],
    )


def test_valid_writer_output_extracts_usage(valid_config):
    payload = json.dumps({
        "subject": "Example Daily",
        "plain_text": "Read https://example.com/story",
        "html": '<p>Read <a href="https://example.com/story">the source</a>.</p>',
    })

    result = writer(valid_config, payload).generate_digest([story()], context())

    assert result.subject == "Example Daily"
    assert result.token_usage.input_tokens == 11
    assert result.token_usage.output_tokens == 7


@pytest.mark.parametrize("output_text", ["not json", '{"subject":"Missing fields"}'])
def test_malformed_writer_output_is_clean_provider_error(valid_config, output_text):
    with pytest.raises(ProviderOutputError, match="invalid structured output"):
        writer(valid_config, output_text).generate_digest([story()], context())


def test_writer_rejects_extra_fields(valid_config):
    payload = json.dumps({"subject": "Digest", "plain_text": "Body", "html": "<p>Body</p>", "extra": True})

    with pytest.raises(ProviderOutputError, match="invalid structured output"):
        writer(valid_config, payload).generate_digest([story()], context())


def test_writer_rejects_unverified_url(valid_config):
    payload = json.dumps({
        "subject": "Digest",
        "plain_text": "Read https://attacker.example/story",
        "html": '<a href="https://attacker.example/story">source</a>',
    })

    with pytest.raises(ProviderOutputError, match="outside the verified source set"):
        writer(valid_config, payload).generate_digest([story()], context())