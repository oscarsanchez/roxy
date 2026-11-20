"""Every URL the lab sends back keeps the separator the request arrived with:
"/" (the lab's own form) or "/;" (the Charles-style form, ADR-0002). A client
app's own "already prefixed?" check relies on it."""

import json

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import LAN_PROXY_BASE, fixture_response, lab_flow, run_chain

SEPARATORS = pytest.mark.parametrize("separator", ["/", "/;"])


def origin_response(status=200, headers=()):
    return tutils.tresp(status_code=status, headers=http.Headers(headers), content=b"")


def client_body(separator, origin_url, fixture, content_type):
    flow = lab_flow(f"{separator}{origin_url}")
    run_chain(flow, fixture_response(fixture, content_type))
    return flow.response.text


@SEPARATORS
def test_redirect_location_keeps_the_separator(separator):
    flow = lab_flow(f"{separator}https://httpbin.org/redirect/1")

    run_chain(flow, origin_response(302, [(b"location", b"/get")]))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}{separator}https://httpbin.org/get"


@SEPARATORS
def test_content_location_link_and_refresh_keep_the_separator(separator):
    flow = lab_flow(f"{separator}https://httpbin.org/page/1")

    run_chain(flow, origin_response(200, [
        (b"content-location", b"/page/1.json"),
        (b"link", b"</page/2>; rel=next"),
        (b"refresh", b"5; url=/page/3"),
    ]))

    base = f"{LAN_PROXY_BASE}{separator}https://httpbin.org"
    assert flow.response.headers["content-location"] == f"{base}/page/1.json"
    assert flow.response.headers["link"] == f"<{base}/page/2>; rel=next"
    assert flow.response.headers["refresh"] == f"5; url={base}/page/3"


@pytest.mark.parametrize(
    "separator, path",
    [
        ("/", "/https://httpbin.org/cookies"),
        # A cookie path cannot hold ";" (RFC 6265): the client would read "Path=/" and an
        # unknown attribute. The lab says "Path=/" itself, so the header stays well formed.
        ("/;", "/"),
    ],
)
def test_set_cookie_path_follows_the_separator(separator, path):
    flow = lab_flow(f"{separator}https://httpbin.org/cookies/set?x=1")

    run_chain(flow, origin_response(302, [(b"set-cookie", b"x=1; Domain=httpbin.org; Path=/cookies")]))

    assert flow.response.headers["set-cookie"] == f"x=1; Path={path}"


@SEPARATORS
def test_hls_variant_and_segment_uris_keep_the_separator(separator):
    master = client_body(
        separator, "https://stream.mux.com/videos/master.m3u8", "hls-master.m3u8", "application/vnd.apple.mpegurl"
    ).splitlines()
    media = client_body(
        separator, "https://stream.mux.com/v1/media.m3u8", "hls-media.m3u8", "application/vnd.apple.mpegurl"
    ).splitlines()

    assert (
        f"{LAN_PROXY_BASE}{separator}https://manifest.edgemv.mux.com/tok/rendition.m3u8"
        "?cdn=edgemv&expires=1700000000&skid=a1&signature=x%2Fy"
    ) in master
    assert f"{LAN_PROXY_BASE}{separator}https://stream.mux.com/v1/chunk/tok/1.ts" in media
    assert "3.ts" in media  # relative: resolves through the Prefixed URL as it is


@SEPARATORS
def test_dash_base_url_keeps_the_separator(separator):
    mpd = client_body(
        separator, "https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd", "dash.mpd", "application/dash+xml"
    )

    assert f"<BaseURL serviceLocation=\"cdn-a\">{LAN_PROXY_BASE}{separator}https://cdn-a.example.com/bbb/</BaseURL>" in mpd


@SEPARATORS
def test_vast_media_file_and_tracking_keep_the_separator(separator):
    vast = client_body(
        separator, "https://pubads.g.doubleclick.net/gampad/ads?output=vast", "vast-inline.xml", "text/xml"
    )

    assert (
        f"<![CDATA[{LAN_PROXY_BASE}{separator}https://redirector.gvt1.com/api/manifest/progressive/0f6b6bc4a2d5f4c0/18"
        "?id=0f6b&itag=18&source=dclk_video_ads]]>"
    ) in vast
    assert (
        f'<Tracking event="start"><![CDATA[{LAN_PROXY_BASE}{separator}https://pagead2.googlesyndication.com'
        "/pagead/interaction/?ai=B3qx&label=part2viewed&ad_mt=%5BAD_MT%5D]]></Tracking>"
    ) in vast


@SEPARATORS
def test_json_urls_keep_the_separator(separator):
    catalog = client_body(separator, "https://dummyjson.com/products?limit=1", "catalog.json", "application/json")

    assert json.loads(catalog)["products"][0]["thumbnail"] == (
        f"{LAN_PROXY_BASE}{separator}https://cdn.dummyjson.com/product-images/beauty/"
        "essence-mascara-lash-princess/thumbnail.webp"
    )


@pytest.mark.parametrize("name", ["referer", "origin"])
@SEPARATORS
def test_referer_and_origin_in_either_form_reach_the_origin_decoded(name, separator):
    flow = lab_flow("/;https://httpbin.org/json")
    flow.request.headers[name] = f"{LAN_PROXY_BASE}{separator}https://cdn.example/page?a=1"

    forwarded = run_chain(flow, origin_response())

    assert forwarded.headers[name] == "https://cdn.example/page?a=1"


@pytest.mark.parametrize("sent", ["/", "/;"])
@SEPARATORS
def test_a_url_already_prefixed_for_this_client_in_either_form_is_not_prefixed_again(sent, separator):
    """An Origin can echo a URL the app already prefixed (a tracking URL it was handed)."""
    flow = lab_flow(f"{separator}https://httpbin.org/anything")
    body = json.dumps({"url": f"{LAN_PROXY_BASE}{sent}https://cdn.example/a.ts"})

    run_chain(flow, tutils.tresp(headers=http.Headers(content_type="application/json"), content=body.encode()))

    assert json.loads(flow.response.text)["url"] == f"{LAN_PROXY_BASE}{separator}https://cdn.example/a.ts"


@pytest.mark.parametrize("recorded", ["/", "/;"])
@SEPARATORS
def test_a_replayed_redirect_recorded_in_either_form_is_reprefixed_once_in_the_current_form(recorded, separator):
    flow = lab_flow(f"{separator}https://httpbin.org/redirect/1")
    flow.is_replay = "response"
    location = f"http://rec.example{recorded}https://httpbin.org/get"

    run_chain(flow, origin_response(302, [(b"location", location.encode())]))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}{separator}https://httpbin.org/get"
