from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class CandidateStory(BaseModel):
    title: str = Field(min_length=1)
    url: HttpUrl
    publisher: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    discovery_mission: str
    locations: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def token_usage(self) -> TokenUsage:
        return TokenUsage.model_validate(self.source_metadata.get("token_usage", {}))


class StoryClassification(BaseModel):
    relevant: bool
    relevance_score: float = Field(ge=0, le=1)
    importance: int = Field(ge=0, le=5)
    category: str | None = None
    story_key: str = Field(min_length=1)
    reasoning_summary: str
    factual_summary: str
    token_usage: TokenUsage = Field(default_factory=lambda: TokenUsage())


class SourceRecord(BaseModel):
    title: str
    url: HttpUrl
    publisher: str | None = None
    published_at: datetime | None = None


class Story(BaseModel):
    id: str | None = None
    canonical_url: str
    title: str
    publisher: str | None = None
    published_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    category: str | None = None
    relevance_score: float = Field(ge=0, le=1)
    importance: int = Field(ge=0, le=5)
    story_key: str
    factual_summary: str
    sources: list[SourceRecord]
    included_in_digest: bool = False
    digest_id: str | None = None


class Digest(BaseModel):
    id: str | None = None
    digest_date: date
    subject: str
    plain_text: str
    html: str
    included_story_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    sent_at: datetime | None = None
    token_usage: TokenUsage = Field(default_factory=lambda: TokenUsage())


class DigestContext(BaseModel):
    digest_name: str
    digest_date: date
    editorial_voice: str
    categories: list[str]
    quiet_day: bool = False


class DiscoveryReport(BaseModel):
    searches_planned: int
    searches_successful: int
    searches_failed: int
    candidates_found: int
    errors: list[str] = Field(default_factory=list)

    @property
    def success_ratio(self) -> float:
        return self.searches_successful / self.searches_planned if self.searches_planned else 0.0


class UsageSummary(BaseModel):
    provider_calls_today: dict[str, int] = Field(default_factory=dict)
    provider_calls_month: dict[str, int] = Field(default_factory=dict)
    estimated_monthly_cost_usd: float = 0.0


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float | None = None


class RunResult(BaseModel):
    run_id: str
    status: str
    discovery: DiscoveryReport
    digest: Digest | None = None
    accepted_stories: int = 0
