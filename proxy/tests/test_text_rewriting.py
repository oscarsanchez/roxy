"""The text format: every absolute http(s) URL in a text body (HTML, JS, plain text,
unknown text types) becomes a Prefixed URL. Off by default; an App Profile turns it on
with "rewrite_text": true in its profile.json."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import LAN_PROXY_BASE, lab_flow, run_chain

ORIGIN_URL = "https://www.example.com/app/index.html"
PAGE = (
    '<script src="https://cdn.example.com/app.js"></script>\n'
    '<a href="http://example.org/a?b=1&c=2">next</a> <img src="/img/logo.png">\n'
    'fetch(`https://api.example.net/v1/items`); see https://example.org/help.\n'
)


def client_body(content_type, body=PAGE, separator="/", **options):
    flow = lab_flow(f"{separator}{ORIGIN_URL}")
    origin = tutils.tresp(headers=http.Headers(content_type=content_type), content=body.encode())
    run_chain(flow, origin, **options)
    return flow.response.content.decode()


@pytest.mark.parametrize(
    "content_type",
    ["text/html; charset=utf-8", "application/javascript", "text/plain", "text/x-made-up"],
)
@pytest.mark.parametrize("separator", ["/", "/;"])
def test_with_the_profile_switch_on_absolute_urls_in_a_text_body_become_prefixed_urls(
    app_profile, content_type, separator
):
    app_profile("example-app", rewrite_text=True)

    body = client_body(content_type, separator=separator, lab_app="example-app")

    lab = f"{LAN_PROXY_BASE}{separator}"
    assert body == (
        f'<script src="{lab}https://cdn.example.com/app.js"></script>\n'
        f'<a href="{lab}http://example.org/a?b=1&c=2">next</a> <img src="/img/logo.png">\n'
        f"fetch(`{lab}https://api.example.net/v1/items`); see {lab}https://example.org/help.\n"
    )


@pytest.mark.parametrize("keys", [None, {}, {"rewrite_text": False}])
def test_with_the_switch_off_a_text_body_reaches_the_client_untouched(app_profile, keys):
    options = {}
    if keys is not None:  # None: no App Profile loaded
        app_profile("example-app", **keys)
        options["lab_app"] = "example-app"

    assert client_body("text/html", **options) == PAGE


@pytest.mark.parametrize("content_type", ["image/jpeg", "application/octet-stream", "video/MP2T", ""])
def test_with_the_switch_on_a_binary_body_passes_through_byte_for_byte(app_profile, content_type):
    app_profile("example-app", rewrite_text=True)
    body = b"\x47\x40\x00\x10\xff\xfe\nhttps://cdn.example.com/x.ts\n\x00\x80"
    flow = lab_flow(f"/{ORIGIN_URL}")
    origin = tutils.tresp(headers=http.Headers(content_type=content_type), content=body)

    run_chain(flow, origin, lab_app="example-app")

    assert flow.response.raw_content == body


def test_a_text_body_another_format_claims_keeps_that_formats_rewriter(app_profile):
    """A playlist served as text/plain is HLS by its extension: its root-relative URI line
    is resolved and prefixed, which the text format would leave alone."""
    app_profile("example-app", rewrite_text=True)
    flow = lab_flow("/https://media.example.com/live/master.m3u8")
    origin = tutils.tresp(headers=http.Headers(content_type="text/plain"), content=b"#EXTM3U\n/live/720p.m3u8\n")

    run_chain(flow, origin, lab_app="example-app")

    assert flow.response.text == f"#EXTM3U\n{LAN_PROXY_BASE}/https://media.example.com/live/720p.m3u8\n"


@pytest.mark.parametrize("separator", ["/", "/;"])
def test_a_url_already_prefixed_for_this_client_is_not_prefixed_again(app_profile, separator):
    app_profile("example-app", rewrite_text=True)
    body = f'<a href="{LAN_PROXY_BASE}/;https://example.org/a">'

    assert client_body("text/html", body, separator, lab_app="example-app") == (
        f'<a href="{LAN_PROXY_BASE}{separator}https://example.org/a">'
    )


@pytest.mark.parametrize(
    "after",
    [".", ",", ";", ":", "!", "?", ")", "]", "}", "&quot;", "&#39;", "&gt;", ").", "&quot;,", "?)"],
)
@pytest.mark.parametrize("separator", ["/", "/;"])
def test_punctuation_or_an_entity_after_a_url_stays_outside_its_prefixed_url(app_profile, after, separator):
    app_profile("example-app", rewrite_text=True)
    body = f"(see https://example.org/a/b?c=1{after} next)"

    assert client_body("text/html", body, separator, lab_app="example-app") == (
        f"(see {LAN_PROXY_BASE}{separator}https://example.org/a/b?c=1{after} next)"
    )


@pytest.mark.parametrize("separator", ["/", "/;"])
def test_a_parenthesis_ends_a_url_so_each_css_background_url_is_prefixed(app_profile, separator):
    app_profile("example-app", rewrite_text=True)
    body = "background: url(https://cdn.example.com/a.png),url(https://cdn.example.com/b.png);"

    lab = f"{LAN_PROXY_BASE}{separator}"
    assert client_body("text/css", body, separator, lab_app="example-app") == (
        f"background: url({lab}https://cdn.example.com/a.png),url({lab}https://cdn.example.com/b.png);"
    )


@pytest.mark.parametrize("separator", ["/", "/;"])
def test_a_closing_bracket_the_url_opens_stays_inside_it(app_profile, separator):
    app_profile("example-app", rewrite_text=True)
    body = "[https://example.org/a[0]]. {https://example.org/b{1}}"

    lab = f"{LAN_PROXY_BASE}{separator}"
    assert client_body("text/plain", body, separator, lab_app="example-app") == (
        f"[{lab}https://example.org/a[0]]. {{{lab}https://example.org/b{{1}}}}"
    )


@pytest.mark.parametrize("entity", ["&quot;", "&#39;", "&#34;", "&gt;", "&lt;"])
@pytest.mark.parametrize("separator", ["/", "/;"])
def test_an_entity_ends_a_url_so_the_url_after_it_is_prefixed_too(app_profile, entity, separator):
    """JSON in an HTML attribute: its quotes are entities, with no space between URLs."""
    app_profile("example-app", rewrite_text=True)
    body = f"<div data-urls='[{entity}https://cdn.example.com/a.js{entity},{entity}https://cdn.example.com/b.js{entity}]'>"

    lab = f"{LAN_PROXY_BASE}{separator}"
    assert client_body("text/html", body, separator, lab_app="example-app") == (
        f"<div data-urls='[{entity}{lab}https://cdn.example.com/a.js{entity},"
        f"{entity}{lab}https://cdn.example.com/b.js{entity}]'>"
    )
