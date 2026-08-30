import json
from types import SimpleNamespace

import pytest

from daily_digest_agent.classification.gemini import GeminiClassifierProvider
from daily_digest_agent.config import AppConfig
from daily_digest_agent.exceptions import ProviderOutputError
from tests.fakes import candidate


def provider(valid_config, response):
    value = object.__new__(GeminiClassifierProvider)
    value.config = AppConfig.model_validate(valid_config)
    value.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: response))
    return value


def classification_payload(**overrides):
    payload = {
        "relevant": True,
        "relevance_score": 0.9,
        "importance": 4,
        "category": "major_news",
        "story_key": "example-development",
        "reasoning_summary": "Relevant",
        "factual_summary": "A documented development occurred.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_valid_classification_extracts_token_usage(valid_config):
    response = SimpleNamespace(
        text=classification_payload(),
        usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=3),
    )

    result = provider(valid_config, response).classify(candidate())

    assert result.category == "major_news"
    assert result.token_usage.input_tokens == 12
    assert result.token_usage.output_tokens == 3


@pytest.mark.parametrize("text", ["not json", '{"relevant": true}'])
def test_malformed_classification_is_clean_provider_error(valid_config, text):
    response = SimpleNamespace(text=text, usage_metadata=None)

    with pytest.raises(ProviderOutputError, match="invalid structured output"):
        provider(valid_config, response).classify(candidate())


def test_unknown_category_is_clean_provider_error(valid_config):
    response = SimpleNamespace(text=classification_payload(category="unknown"), usage_metadata=None)

    with pytest.raises(ProviderOutputError, match="unknown category"):
        provider(valid_config, response).classify(candidate())