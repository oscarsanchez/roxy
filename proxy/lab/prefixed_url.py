"""The single source of truth for the Prefixed URL format and its two forms.

    <proxy-base><separator><origin-url>
    proxy-base = scheme://host[:port][/secret-segment[/device-slug]]
    separator  = "/" (the lab's own form) | "/;" (the Charles-style form)

The secret segment and device slug are for the Public Endpoint (Cloud Devices).

Every addon that reads or writes Prefixed URLs uses these two functions;
the rewriters reach build through prefixed_for_client.

It also owns where a flow keeps its client's Proxy Base and separator:
remember_client writes them, client_proxy_base reads them.
"""

import re
from typing import NamedTuple
from urllib.parse import urlsplit

_PREFIXED = re.compile(
    r"^(?P<proxy_base>https?://[^/?#]+(?:/(?!;?https?:)[^/?#]+){0,2})"
    r"(?P<separator>/;?)(?P<scheme>https?):/{1,2}"  # tolerate a client-collapsed "https:/host"
    r"(?P<rest>[^/?#]+.*)$"
)


class PrefixedUrl(NamedTuple):
    proxy_base: str
    separator: str
    origin_url: str


class ClientProxyBase(NamedTuple):
    """The Proxy Base and separator a client's Prefixed request used."""

    proxy_base: str
    separator: str


def build_prefixed_url(proxy_base, separator, origin_url):
    return f"{proxy_base.rstrip('/')}{separator}{origin_url}"


def parse_prefixed_url(url):
    """Return a PrefixedUrl, or None if url is not a Prefixed URL."""
    match = _PREFIXED.match(url)
    if match is None:
        return None
    return PrefixedUrl(match["proxy_base"], match["separator"], f"{match['scheme']}://{match['rest']}")


def _path_segment(proxy_base, index):
    segments = urlsplit(proxy_base).path.strip("/").split("/")
    return segments[index] if index < len(segments) else ""


def secret_segment(proxy_base):
    """The Proxy Base's secret path segment, or "" if it has none."""
    return _path_segment(proxy_base, 0)


def device_slug(proxy_base):
    """The Proxy Base's device slug (after the secret segment), or "" if it has none."""
    return _path_segment(proxy_base, 1)


def remember_client(flow, parsed):
    """Keep the Proxy Base and separator of the PrefixedUrl `parsed` that `flow` arrived as.

    Plain strings in flow.metadata, under keys Recordings already hold.
    """
    flow.metadata["proxy_base"] = parsed.proxy_base
    flow.metadata["separator"] = parsed.separator


def client_proxy_base(flow):
    """The ClientProxyBase of the client that made `flow`, or None if its request was not Prefixed."""
    if "proxy_base" not in flow.metadata:
        return None
    return ClientProxyBase(flow.metadata["proxy_base"], flow.metadata["separator"])


def prefixed_for_client(flow, origin_url):
    """origin_url as a Prefixed URL with the Proxy Base of the client that made `flow`.

    A URL already Prefixed, in either form, is never prefixed again: it comes back
    in the separator the request used. That is any Prefixed URL in a replayed
    response (rewritten when it was recorded, maybe for another client), but in a
    live one only a URL with this client's Proxy Base: an Origin URL may embed
    another URL.
    """
    proxy_base, separator = client_proxy_base(flow)
    parsed = parse_prefixed_url(origin_url)
    if parsed and (flow.is_replay == "response" or parsed.proxy_base == proxy_base):
        origin_url = parsed.origin_url
    return build_prefixed_url(proxy_base, separator, origin_url)
