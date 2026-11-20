"""The single source of truth for the Prefixed URL format (ADR-0001).

    <proxy-base>/<origin-url>
    proxy-base = scheme://host[:port][/secret-segment[/device-slug]]

The secret segment and device slug are for the Public Endpoint (Cloud Devices).

Every addon that reads or writes Prefixed URLs uses these two functions;
the rewriters reach build through prefixed_for_client.
"""

import re
from urllib.parse import urlsplit

_PREFIXED = re.compile(
    r"^(?P<proxy_base>https?://[^/?#]+(?:/(?!https?:)[^/?#]+){0,2})"
    r"/(?P<scheme>https?):/{1,2}"  # tolerate a client-collapsed "https:/host"
    r"(?P<rest>[^/?#]+.*)$"
)


def build_prefixed_url(proxy_base, origin_url):
    return f"{proxy_base.rstrip('/')}/{origin_url}"


def parse_prefixed_url(url):
    """Return (proxy_base, origin_url), or None if url is not a Prefixed URL."""
    match = _PREFIXED.match(url)
    if match is None:
        return None
    return match["proxy_base"], f"{match['scheme']}://{match['rest']}"


def _path_segment(proxy_base, index):
    segments = urlsplit(proxy_base).path.strip("/").split("/")
    return segments[index] if index < len(segments) else ""


def secret_segment(proxy_base):
    """The Proxy Base's secret path segment, or "" if it has none."""
    return _path_segment(proxy_base, 0)


def device_slug(proxy_base):
    """The Proxy Base's device slug (after the secret segment), or "" if it has none."""
    return _path_segment(proxy_base, 1)


def prefixed_for_client(flow, origin_url):
    """origin_url as a Prefixed URL with the Proxy Base of the client that made `flow`.

    A replayed response was rewritten when it was recorded: undo that first, so it
    is re-prefixed with this client's Proxy Base, never double-prefixed. Live
    responses are never parsed: an Origin URL may embed another URL.
    """
    if flow.is_replay == "response" and (parsed := parse_prefixed_url(origin_url)):
        origin_url = parsed[1]
    return build_prefixed_url(flow.metadata["proxy_base"], origin_url)
