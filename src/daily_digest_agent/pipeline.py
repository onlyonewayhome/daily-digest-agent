from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .budgeting import BudgetGuard, estimate_cost
from .classification.base import ClassifierProvider
from .config import AppConfig
from .dedupe import deduplicate_candidates, group_stories_by_key
from .delivery.base import DeliveryProvider
from .discovery.base import DiscoveryProvider
from .exceptions import BudgetExceeded, DiscoveryHealthError, DuplicateDigestError
from .models import DigestContext, DiscoveryReport, RunResult, SourceRecord, Story
from .normalize import canonicalize_url
from .storage.base import StateStore
from .writers.base import DigestWriter

logger = logging.getLogger(__name__)


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
                   operation, attempts: int, unsafe_override: bool):
        last_error = None
        for attempt in range(attempts):
            guard.check_request(provider, unsafe_override)
            try:
                result = operation()
                if isinstance(result, list):
                    input_tokens = max((item.token_usage.input_tokens for item in result), default=0)
                    output_tokens = max((item.token_usage.output_tokens for item in result), default=0)
                else:
                    input_tokens = result.token_usage.input_tokens
                    output_tokens = result.token_usage.output_tokens
                prices = (self.config.pricing.google if provider == "google"
                          else self.config.pricing.openai)
                cost = estimate_cost(prices.get(model), input_tokens, output_tokens)
                self.store.record_usage(
                    run_id, provider, model, input_tokens, output_tokens, cost
                )
                return result
            except Exception as exc:
                self.store.record_usage(run_id, provider, model, 0, 0, None)
                last_error = exc
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if status not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                    raise
                from time import sleep
                sleep(2**attempt)
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
                    found = self._paid_call(
                        guard, run_id, "google", self.config.models.discovery.model,
                        lambda mission=mission: self.discovery.discover(mission), 3,
                        unsafe_budget_override,
                    )
                    candidates.extend(found)
                    report.searches_successful += 1
                    report.candidates_found += len(found)
                except BudgetExceeded:
                    raise
                except Exception as exc:  # missions are isolated by design
                    report.searches_failed += 1
                    report.errors.append(f"{mission.id}: {exc}")
                    logger.exception("Discovery mission failed", extra={"mission": mission.id, "run_id": run_id})
            if report.success_ratio < self.config.health.minimum_search_success_ratio:
                raise DiscoveryHealthError("Digest not generated because discovery coverage was insufficient")

            novel = [candidate for candidate in deduplicate_candidates(candidates)
                     if not self.store.story_exists(canonicalize_url(str(candidate.url)))]
            accepted: list[Story] = []
            for candidate in novel:
                classification = self._paid_call(
                    guard, run_id, "google", self.config.models.classification.model,
                    lambda candidate=candidate: self.classifier.classify(candidate), 3,
                    unsafe_budget_override,
                )
                if (not classification.relevant
                        or classification.relevance_score < self.config.filters.minimum_relevance
                        or classification.importance < self.config.filters.minimum_importance):
                    continue
                accepted.append(Story(
                    canonical_url=canonicalize_url(str(candidate.url)), title=candidate.title,
                    publisher=candidate.publisher, published_at=candidate.published_at,
                    first_seen_at=now, last_seen_at=now, category=classification.category,
                    relevance_score=classification.relevance_score, importance=classification.importance,
                    story_key=classification.story_key, factual_summary=classification.factual_summary,
                    sources=[SourceRecord(title=candidate.title, url=candidate.url,
                                          publisher=candidate.publisher, published_at=candidate.published_at)]))

            grouped = group_stories_by_key(accepted)
            for story in grouped:
                story.id = self.store.upsert_story(story)
            selected = sorted(grouped, key=lambda item: item.importance, reverse=True)[
                :self.config.filters.maximum_stories_per_digest]
            context = DigestContext(digest_name=self.config.digest.name, digest_date=local_date,
                                    editorial_voice=self.config.digest.editorial_voice,
                                    categories=[category.name for category in self.config.categories],
                                    quiet_day=not selected)
            digest = self._paid_call(
                guard, run_id, "openai", self.config.models.writer.model,
                lambda: self.writer.generate_digest(selected, context), 2,
                unsafe_budget_override,
            )
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
                             digest=digest, accepted_stories=len(grouped))
        except Exception as exc:
            status = "degraded" if isinstance(exc, DiscoveryHealthError) else "failed"
            self.store.record_run_finish(run_id, status, str(exc))
            raise
