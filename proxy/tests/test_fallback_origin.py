"""A fallback Origin (App Profile `fallback_origin`): a bare path on a LAN listener, which
names no Origin, is treated as if Prefixed with the profile's Origin and the client's
Proxy Base, in the `/;` form, when its path matches the profile's regex."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import SECRET, TUNNEL_OPTIONS, assert_refused, lab_flow, origin_json, run_chain, tunnel_flow

CDN = "https://cdn.example"
# A Charles hook's leftover: a root-relative manifest line the app resolved against the
# proxy port, so the lab sees the CDN's path with no Origin in front of it.
MANIFEST_PATH = "/live/abc123/hls/index.m3u8?token=a%2Fb&x="


@pytest.fixture
def fallback(app_profile):
    """Lab options loading an App Profile whose fallback Origin is CDN, for /live/<id>/hls/ paths."""
    app_profile("example-app", fallback_origin={"path": r"^/live/[^/]+/hls/", "origin": CDN})
    return {"lab_app": "example-app"}


def test_a_matching_bare_path_reaches_the_fallback_origin_with_its_path_and_query(fallback):
    flow = lab_flow(MANIFEST_PATH)

    forwarded = run_chain(flow, origin_json(), **fallback)

    assert forwarded.url == f"{CDN}{MANIFEST_PATH}"
    assert forwarded.headers["host"] == "cdn.example"


def test_its_manifest_comes_back_prefixed_in_the_charles_form(fallback):
    """The Charles pattern: a bare /live/…/hls/… path on the proxy port goes to the CDN, and
    the manifest's lines come back as Prefixed URLs with `/;`, so the segments come back too."""
    flow = lab_flow(MANIFEST_PATH, host_header="192.0.2.10:8888")

    run_chain(flow, manifest(
        "#EXTM3U\n"
        "#EXTINF:6,\n/live/abc123/hls/seg-1.ts\n"
        "#EXTINF:6,\nhttps://cdn-2.example/vod/abc123/seg-2.ts\n"
    ), **fallback)

    assert flow.response.text.splitlines()[2::2] == [
        "http://192.0.2.10:8888/;https://cdn.example/live/abc123/hls/seg-1.ts",
        "http://192.0.2.10:8888/;https://cdn-2.example/vod/abc123/seg-2.ts",
    ]


@pytest.mark.parametrize("path", ["/favicon.ico", "/vod/abc123/index.m3u8", "/"])
def test_a_bare_path_the_regex_does_not_match_is_still_refused(fallback, path):
    flow = lab_flow(path)

    assert_refused(flow, run_chain(flow, origin_json(), **fallback), "not-prefixed", status=400)


def test_without_a_fallback_origin_a_matching_bare_path_is_refused(app_profile):
    app_profile("example-app")
    flow = lab_flow(MANIFEST_PATH)

    assert_refused(flow, run_chain(flow, origin_json(), lab_app="example-app"), "not-prefixed", status=400)


def test_the_guards_refuse_a_fallback_origin_with_a_private_address(fallback, dns):
    dns["cdn.example"] = ["10.0.0.20"]
    flow = lab_flow(MANIFEST_PATH)

    assert_refused(flow, run_chain(flow, origin_json(), **fallback), "origin-address")


def test_the_guards_refuse_a_lan_client_outside_the_lan_subnets(fallback):
    flow = lab_flow(MANIFEST_PATH, peer=("203.0.113.9", 51000))

    assert_refused(flow, run_chain(flow, origin_json(), **fallback), "client-ip")


@pytest.mark.parametrize("path", [MANIFEST_PATH, f"/{SECRET}{MANIFEST_PATH}"])
def test_the_public_endpoint_takes_no_fallback_even_for_an_allowlisted_host(app_profile, path):
    """A Cloud Device must send a Prefixed URL behind the secret: the Public Endpoint never
    guesses an Origin, so nothing reaches the fallback Origin around its guards."""
    app_profile(
        "example-app", origin_allowlist=["cdn.example"],
        fallback_origin={"path": r"^/live/[^/]+/hls/", "origin": CDN},
    )
    flow = tunnel_flow(path)

    assert_refused(flow, run_chain(flow, origin_json(), lab_app="example-app", **TUNNEL_OPTIONS), "secret-segment")


def manifest(text):
    return tutils.tresp(headers=http.Headers(content_type="application/vnd.apple.mpegurl"), content=text.encode())
