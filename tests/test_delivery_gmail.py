import base64
from datetime import UTC, date, datetime
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from daily_digest_agent.delivery import gmail
from daily_digest_agent.delivery.gmail import GmailDeliveryProvider
from daily_digest_agent.models import Digest


class HttpError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def digest():
    return Digest(
        digest_date=date(2026, 8, 29),
        subject="Example Daily",
        plain_text="Plain body",
        html="<p>HTML body</p>",
        generated_at=datetime.now(UTC),
    )


def provider():
    value = object.__new__(GmailDeliveryProvider)
    value.sender = "sender@example.com"
    value.recipient = "reader@example.com"
    value.credentials = SimpleNamespace(valid=True)
    return value


def test_gmail_builds_multipart_message(monkeypatch):
    bodies = []

    class Request:
        def execute(self):
            return {"id": "message-id"}

    class Messages:
        def send(self, *, userId, body):
            assert userId == "me"
            bodies.append(body)
            return Request()

    service = SimpleNamespace(users=lambda: SimpleNamespace(messages=lambda: Messages()))
    monkeypatch.setattr(gmail, "build", lambda *args, **kwargs: service)

    provider().deliver(digest())

    raw = base64.urlsafe_b64decode(bodies[0]["raw"])
    message = BytesParser(policy=policy.default).parsebytes(raw)
    assert message["To"] == "reader@example.com"
    assert message["From"] == "sender@example.com"
    assert message["Subject"] == "Example Daily"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Plain body"
    assert message.get_body(preferencelist=("html",)).get_content().strip() == "<p>HTML body</p>"


def test_gmail_retries_transient_failure_once(monkeypatch):
    attempts = 0

    class Request:
        def execute(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise HttpError(503)
            return {"id": "message-id"}

    service = SimpleNamespace(
        users=lambda: SimpleNamespace(
            messages=lambda: SimpleNamespace(send=lambda **kwargs: Request())
        )
    )
    monkeypatch.setattr(gmail, "build", lambda *args, **kwargs: service)

    provider().deliver(digest())

    assert attempts == 2


def test_gmail_does_not_retry_permanent_failure(monkeypatch):
    attempts = 0

    class Request:
        def execute(self):
            nonlocal attempts
            attempts += 1
            raise HttpError(400)

    service = SimpleNamespace(
        users=lambda: SimpleNamespace(
            messages=lambda: SimpleNamespace(send=lambda **kwargs: Request())
        )
    )
    monkeypatch.setattr(gmail, "build", lambda *args, **kwargs: service)

    with pytest.raises(HttpError):
        provider().deliver(digest())

    assert attempts == 1