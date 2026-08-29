from datetime import UTC, datetime

from daily_digest_agent.dedupe import deduplicate_candidates, group_stories_by_key
from daily_digest_agent.models import SourceRecord, Story
from tests.fakes import candidate


def test_exact_and_canonical_duplicates():
    values = [candidate("https://example.com/a?utm_source=x"), candidate("https://www.example.com/a/")]
    assert len(deduplicate_candidates(values)) == 1


def test_semantic_story_key_groups_sources():
    now = datetime.now(UTC)
    def story(url):
        return Story(canonical_url=url, title="Title", first_seen_at=now, last_seen_at=now,
                     relevance_score=.9, importance=4, story_key="same-event",
                     factual_summary="Fact", sources=[SourceRecord(title="Title", url=url)])
    grouped = group_stories_by_key([story("https://a.example/x"), story("https://b.example/y")])
    assert len(grouped) == 1
    assert len(grouped[0].sources) == 2
