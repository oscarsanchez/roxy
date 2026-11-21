"""Regression tests for common Charles-hook patterns: URLs a Charles Rewrite set
re-points at the proxy by hand, which roxy handles with no rule, in either separator.
Hosts are documentation hosts."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import LAN_PROXY_BASE, lab_flow, run_chain

SEPARATORS = pytest.mark.parametrize("separator", ["/", "/;"])


@SEPARATORS
def test_root_relative_hls_lines_and_uri_attributes_become_prefixed_urls_on_the_origins_host(separator):
    flow = lab_flow(f"{separator}https://video.example.net/live/channel-1/master.m3u8?token=abc")
    playlist = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="en",URI="/live/channel-1/audio/en.m3u8"\n'
        '#EXT-X-KEY:METHOD=AES-128,URI="/keys/channel-1?kid=7"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=2000000,AUDIO="aud"\n'
        "/live/channel-1/720p/index.m3u8\n"
    )
    origin = tutils.tresp(headers=http.Headers(content_type="application/x-mpegURL"), content=playlist.encode())

    run_chain(flow, origin)

    lab = f"{LAN_PROXY_BASE}{separator}https://video.example.net"
    assert flow.response.text == (
        "#EXTM3U\n"
        f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="en",URI="{lab}/live/channel-1/audio/en.m3u8"\n'
        f'#EXT-X-KEY:METHOD=AES-128,URI="{lab}/keys/channel-1?kid=7"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=2000000,AUDIO="aud"\n'
        f"{lab}/live/channel-1/720p/index.m3u8\n"
    )


@SEPARATORS
@pytest.mark.parametrize(
    "location, origin_url",
    [
        ("/auth/session?next=home", "https://api.example.org/auth/session?next=home"),
        ("../v2/catalog", "https://api.example.org/v2/catalog"),
    ],
)
def test_a_relative_location_becomes_a_prefixed_url_on_the_origins_host(separator, location, origin_url):
    flow = lab_flow(f"{separator}https://api.example.org/v1/login")

    run_chain(flow, tutils.tresp(status_code=302, headers=http.Headers(location=location), content=b""))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}{separator}{origin_url}"
