from pathlib import Path

from ..models import DeliveryReceipt, Digest


class ConsoleDeliveryProvider:
    def __init__(self, save_html_path: str | None = None) -> None:
        self.save_html_path = save_html_path

    def deliver(self, digest: Digest) -> DeliveryReceipt:
        print(f"Subject: {digest.subject}\n\n{digest.plain_text}")
        if self.save_html_path:
            output = Path(self.save_html_path)
            output.mkdir(parents=True, exist_ok=True)
            (output / f"{digest.digest_date}.html").write_text(digest.html, encoding="utf-8")
        return DeliveryReceipt(provider="console", provider_message_id=f"console:{digest.digest_date}")
