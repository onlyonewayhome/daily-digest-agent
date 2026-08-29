import sys
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import HttpUrl

from daily_digest_agent.config import AppConfig
from daily_digest_agent.exceptions import ProviderOutputError
from daily_digest_agent.models import SourceRecord

google = sys.modules.setdefault("google", ModuleType("google"))
genai = ModuleType("google.genai")
genai.Client = object
genai.types = SimpleNamespace(
    GenerateContentConfig=lambda **kwargs: kwargs,
    Tool=lambda **kwargs: kwargs,
    GoogleSearch=lambda: object(),
)
google.genai = genai
sys.modules["google.genai"] = genai

from daily_digest_agent.discovery.gemini import GeminiDiscoveryProvider, _matching_sources  # noqa: E402


def provider(valid_config, response):
    value = object.__new__(GeminiDiscoveryProvider)
    value.config = AppConfig.model_validate(valid_config)
    value.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: response))
    return value


def test_malformed_discovery_payload_is_clean_provider_error(valid_config):
    response = SimpleNamespace(text='{"stories":[{"title":"missing url"}]}', usage_metadata=None, candidates=[])
    value = provider(valid_config, response)
    with pytest.raises(ProviderOutputError, match="invalid structured output"):
        value.discover(value.config.search_missions[0])


def test_matching_sources_accepts_exact_canonical_match():
    grounded = SourceRecord(title="Grounded story", url="https://example.com/story")

    result = _matching_sources(HttpUrl("https://example.com/story?utm_source=google"), [grounded])

    assert len(result) == 1
    assert result[0].url == grounded.url


def test_matching_sources_returns_empty_when_no_source_matches():
    grounded = [
        SourceRecord(title="Story B", url="https://example.com/story-b"),
        SourceRecord(title="Story C", url="https://another.com/story-c"),
    ]

    assert _matching_sources(HttpUrl("https://example.com/story-a"), grounded) == []


def test_grounding_sources_are_extracted_and_matched_conservatively(valid_config):
    web = SimpleNamespace(uri="https://source.example/report", title="Grounded report")
    metadata = SimpleNamespace(grounding_chunks=[SimpleNamespace(web=web)])
    response = SimpleNamespace(
        text='{"stories":[{"title":"Story","url":"https://source.example/report?utm_source=google"}]}',
        usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=3),
        candidates=[SimpleNamespace(grounding_metadata=metadata)],
    )
    value = provider(valid_config, response)
    result = value.discover(value.config.search_missions[0])
    assert result.token_usage.input_tokens == 12
    assert str(result.stories[0].grounding_sources[0].url) == "https://source.example/report"


def test_unmatched_grounding_sources_are_not_associated(valid_config):
    web = SimpleNamespace(uri="https://source.example/report", title="Grounded report")
    metadata = SimpleNamespace(grounding_chunks=[SimpleNamespace(web=web)])
    response = SimpleNamespace(
        text='{"stories":[{"title":"Story","url":"https://model.example/story"}]}',
        usage_metadata=None,
        candidates=[SimpleNamespace(grounding_metadata=metadata)],
    )

    value = provider(valid_config, response)
    result = value.discover(value.config.search_missions[0])

    assert result.stories[0].grounding_sources == []