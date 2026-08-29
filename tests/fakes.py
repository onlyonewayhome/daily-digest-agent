from datetime import UTC, datetime

from daily_digest_agent.models import (
    CandidateStory,
    Digest,
    DigestContext,
    DiscoveryResult,
    Story,
    StoryClassification,
    TokenUsage,
)


class FakeDiscoveryProvider:
    def __init__(self, results=None, failures=None, token_usage=None):
        self.results = results or {}
        self.failures = failures or set()
        self.token_usage = token_usage or TokenUsage(input_tokens=100, output_tokens=20)
        self.calls = 0

    def discover(self, mission):
        self.calls += 1
        if mission.id in self.failures:
            raise RuntimeError("discovery failed")
        result = self.results.get(mission.id, [])
        if isinstance(result, Exception):
            raise result
        if isinstance(result, DiscoveryResult):
            return result
        return DiscoveryResult(stories=result, token_usage=self.token_usage)


class FakeClassifier:
    def __init__(self, classification=None, fail=False):
        self.classification = classification or StoryClassification(
            relevant=True, relevance_score=0.9, importance=4, category="major_news",
            story_key="example-development", reasoning_summary="Relevant",
            factual_summary="A documented development occurred.")
        self.fail = fail
        self.calls = 0

    def classify(self, candidate):
        self.calls += 1
        if self.fail:
            raise RuntimeError("classifier failed")
        return self.classification


class FakeWriter:
    def __init__(self, fail=False): self.fail, self.calls = fail, 0

    def generate_digest(self, stories: list[Story], context: DigestContext) -> Digest:
        self.calls += 1
        if self.fail:
            raise RuntimeError("writer failed")
        body = ("Quiet day today — no substantial new developments met the configured relevance threshold."
                if context.quiet_day else "\n".join(story.title for story in stories))
        return Digest(digest_date=context.digest_date, subject=context.digest_name,
                      plain_text=body, html=f"<html><body><p>{body}</p></body></html>",
                      generated_at=datetime.now(UTC),
                      token_usage=TokenUsage(input_tokens=50, output_tokens=25))


class FakeDelivery:
    def __init__(self, fail=False): self.fail, self.delivered = fail, []
    def deliver(self, digest):
        if self.fail:
            raise RuntimeError("delivery failed")
        self.delivered.append(digest)


def candidate(url="https://example.com/story", title="Example story"):
    return CandidateStory(title=title, url=url, publisher="Example", discovery_mission="general")
