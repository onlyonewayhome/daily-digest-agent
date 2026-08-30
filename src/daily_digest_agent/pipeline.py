from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep
from typing import TypeVar
from zoneinfo import ZoneInfo

from .budgeting import BudgetGuard, estimate_cost
from .classification.base import ClassifierProvider
from .config import AppConfig, SearchMissionSettings
from .dedupe import deduplicate_candidates, group_stories_by_key
from .delivery.base import DeliveryProvider
from .discovery.base import DiscoveryProvider
from .exceptions import BudgetExceeded, DiscoveryHealthError, DuplicateDigestError, ProviderOutputError
from .models import (
    CandidateStory,
    ClassificationReport,
    Digest,
    DigestContext,
    DiscoveryReport,
    DiscoveryResult,
    RunResult,
    SourceRecord,
    Story,
    StoryClassification,
    UsageBearing,
)
from .normalize import canonical_story_url
from .retry import is_retryable_error
from .storage.base import StateStore
from .writers.base import DigestWriter

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=UsageBearing)


def build_quiet_day_digest(context: DigestContext, message: str) -> Digest:
    return Digest(
        digest_date=context.digest_date,
        subject=f"{context.digest_name} — {context.digest_date}",
        plain_text=message,
        html=f"<p>{message}</p>",
        generated_at=datetime.now(UTC),
    )


class DigestPipeline:
    def __init__(self, config: AppConfig, store: StateStore, discovery: DiscoveryProvider,
                 classifier: ClassifierProvider, writer: DigestWriter,
                 delivery: DeliveryProvider) -> None:
        self.config = config
        self.store = store
        self.discovery = discovery
        self.classifier = classifier
        self.writer = writer
        self.delivery = delivery

    def _paid_call(self, guard: BudgetGuard, run_id: str, provider: str, model: str,
                   operation: Callable[[], T], attempts: int, unsafe_override: bool) -> T:
        last_error: Exception | None = None
        prices = self.config.pricing.google if provider == "google" else self.config.pricing.openai
        for attempt in range(attempts):
            guard.check_request(provider, model, unsafe_override)
            try:
                result = operation()
                usage = result.token_usage
                cost = estimate_cost(prices.get(model), usage.input_tokens, usage.output_tokens)
                if cost is None:
                    logger.warning(
                        "Paid request cost is unknown; dollar budget accounting is incomplete",
                        extra={"provider": provider, "model": model, "run_id": run_id},
                    )
                self.store.record_usage(
                    run_id, guard.local_date, provider, model, usage.input_tokens, usage.output_tokens, cost
                )
                return result
            except Exception as exc:
                self.store.record_usage(run_id, guard.local_date, provider, model, 0, 0, None)
                last_error = exc
                if not is_retryable_error(provider, exc) or attempt == attempts - 1:
                    raise
                sleep(2**attempt)
        assert last_error is not None
        raise last_error

    def run(self, *, dry_run: bool = False, force: bool = False,
            force_send: bool = False, unsafe_budget_override: bool = False) -> RunResult:
        now = datetime.now(UTC)
        local_date = now.astimezone(ZoneInfo(self.config.digest.timezone)).date()
        self.store.initialize()
        guard = BudgetGuard(self.config, self.store, local_date)
        guard.check_run(force=force)
        if self.store.digest_sent_for_date(local_date) and not force_send:
            raise DuplicateDigestError(f"A digest was already sent for {local_date}")
        run_id = self.store.record_run_start(local_date, force)
        report = DiscoveryReport(searches_planned=len(self.config.search_missions),
                                 searches_successful=0, searches_failed=0, candidates_found=0)
        try:
            candidates = []
            for mission in self.config.search_missions:
                try:
                    def discover(mission: SearchMissionSettings = mission) -> DiscoveryResult:
                        return self.discovery.discover(mission)

                    result = self._paid_call(
                        guard, run_id, "google", self.config.models.discovery.model,
                        discover, 3,
                        unsafe_budget_override,
                    )
                    candidates.extend(result.stories)
                    report.searches_successful += 1
                    report.candidates_found += len(result.stories)
                    report.candidates_grounded += sum(bool(candidate.grounding_sources) for candidate in result.stories)
                    report.candidates_ungrounded += sum(
                        not candidate.grounding_sources for candidate in result.stories
                    )
                except BudgetExceeded:
                    raise
                except Exception as exc:  # missions are isolated by design
                    report.searches_failed += 1
                    report.errors.append(f"{mission.id}: {exc}")
                    logger.exception("Discovery mission failed", extra={"mission": mission.id, "run_id": run_id})
            if report.success_ratio < self.config.health.minimum_search_success_ratio:
                raise DiscoveryHealthError("Digest not generated because discovery coverage was insufficient")
            unique_candidates = deduplicate_candidates(candidates)
            if self.config.sources.grounding_policy == "require":
                report.candidates_rejected_ungrounded = sum(
                    not candidate.grounding_sources for candidate in unique_candidates
                )
                unique_candidates = [candidate for candidate in unique_candidates if candidate.grounding_sources]
            novel = [candidate for candidate in unique_candidates
                     if not self.store.story_exists(canonical_story_url(candidate))]
            accepted: list[Story] = []
            classification_report = ClassificationReport()
            configured_ids = {category.id for category in self.config.categories}
            for candidate in novel:
                classification_report.attempted += 1
                try:
                    def classify(candidate: CandidateStory = candidate) -> StoryClassification:
                        return self.classifier.classify(candidate)

                    classification = self._paid_call(
                        guard, run_id, "google", self.config.models.classification.model,
                        classify, 3,
                        unsafe_budget_override,
                    )
                    if classification.category is not None and classification.category not in configured_ids:
                        raise ProviderOutputError(
                            f"Classifier returned unknown category {classification.category!r}; "
                            f"expected {sorted(configured_ids)}"
                        )
                except ProviderOutputError as exc:
                    classification_report.rejected += 1
                    classification_report.invalid_output += 1
                    classification_report.errors.append(str(exc))
                    logger.warning(
                        "Rejected candidate due to invalid classifier output",
                        extra={"candidate_url": str(candidate.url), "run_id": run_id},
                    )
                    continue

                classification_report.successful += 1
                if (not classification.relevant
                        or classification.relevance_score < self.config.filters.minimum_relevance
                        or classification.importance < self.config.filters.minimum_importance):
                    classification_report.rejected += 1
                    continue
                sources = candidate.grounding_sources or [
                    SourceRecord(title=candidate.title, url=candidate.url, publisher=candidate.publisher,
                                 published_at=candidate.published_at)
                ]
                accepted.append(Story(
                    canonical_url=canonical_story_url(candidate), title=candidate.title,
                    publisher=candidate.publisher, published_at=candidate.published_at,
                    first_seen_at=now, last_seen_at=now, category=classification.category,
                    relevance_score=classification.relevance_score, importance=classification.importance,
                    story_key=classification.story_key, factual_summary=classification.factual_summary,
                    sources=sources))

            grouped = group_stories_by_key(accepted)
            for story in grouped:
                story.id = self.store.upsert_story(story)
            selected = sorted(grouped, key=lambda item: item.importance, reverse=True)[
                :self.config.filters.maximum_stories_per_digest]
            context = DigestContext(digest_name=self.config.digest.name, digest_date=local_date,
                                    editorial_voice=self.config.digest.editorial_voice,
                                    categories=[category.name for category in self.config.categories],
                                    quiet_day=not selected)
            if selected:
                digest = self._paid_call(
                    guard, run_id, "openai", self.config.models.writer.model,
                    lambda: self.writer.generate_digest(selected, context), 2,
                    unsafe_budget_override,
                )
            else:
                digest = build_quiet_day_digest(context, self.config.digest.quiet_day_message)
            digest.included_story_ids = [story.id for story in selected if story.id]
            digest_id = self.store.record_digest(digest, run_id)
            digest.id = digest_id
            if not dry_run:
                self.delivery.deliver(digest)
                sent_at = datetime.now(UTC)
                self.store.mark_digest_sent(digest_id, sent_at)
                digest.sent_at = sent_at
            self.store.record_run_finish(run_id, "success")
            return RunResult(run_id=run_id, status="success", discovery=report,
                             classification=classification_report, digest=digest, accepted_stories=len(grouped))
        except Exception as exc:
            status = "degraded" if isinstance(exc, DiscoveryHealthError) else "failed"
            self.store.record_run_finish(run_id, status, str(exc))
            raise
