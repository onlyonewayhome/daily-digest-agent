from daily_digest_agent.normalize import canonicalize_url


def test_removes_tracking_fragment_and_trailing_slash():
    assert canonicalize_url("HTTPS://WWW.Example.COM/story/?utm_source=x&gclid=y#part") == "https://example.com/story"


def test_preserves_and_sorts_meaningful_parameters():
    assert canonicalize_url("https://example.com/search?z=2&q=topic&utm_term=x") == "https://example.com/search?q=topic&z=2"


def test_normalizes_mobile_and_amp():
    assert canonicalize_url("https://m.example.com/news/amp") == "https://example.com/news"
