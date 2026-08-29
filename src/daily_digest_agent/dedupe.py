from collections.abc import Iterable

from .models import CandidateStory, Story
from .normalize import canonicalize_url


def deduplicate_candidates(candidates: Iterable[CandidateStory]) -> list[CandidateStory]:
    seen: set[str] = set()
    result: list[CandidateStory] = []
    for candidate in candidates:
        canonical = canonicalize_url(str(candidate.url))
        if canonical not in seen:
            seen.add(canonical)
            result.append(candidate)
    return result


def group_stories_by_key(stories: Iterable[Story]) -> list[Story]:
    grouped: dict[str, Story] = {}
    for story in stories:
        existing = grouped.get(story.story_key)
        if existing is None:
            grouped[story.story_key] = story.model_copy(deep=True)
            continue
        known = {str(source.url) for source in existing.sources}
        existing.sources.extend(source for source in story.sources if str(source.url) not in known)
        if story.importance > existing.importance:
            existing.title = story.title
            existing.factual_summary = story.factual_summary
            existing.importance = story.importance
            existing.relevance_score = story.relevance_score
            existing.category = story.category
    return list(grouped.values())
