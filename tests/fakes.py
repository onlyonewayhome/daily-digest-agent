from datetime import UTC, datetime

from daily_digest_agent.models import (
    CandidateStory,
    Digest,
    DigestContext,
    Story,
    StoryClassification,
)


class FakeDiscoveryProvider:
    def __init__(self, results=None, failures=None):
        self.results = results or {}
        self.failures = failures or set()

    def discover(self, mission):
        if mission.id in self.failures:
            raise RuntimeError("discovery failed")
        return self.results.get(mission.id, [])


class FakeClassifier:
    def __init__(self, classification=None, fail=False):
        self.classification = classification or StoryClassification(
            relevant=True, relevance_score=0.9, importance=4, category="major_news",
            story_key="example-development", reasoning_summary="Relevant",
            factual_summary="A documented development occurred.")
        self.fail = fail

    def classify(self, candidate):
        if self.fail:
            raise RuntimeError("classifier failed")
        return self.classification


class FakeWriter:
    def __init__(self, fail=False): self.fail = fail

    def generate_digest(self, stories: list[Story], context: DigestContext) -> Digest:
        if self.fail:
            raise RuntimeError("writer failed")
        body = ("Quiet day today — no substantial new developments met the configured relevance threshold."
                if context.quiet_day else "\n".join(story.title for story in stories))
        return Digest(digest_date=context.digest_date, subject=context.digest_name,
                      plain_text=body, html=f"<html><body><p>{body}</p></body></html>",
                      generated_at=datetime.now(UTC))


class FakeDelivery:
    def __init__(self, fail=False): self.fail, self.delivered = fail, []
    def deliver(self, digest):
        if self.fail:
            raise RuntimeError("delivery failed")
        self.delivered.append(digest)


def candidate(url="https://example.com/story", title="Example story"):
    return CandidateStory(title=title, url=url, publisher="Example", discovery_mission="general")
