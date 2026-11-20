"""Response header rewriting: header-borne URLs become Prefixed URLs, so follow-up
traffic comes back through the lab."""

import re
from urllib.parse import urljoin, urlsplit

from lab.prefixed_url import client_proxy_base, prefixed_for_client

# Where the URL sits in each header value (the "url" group is replaced).
_WHOLE_VALUE = re.compile(r"(?P<url>.+)")
_URLS = {
    "content-location": _WHOLE_VALUE,
    "link": re.compile(r"<(?P<url>[^>]*)>"),
    "refresh": re.compile(r";\s*url\s*=\s*['\"]?(?P<url>[^'\"]+)", re.IGNORECASE),
}
_COOKIE_DOMAIN = re.compile(r";\s*domain\s*=[^;]*", re.IGNORECASE)
_COOKIE_PATH = re.compile(r";\s*path\s*=\s*(?P<url>[^;]+)", re.IGNORECASE)


class ResponseHeaderRewriter:
    def responseheaders(self, flow):
        if client_proxy_base(flow) is None:  # the lab answered a non-Prefixed request itself
            return
        response = flow.response
        urls = dict(_URLS)
        if 300 <= response.status_code < 400 or response.status_code == 201:
            urls["location"] = _WHOLE_VALUE

        def prefixed(url):
            """The Prefixed URL for a (possibly relative) URL the Origin sent."""
            return prefixed_for_client(flow, urljoin(flow.request.url, url))

        def cookie_path(path):
            """The Prefixed URL's path, up to any ";": a cookie path cannot hold one
            (RFC 6265), so a Charles-style ("/;") cookie is scoped to the Proxy Base."""
            return urlsplit(prefixed(path)).path.partition(";")[0]

        def cookie(value):
            """Host-only on the Proxy Base, and scoped to its Origin by path."""
            value = _COOKIE_DOMAIN.sub("", value)
            return _replace_url(_COOKIE_PATH, cookie_path, value)

        for name, pattern in urls.items():
            _rewrite_values(response.headers, name, lambda v: _replace_url(pattern, prefixed, v))
        _rewrite_values(response.headers, "set-cookie", cookie)


def _rewrite_values(headers, name, rewrite):
    values = headers.get_all(name)
    if values:
        headers.set_all(name, [rewrite(v) for v in values])


def _replace_url(pattern, rewrite, value):
    """Apply `rewrite` to the "url" group of every match of `pattern` in `value`."""

    def replace(match):
        start, end = match.start("url") - match.start(), match.end("url") - match.start()
        return match[0][:start] + rewrite(match["url"]) + match[0][end:]

    return pattern.sub(replace, value)
