from typing import Protocol

from ..models import CandidateStory, StoryClassification


class ClassifierProvider(Protocol):
    def classify(self, candidate: CandidateStory) -> StoryClassification: ...
