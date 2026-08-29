from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "fbclid", "gclid"
}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    hostname = (parts.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if hostname.startswith("m."):
        hostname = hostname[2:]
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = parts.path or "/"
    if path.endswith("/amp"):
        path = path[:-4] or "/"
    if path != "/":
        path = path.rstrip("/")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMETERS]
    query.sort()
    return urlunsplit((scheme, hostname + port, path, urlencode(query, doseq=True), ""))
