"""Response body rewriting: URLs in manifests and documents become Prefixed URLs,
so follow-up traffic comes back through the lab.

A format rewriter is `rewrite(text, link) -> text`: it finds the URLs of its
format and passes each through `link`, which decides how it reaches the lab.
To add a format, write its rewriter and add a BodyFormat to FORMATS.

Which bodies get which rewriter is configurable without code changes: each
format has a mitmproxy option, lab_rewrite_<name> (e.g. lab_rewrite_json), that
lists its content types, structured-syntax suffixes ("+json") and URL extensions.
FORMATS holds the defaults.

An opt-in format (text) is off unless the loaded App Profile turns it on (lab.app_profile's
rewrites_text, False with no profile).
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
from lab.prefixed_url import client_proxy_base, prefixed_for_client
from lab.text_body import rewrite_text
from lab.vast_xml import rewrite_xml


class BodyFormat(NamedTuple):
    name: str  # "hls": names the option (lab_rewrite_hls) and the manifest-edit format
    rewrite: Callable[[str, Callable[[str], str]], str]
    content_types: frozenset[str]  # defaults for the format's option, suffixes ("+json") included
    extensions: frozenset[str]  # fallback when the content type is not one of ours
    opt_in: bool = False  # True: off unless the loaded App Profile turns it on (rewrite_text)

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
    BodyFormat("json", rewrite_json, frozenset({"application/json", "+json"}), frozenset({".json"})),
    BodyFormat("xml", rewrite_xml, GENERIC_XML | {"+xml"}, frozenset({".xml"})),  # VAST, ad responses
    # HTML, JS, plain text and any other text type no format above claims.
    BodyFormat(
        "text",
        rewrite_text,
        frozenset({"text/*", "application/javascript", "application/x-javascript", "application/ecmascript"}),
        frozenset(),
        opt_in=True,
    ),
)


def _format_tables(formats):
    """(content type or suffix -> format, extension -> format) from the options of
    `formats`. On a clash, the format listed first in FORMATS wins."""
    by_content_type, by_extension = {}, {}
    for body_format in formats:
        for entry in getattr(ctx.options, body_format.option):
            entry = entry.strip().lower()
            if len(entry) > 1 and entry.startswith("."):
                by_extension.setdefault(entry, body_format)
            elif "/" in entry or (len(entry) > 1 and entry.startswith("+")):
                by_content_type.setdefault(entry, body_format)
            else:
                raise OptionsError(
                    f"{body_format.option}: {entry!r} is neither a content type "
                    '("application/json"), a suffix ("+json") nor a URL extension (".json")'
                )
    return by_content_type, by_extension


def body_format(flow):
    """The name of the format the BodyRewriter chose for `flow`'s response ("hls", ...), or None."""
    return flow.metadata.get("body_format")


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
    def __init__(self, app_profile):
        self.app_profile = app_profile  # its rewrites_text turns the opt-in formats on
        self.by_content_type, self.by_extension = {}, {}

    def load(self, loader):
        for body_format in FORMATS:
            loader.add_option(
                body_format.option, Sequence[str],
                sorted(body_format.content_types | body_format.extensions),
                f"Content types, suffixes (\"+json\") and URL extensions (\".ext\") whose "
                f"response bodies get the {body_format.name} rewriter (\"text/*\" covers "
                "every text/ type). "
                "Empty turns it off.",
            )

    def configure(self, updated):
        if "lab_app" in updated or any(body_format.option in updated for body_format in FORMATS):
            formats = [f for f in FORMATS if not f.opt_in or self.app_profile.rewrites_text]
            self.by_content_type, self.by_extension = _format_tables(formats)

    def body_format_for(self, content_type, url):
        """The format whose rewriter applies, chosen by content type, falling back to
        the URL extension, then to the type's structured-syntax suffix ("+json"), then
        to a whole family ("text/*"); None means the body passes through untouched.

        A generic XML content type only says "some XML", so a format the URL extension
        names (a DASH .mpd served as text/xml) wins over it.
        """
        media_type = content_type.split(";")[0].strip().lower()
        extension = PurePosixPath(urlsplit(url).path).suffix.lower()
        by_type = self.by_content_type.get(media_type)
        by_extension = self.by_extension.get(extension)
        by_suffix = self.by_content_type.get(f"+{media_type.rpartition('+')[2]}") if "+" in media_type else None
        by_family = self.by_content_type.get(f"{media_type.partition('/')[0]}/*")
        if media_type in GENERIC_XML:
            return by_extension or by_type
        return by_type or by_extension or by_suffix or by_family

    def response(self, flow):
        chosen = self.body_format_for(flow.response.headers.get("content-type", ""), flow.request.url)
        if chosen is not None:
            flow.metadata["body_format"] = chosen.name  # e.g. "hls", for manifest edits: see body_format
        if client_proxy_base(flow) is None or chosen is None:
            return  # not Prefixed, or binary/unknown content: never decoded, passes byte for byte
        body = flow.response.text  # decoded: compression is mitmproxy's job
        rewritten = chosen.rewrite(body, lab_link(flow))
        if rewritten != body:
            flow.response.text = rewritten  # re-encoded with the original Content-Encoding
