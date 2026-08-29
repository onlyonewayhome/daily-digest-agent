from typing import Protocol

from ..models import Digest, DigestContext, Story


class DigestWriter(Protocol):
    def generate_digest(self, stories: list[Story], context: DigestContext) -> Digest: ...
