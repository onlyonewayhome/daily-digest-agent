from datetime import UTC, date, datetime

import pytest

from daily_digest_agent.delivery.recovery import retry_delivery
from daily_digest_agent.exceptions import DeliveryStateError
from daily_digest_agent.models import Digest
from daily_digest_agent.storage.sqlite import SQLiteStateStore
from tests.fakes import FakeDelivery


def setup_unknown_delivery(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.initialize()
    local_date = date(2026, 8, 30)
    run_id = store.record_run_start(local_date, forced=False)
    digest = Digest(
        digest_date=local_date,
        subject="Existing digest",
        plain_text="Existing body",
        html="<p>Existing body</p>",
        generated_at=datetime.now(UTC),
    )
    digest_id = store.record_digest(digest, run_id)
    delivery_id = store.reserve_delivery(local_date, run_id)
    assert delivery_id is not None
    store.update_delivery(delivery_id, "unknown", digest_id=digest_id, error="ambiguous")
    return store, delivery_id


def test_retry_delivery_resends_persisted_digest_as_new_attempt(tmp_path):
    store, delivery_id = setup_unknown_delivery(tmp_path)
    delivery = FakeDelivery()

    result = retry_delivery(store, delivery, delivery_id)

    assert result["attempt"] == 2
    assert result["state"] == "sent"
    assert result["provider"] == "fake"
    assert result["provider_message_id"] == "fake-1"
    assert len(delivery.delivered) == 1
    assert delivery.delivered[0].subject == "Existing digest"


def test_retry_delivery_rejects_sent_attempt(tmp_path):
    store, delivery_id = setup_unknown_delivery(tmp_path)
    store.update_delivery(delivery_id, "sent")

    with pytest.raises(DeliveryStateError, match="only failed or unknown"):
        retry_delivery(store, FakeDelivery(), delivery_id)