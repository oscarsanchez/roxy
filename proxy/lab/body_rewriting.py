"""Response body rewriting: URLs in manifests and documents become Prefixed URLs,
so follow-up traffic comes back through the lab.

A format rewriter is `rewrite(text, link) -> text`: it finds the URLs of its
format and passes each through `link`, which decides how it reaches the lab.
To add a format, write its rewriter and add a BodyFormat to FORMATS.

Which bodies get which rewriter is configurable without code changes: each
format has a mitmproxy option, lab_rewrite_<name> (e.g. lab_rewrite_json), that
lists its content types and URL extensions. FORMATS holds the defaults.
"""

from collections.abc import Sequence  # what mitmproxy's --set parser matches list options by
from pathlib import PurePosixPath
from typing import Callable, NamedTuple
from urllib.parse import urljoin, urlsplit

from mitmproxy import ctx
from mitmproxy.exceptions import OptionsError

from lab.dash import rewrite_dash
from lab.hls import rewrite_hls
from lab.json_body import rewrite_json
from lab.prefixed_url import prefixed_for_client
from lab.vast_xml import rewrite_xml


class BodyFormat(NamedTuple):
    name: str  # "hls": names the option (lab_rewrite_hls) and the manifest-edit format
    rewrite: Callable[[str, Callable[[str], str]], str]
    content_types: frozenset[str]  # defaults for the format's option
    extensions: frozenset[str]  # fallback when the content type is not one of ours

    @property
    def option(self):
        return f"lab_rewrite_{self.name}"


GENERIC_XML = frozenset({"application/xml", "text/xml"})

FORMATS = (
    BodyFormat(
        "hls",
        rewrite_hls,
        # Origins disagree: Mux test-streams serve HLS as audio/mpegurl.
        frozenset({"application/vnd.apple.mpegurl", "application/x-mpegurl",
                   "audio/mpegurl", "audio/x-mpegurl"}),
        frozenset({".m3u8"}),
    ),
    BodyFormat(
        "dash",
        rewrite_dash,
        frozenset({"application/dash+xml"}),
        # GCS serves .mpd as application/octet-stream; map_local gives it no type.
        frozenset({".mpd"}),
    ),
    BodyFormat("json", rewrite_json, frozenset({"application/json"}), frozenset({".json"})),
    BodyFormat("xml", rewrite_xml, GENERIC_XML, frozenset({".xml"})),  # VAST, ad responses
)


def _format_tables():
    """(content type -> format, extension -> format) from the formats' options.
    On a clash, the format listed first in FORMATS wins."""
    by_content_type, by_extension = {}, {}
    for body_format in FORMATS:
        for entry in getattr(ctx.options, body_format.option):
            entry = entry.strip().lower()
            if len(entry) > 1 and entry.startswith("."):
                by_extension.setdefault(entry, body_format)
            elif "/" in entry:
                by_content_type.setdefault(entry, body_format)
            else:
                raise OptionsError(
                    f"{body_format.option}: {entry!r} is neither a content type "
                    '("application/json") nor a URL extension (".json")'
                )
    return by_content_type, by_extension


def lab_link(flow):
    """How a URL found in `flow`'s response body reaches the lab.

    Absolute http(s) and root-relative URLs become Prefixed URLs with the client's
    Proxy Base (root-relative ones are resolved against the Origin URL first).
    Relative URLs are left alone: they already resolve through the Prefixed URL.
    """

    def link(url):
        if url.startswith("/"):
            return prefixed_for_client(flow, urljoin(flow.request.url, url))
        if urlsplit(url).scheme.lower() in ("http", "https"):
            return prefixed_for_client(flow, url)  # byte for byte: signed queries break otherwise
        return url

    return link


class BodyRewriter:
    def __init__(self):
        self.by_content_type, self.by_extension = {}, {}

    def load(self, loader):
        for body_format in FORMATS:
            loader.add_option(
                body_format.option, Sequence[str],
                sorted(body_format.content_types | body_format.extensions),
                f"Content types and URL extensions (\".ext\") whose response bodies get "
                f"the {body_format.name} rewriter. Empty turns it off.",
            )

    def configure(self, updated):
        if any(body_format.option in updated for body_format in FORMATS):
            self.by_content_type, self.by_extension = _format_tables()

    def body_format_for(self, content_type, url):
        """The format whose rewriter applies, chosen by content type, falling back to
        the URL extension; None means the body passes through untouched.

        A generic XML content type only says "some XML", so a format the URL extension
        names (a DASH .mpd served as text/xml) wins over it.
        """
        media_type = content_type.split(";")[0].strip().lower()
        extension = PurePosixPath(urlsplit(url).path).suffix.lower()
        by_type = self.by_content_type.get(media_type)
        by_extension = self.by_extension.get(extension)
        if media_type in GENERIC_XML:
            return by_extension or by_type
        return by_type or by_extension

    def response(self, flow):
        body_format = self.body_format_for(flow.response.headers.get("content-type", ""), flow.request.url)
        if body_format is not None:
            flow.metadata["body_format"] = body_format.name  # e.g. "hls", for manifest edits
        if "proxy_base" not in flow.metadata or body_format is None:
            return  # not Prefixed, or binary/unknown content: never decoded, passes byte for byte
        body = flow.response.text  # decoded: compression is mitmproxy's job
        rewritten = body_format.rewrite(body, lab_link(flow))
        if rewritten != body:
            flow.response.text = rewritten  # re-encoded with the original Content-Encoding
