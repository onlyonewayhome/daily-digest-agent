from __future__ import annotations

from html import escape
from html.parser import HTMLParser

from ..exceptions import ProviderOutputError

ALLOWED_TAGS = {
    "a", "blockquote", "br", "div", "em", "h1", "h2", "h3", "hr", "li", "ol", "p", "span", "strong", "ul",
}
VOID_TAGS = {"br", "hr"}
DROP_CONTENT_TAGS = {"audio", "canvas", "embed", "form", "iframe", "object", "script", "style", "svg", "video"}


class EmailHTMLSanitizer(HTMLParser):
    def __init__(self, allowed_urls: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.allowed_urls = allowed_urls
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.dropped_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.dropped_depth:
            if tag in DROP_CONTENT_TAGS:
                self.dropped_depth += 1
            return
        if tag in DROP_CONTENT_TAGS:
            self.dropped_depth = 1
            return
        if tag not in ALLOWED_TAGS:
            return
        rendered_attrs = ""
        if tag == "a":
            values = {name.lower(): value for name, value in attrs}
            href = values.get("href")
            if href is None or href not in self.allowed_urls or not href.startswith("https://"):
                raise ProviderOutputError(f"Writer returned an unverified or unsafe HTML link: {href!r}")
            rendered_attrs = f' href="{escape(href, quote=True)}" rel="noopener noreferrer"'
        self.output.append(f"<{tag}{rendered_attrs}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS and self.open_tags and self.open_tags[-1] == tag.lower():
            self.open_tags.pop()
            self.output.append(f"</{tag.lower()}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.dropped_depth:
            if tag in DROP_CONTENT_TAGS:
                self.dropped_depth -= 1
            return
        if tag in VOID_TAGS or tag not in self.open_tags:
            return
        while self.open_tags:
            open_tag = self.open_tags.pop()
            self.output.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.dropped_depth:
            self.output.append(escape(data))

    def close(self) -> None:
        super().close()
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")


def sanitize_email_html(value: str, allowed_urls: set[str]) -> str:
    sanitizer = EmailHTMLSanitizer(allowed_urls)
    try:
        sanitizer.feed(value)
        sanitizer.close()
    except ProviderOutputError:
        raise
    except Exception as exc:
        raise ProviderOutputError(f"Writer returned malformed HTML: {exc}") from exc
    return "".join(sanitizer.output)