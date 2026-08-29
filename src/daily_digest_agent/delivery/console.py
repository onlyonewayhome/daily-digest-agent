from pathlib import Path

from ..models import Digest


class ConsoleDeliveryProvider:
    def __init__(self, save_html_path: str | None = None) -> None:
        self.save_html_path = save_html_path

    def deliver(self, digest: Digest) -> None:
        print(f"Subject: {digest.subject}\n\n{digest.plain_text}")
        if self.save_html_path:
            output = Path(self.save_html_path)
            output.mkdir(parents=True, exist_ok=True)
            (output / f"{digest.digest_date}.html").write_text(digest.html, encoding="utf-8")
