from typing import Protocol

from ..config import SearchMissionSettings
from ..models import CandidateStory


class DiscoveryProvider(Protocol):
    def discover(self, mission: SearchMissionSettings) -> list[CandidateStory]: ...
