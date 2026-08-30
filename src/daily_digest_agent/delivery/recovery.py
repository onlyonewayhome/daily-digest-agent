from __future__ import annotations

from datetime import UTC, datetime

from ..exceptions import DeliveryStateError
from ..storage.base import StateStore
from .base import DeliveryProvider


def retry_delivery(store: StateStore, delivery: DeliveryProvider, delivery_id: str) -> dict[str, object]:
    original = store.get_delivery(delivery_id)
    if original is None:
        raise DeliveryStateError(f"Delivery attempt not found: {delivery_id}")
    if original["state"] not in {"failed", "unknown"}:
        raise DeliveryStateError(
            f"Delivery attempt {delivery_id} is {original['state']!r}; only failed or unknown attempts can be retried"
        )
    digest_id = original.get("digest_id")
    if not isinstance(digest_id, str) or not digest_id:
        raise DeliveryStateError(f"Delivery attempt {delivery_id} has no persisted digest")
    digest = store.get_digest(digest_id)
    if digest is None:
        raise DeliveryStateError(f"Digest not found for delivery attempt {delivery_id}: {digest_id}")
    digest.sent_at = None
    retry_id = store.reserve_delivery(digest.digest_date, str(original["run_id"]), force=True)
    if retry_id is None:
        raise DeliveryStateError(f"Unable to reserve retry for delivery attempt {delivery_id}")
    store.update_delivery(retry_id, "sending", digest_id=digest_id)
    try:
        receipt = delivery.deliver(digest)
    except Exception as exc:
        store.update_delivery(retry_id, "unknown", digest_id=digest_id, error=str(exc))
        raise
    store.complete_delivery(retry_id, digest_id, datetime.now(UTC), receipt)
    result = store.get_delivery(retry_id)
    assert result is not None
    return result