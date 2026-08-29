from typing import Protocol

from ..config import SearchMissionSettings
from ..models import DiscoveryResult


class DiscoveryProvider(Protocol):
    def discover(self, mission: SearchMissionSettings) -> DiscoveryResult: ...
