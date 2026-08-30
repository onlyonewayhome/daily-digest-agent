import base64
from email.message import EmailMessage
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..models import Digest


class GmailDeliveryProvider:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 sender: str, recipient: str) -> None:
        self.sender = sender
        self.recipient = recipient
        self.credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )

    def deliver(self, digest: Digest) -> None:
        if not self.credentials.valid:
            self.credentials.refresh(Request())
        message = EmailMessage()
        message["To"] = self.recipient
        message["From"] = self.sender
        message["Subject"] = digest.subject
        message.set_content(digest.plain_text)
        message.add_alternative(digest.html, subtype="html")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        def send() -> Any:
            service = build("gmail", "v1", credentials=self.credentials, cache_discovery=False)
            return service.users().messages().send(userId="me", body={"raw": raw}).execute()

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                send()
                return
            except Exception as exc:
                last_error = exc
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if status not in {429, 500, 502, 503, 504} or attempt == 1:
                    raise
        assert last_error is not None
        raise last_error
