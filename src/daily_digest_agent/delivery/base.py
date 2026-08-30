from typing import Protocol

from ..models import DeliveryReceipt, Digest


class DeliveryProvider(Protocol):
    def deliver(self, digest: Digest) -> DeliveryReceipt: ...
