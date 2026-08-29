from typing import Protocol

from ..models import Digest


class DeliveryProvider(Protocol):
    def deliver(self, digest: Digest) -> None: ...
