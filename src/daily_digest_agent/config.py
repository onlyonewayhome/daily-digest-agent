from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, model_validator

from .exceptions import ConfigurationError


class DigestSettings(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    timezone: str
    editorial_voice: str = Field(min_length=1)
    search_window_hours: int = Field(default=36, ge=1, le=336)
    quiet_day_message: str = Field(
        default="Quiet day today — no substantial new developments met the configured relevance threshold.",
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_timezone(self) -> DigestSettings:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown IANA timezone: {self.timezone}") from exc
        return self


class TopicSettings(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)


class CategorySettings(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    weight: int = Field(default=1, ge=0)


class SearchMissionSettings(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    prompt: str = Field(min_length=1)


class SourcesSettings(BaseModel):
    preferred_domains: list[str] = Field(default_factory=list)
    ignored_domains: list[str] = Field(default_factory=list)


class ModelProviderSettings(BaseModel):
    provider: Literal["google", "openai"]
    model: str
    grounding: Literal["google_search"] | None = None


class ModelsSettings(BaseModel):
    discovery: ModelProviderSettings
    classification: ModelProviderSettings
    writer: ModelProviderSettings

    @model_validator(mode="after")
    def validate_roles(self) -> ModelsSettings:
        if self.discovery.provider != "google" or self.classification.provider != "google":
            raise ValueError("V1 discovery and classification providers must be google")
        if self.writer.provider != "openai":
            raise ValueError("V1 writer provider must be openai")
        if self.discovery.grounding != "google_search":
            raise ValueError("Discovery must use google_search grounding")
        return self


class StorageSettings(BaseModel):
    provider: Literal["sqlite", "d1"] = "sqlite"
    sqlite_path: str = "./data/digest.db"


class DeliverySettings(BaseModel):
    provider: Literal["console", "gmail"] = "console"
    save_html_path: str | None = "./output"


class FiltersSettings(BaseModel):
    minimum_importance: int = Field(default=3, ge=0, le=5)
    minimum_relevance: float = Field(default=0.6, ge=0, le=1)
    maximum_stories_per_digest: int = Field(default=15, ge=1, le=100)


class ProviderBudgetSettings(BaseModel):
    max_calls_per_run: int = Field(ge=1)
    max_calls_per_day: int = Field(ge=1)
    max_output_tokens_per_digest: int | None = Field(default=None, ge=1)


class BudgetSettings(BaseModel):
    monthly_usd_cap: float = Field(default=3.0, gt=0)
    monthly_safety_buffer_usd: float = Field(default=0.25, ge=0)
    allow_unknown_pricing: bool = False
    max_runs_per_day: int = Field(default=1, ge=1)
    gemini: ProviderBudgetSettings
    openai: ProviderBudgetSettings

    @model_validator(mode="after")
    def validate_safety_buffer(self) -> BudgetSettings:
        if self.monthly_safety_buffer_usd >= self.monthly_usd_cap:
            raise ValueError("monthly_safety_buffer_usd must be less than monthly_usd_cap")
        return self


class ModelPrice(BaseModel):
    input_per_million: float | None = Field(default=None, ge=0)
    output_per_million: float | None = Field(default=None, ge=0)


class PricingSettings(BaseModel):
    google: dict[str, ModelPrice] = Field(default_factory=dict)
    openai: dict[str, ModelPrice] = Field(default_factory=dict)


class HealthSettings(BaseModel):
    minimum_search_success_ratio: float = Field(default=0.75, gt=0, le=1)


class AppConfig(BaseModel):
    digest: DigestSettings
    topic: TopicSettings
    categories: list[CategorySettings] = Field(min_length=1)
    search_missions: list[SearchMissionSettings] = Field(min_length=1)
    sources: SourcesSettings = Field(default_factory=SourcesSettings)
    models: ModelsSettings
    storage: StorageSettings = Field(default_factory=StorageSettings)
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)
    filters: FiltersSettings = Field(default_factory=FiltersSettings)
    budget: BudgetSettings
    pricing: PricingSettings = Field(default_factory=PricingSettings)
    health: HealthSettings = Field(default_factory=HealthSettings)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> AppConfig:
        for values, label in ((self.categories, "category"), (self.search_missions, "mission")):
            ids = [item.id for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {label} IDs are not allowed")
        return self


def load_config(path: str | Path | None = None) -> AppConfig:
    configured = path or os.getenv("DIGEST_CONFIG_PATH") or "config/example.yaml"
    config_path = Path(configured)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return AppConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise ConfigurationError(f"Unable to load configuration from {config_path}: {exc}") from exc
