import sys
from types import ModuleType, SimpleNamespace

import pytest

from daily_digest_agent.config import AppConfig
from daily_digest_agent.exceptions import ProviderOutputError

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

from daily_digest_agent.discovery.gemini import GeminiDiscoveryProvider  # noqa: E402


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


def test_grounding_sources_are_extracted_and_preferred(valid_config):
    web = SimpleNamespace(uri="https://source.example/report", title="Grounded report")
    metadata = SimpleNamespace(grounding_chunks=[SimpleNamespace(web=web)])
    response = SimpleNamespace(
        text='{"stories":[{"title":"Story","url":"https://model.example/story"}]}',
        usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=3),
        candidates=[SimpleNamespace(grounding_metadata=metadata)],
    )
    value = provider(valid_config, response)
    result = value.discover(value.config.search_missions[0])
    assert result.token_usage.input_tokens == 12
    assert str(result.stories[0].grounding_sources[0].url) == "https://source.example/report"