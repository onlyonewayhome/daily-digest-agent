import os

from .config import AppConfig
from .delivery.base import DeliveryProvider
from .exceptions import ConfigurationError
from .pipeline import DigestPipeline
from .storage.base import StateStore


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigurationError(f"Required environment variable is not set: {name}")
    return value


def create_store(config: AppConfig) -> StateStore:
    if config.storage.provider == "sqlite":
        from .storage.sqlite import SQLiteStateStore
        return SQLiteStateStore(config.storage.sqlite_path)
    from .storage.d1 import D1StateStore
    return D1StateStore(
        required_env("CLOUDFLARE_ACCOUNT_ID"),
        required_env("D1_DATABASE_ID"),
        required_env("CLOUDFLARE_API_TOKEN"),
    )


def create_delivery(config: AppConfig) -> DeliveryProvider:
    from .delivery.console import ConsoleDeliveryProvider
    from .delivery.gmail import GmailDeliveryProvider

    return (
        ConsoleDeliveryProvider(config.delivery.save_html_path)
        if config.delivery.provider == "console"
        else GmailDeliveryProvider(
            required_env("GMAIL_CLIENT_ID"),
            required_env("GMAIL_CLIENT_SECRET"),
            required_env("GMAIL_REFRESH_TOKEN"),
            required_env("GMAIL_SENDER"),
            required_env("DIGEST_RECIPIENT"),
        )
    )


def create_pipeline(config: AppConfig) -> DigestPipeline:
    from .classification.gemini import GeminiClassifierProvider
    from .discovery.gemini import GeminiDiscoveryProvider
    from .writers.openai import OpenAIDigestWriter

    delivery = create_delivery(config)
    return DigestPipeline(
        config,
        create_store(config),
        GeminiDiscoveryProvider(config, required_env("GEMINI_API_KEY")),
        GeminiClassifierProvider(config, required_env("GEMINI_API_KEY")),
        OpenAIDigestWriter(config, required_env("OPENAI_API_KEY")),
        delivery,
    )
