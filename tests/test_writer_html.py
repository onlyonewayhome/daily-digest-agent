import pytest

from daily_digest_agent.exceptions import ProviderOutputError
from daily_digest_agent.writers.html import sanitize_email_html

ALLOWED_URLS = {"https://example.com/story"}


def test_sanitizer_preserves_safe_email_structure_and_verified_link():
    value = (
        '<div style="color:red"><h2>Heading</h2><p>Read '
        '<a href="https://example.com/story" target="_blank">the source</a>.</p><ul><li>Item</li></ul></div>'
    )

    result = sanitize_email_html(value, ALLOWED_URLS)

    assert result == (
        '<div><h2>Heading</h2><p>Read <a href="https://example.com/story" '
        'rel="noopener noreferrer">the source</a>.</p><ul><li>Item</li></ul></div>'
    )


def test_sanitizer_drops_active_content_and_its_text():
    value = '<p>Before</p><script>alert("secret")</script><style>body{display:none}</style><p>After</p>'

    result = sanitize_email_html(value, ALLOWED_URLS)

    assert result == "<p>Before</p><p>After</p>"
    assert "alert" not in result
    assert "display" not in result


def test_sanitizer_unwraps_unknown_non_active_tags_and_escapes_text():
    value = "<article><custom>One & two</custom></article>"

    assert sanitize_email_html(value, ALLOWED_URLS) == "One &amp; two"


@pytest.mark.parametrize(
    "href",
    ["javascript:alert(1)", "http://example.com/story", "https://attacker.example/story", None],
)
def test_sanitizer_rejects_unverified_or_unsafe_links(href):
    attribute = "" if href is None else f' href="{href}"'

    with pytest.raises(ProviderOutputError, match="unverified or unsafe HTML link"):
        sanitize_email_html(f"<a{attribute}>source</a>", ALLOWED_URLS)


def test_sanitizer_closes_unclosed_allowed_tags():
    assert sanitize_email_html("<div><p>Body", ALLOWED_URLS) == "<div><p>Body</p></div>"