"""The Public Endpoint: Cloud Device requests that arrive through the local tunnel."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import (
    LAN_LISTENER,
    SECRET,
    TUNNEL_HOST,
    TUNNEL_OPTIONS,
    assert_refused,
    fixture_response,
    lab_flow,
    origin_json,
    run_chain,
    tunnel_flow,
)


def run(flow, origin_response=None, **options):
    options = {**TUNNEL_OPTIONS, **options}
    return run_chain(flow, origin_response or origin_json(), **options)



def test_a_cloud_device_request_with_the_secret_from_an_rce_egress_ip_reaches_its_origin():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json")

    forwarded = run(flow)

    assert forwarded.url == "https://httpbin.org/json"
    assert flow.response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/https://httpbin.org/json",  # no secret segment
        "/wrong-secret/https://httpbin.org/json",
        f"/{SECRET}x/https://httpbin.org/json",
    ],
)
def test_a_cloud_device_request_without_the_right_secret_is_refused(path):
    flow = tunnel_flow(path)

    assert_refused(flow, run(flow), "secret-segment")


@pytest.mark.parametrize("path", ["/", "/json", "/favicon.ico", "/wp-login.php?x=1"])
def test_a_tunnel_request_that_is_not_a_prefixed_url_is_refused_for_the_secret_not_as_not_prefixed(path):
    # A scanner on the Public Endpoint learns nothing about what the lab is.
    flow = tunnel_flow(path)

    assert_refused(flow, run(flow), "secret-segment")


def test_with_no_secret_configured_every_tunnel_request_is_refused():
    flow = tunnel_flow("/https://httpbin.org/json")

    assert_refused(flow, run(flow, lab_secret=""), "secret-segment")


@pytest.mark.parametrize("client_ip", ["8.8.8.8", "192.0.2.54", "not-an-ip", ""])
def test_a_cloud_device_request_from_a_client_ip_other_than_the_rce_egress_ips_is_refused(client_ip):
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", client_ip=client_ip)

    assert_refused(flow, run(flow), "client-ip")


def test_a_tunnel_request_without_the_client_ip_header_is_refused():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json")
    del flow.request.headers["CF-Connecting-IP"]

    assert_refused(flow, run(flow), "client-ip")


def test_every_rce_egress_ip_ships_in_the_default_list():
    # Roku's published list (docs/DEVELOPER/rce/index.md, Prerequisites).
    published = [
        "44.239.29.169", "34.209.122.192", "54.202.182.128", "100.21.142.143", "34.210.16.174",
        "34.215.23.153", "35.160.218.63", "35.81.125.176", "54.188.9.148",
    ]
    for client_ip in published:
        flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", client_ip=client_ip)
        assert run(flow) is not None, client_ip


def test_the_rce_egress_ips_are_set_in_config():
    added = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", client_ip="203.0.113.7")
    removed = tunnel_flow(f"/{SECRET}/https://httpbin.org/json")

    assert run(added, lab_rce_egress_ips=["203.0.113.7"]) is not None
    assert_refused(removed, run(removed, lab_rce_egress_ips=["203.0.113.7"]), "client-ip")


def test_under_compose_cloudflared_reaches_the_tunnel_listener_from_its_own_container_ip():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", peer=("172.18.0.3", 52000))

    assert run(flow).url == "https://httpbin.org/json"


def test_a_loopback_client_on_the_lan_listener_is_not_a_tunnel_request():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", peer=("127.0.0.1", 4000), listener=LAN_LISTENER)

    assert_refused(flow, run(flow), "client-ip")


def test_without_a_tunnel_listener_no_request_is_a_tunnel_request():
    flow = tunnel_flow("/https://httpbin.org/json", client_ip="8.8.8.8", peer=("192.0.2.54", 4000))

    assert run(flow, lab_tunnel_port=0).url == "https://httpbin.org/json"


def test_a_lan_client_cannot_spoof_an_rce_egress_ip_with_the_tunnel_header():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", peer=("10.9.9.9", 4000), listener=LAN_LISTENER)

    assert_refused(flow, run(flow), "client-ip")


def test_a_lan_client_sending_the_tunnel_header_is_judged_by_its_real_ip():
    flow = tunnel_flow(
        "/https://httpbin.org/json", client_ip="8.8.8.8", peer=("192.0.2.54", 4000), listener=LAN_LISTENER
    )

    assert run(flow).url == "https://httpbin.org/json"


TUNNEL_AND_FORWARDING_HEADERS = [
    "CF-Connecting-IP", "CF-Connecting-IPv6", "CF-IPCountry", "CF-Ray", "CF-Visitor", "Cf-Warp-Tag-Id",
    "Cf-Access-Jwt-Assertion", "CDN-Loop", "X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host",
    "Forwarded", "X-Real-IP", "True-Client-IP", "Via",
]


def test_tunnel_and_forwarding_headers_never_reach_the_origin():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json")
    for name in TUNNEL_AND_FORWARDING_HEADERS:
        flow.request.headers.setdefault(name, "x")
    flow.request.headers["User-Agent"] = "Roku/DVP-15.2"

    forwarded = run(flow)

    assert [name for name in TUNNEL_AND_FORWARDING_HEADERS if name in forwarded.headers] == []
    assert forwarded.headers["User-Agent"] == "Roku/DVP-15.2"  # the device's own headers stay


def test_a_refused_tunnel_request_keeps_the_client_ip_header_in_mitmweb_to_show_who_was_refused():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", client_ip="8.8.8.8")

    run(flow)

    assert flow.request.headers["CF-Connecting-IP"] == "8.8.8.8"


def test_forwarding_headers_from_a_lan_client_never_reach_the_origin_either():
    flow = lab_flow("/https://httpbin.org/json")
    flow.request.headers.update({"X-Forwarded-For": "1.2.3.4", "CF-Connecting-IP": "1.2.3.4"})

    forwarded = run(flow)

    assert "X-Forwarded-For" not in forwarded.headers
    assert "CF-Connecting-IP" not in forwarded.headers


PUBLIC_PROXY_BASE = f"https://{TUNNEL_HOST}/{SECRET}"  # the tunnel's https, as the Cloud Device saw it


def test_a_redirect_for_a_cloud_device_points_at_the_public_endpoint():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/redirect-to?url=%2Fjson")

    run(flow, tutils.tresp(status_code=302, headers=http.Headers(location="/json"), content=b""))

    assert flow.response.headers["Location"] == f"{PUBLIC_PROXY_BASE}/https://httpbin.org/json"


def test_a_cloud_device_with_a_device_slug_reaches_its_origin_and_keeps_the_slug_in_rewritten_urls():
    flow = tunnel_flow(f"/{SECRET}/cloud-device/https://httpbin.org/redirect-to?url=%2Fjson")

    forwarded = run(flow, tutils.tresp(status_code=302, headers=http.Headers(location="/json"), content=b""))

    assert forwarded.url == "https://httpbin.org/redirect-to?url=%2Fjson"
    assert flow.response.headers["Location"] == f"{PUBLIC_PROXY_BASE}/cloud-device/https://httpbin.org/json"


def test_a_device_slug_does_not_stand_in_for_the_secret():
    flow = tunnel_flow("/cloud-device/https://httpbin.org/json")

    assert_refused(flow, run(flow), "secret-segment")


def test_a_playlist_for_a_cloud_device_points_at_the_public_endpoint():
    flow = tunnel_flow(f"/{SECRET}/https://stream.mux.com/videos/master.m3u8")

    run(flow, fixture_response("hls-master.m3u8", "application/vnd.apple.mpegurl"))

    lines = flow.response.text.splitlines()
    assert f"{PUBLIC_PROXY_BASE}/https://stream.mux.com/videos/gear2/prog_index.m3u8" in lines
    assert not any("192.0.2.10" in line for line in lines)


def test_a_lan_client_keeps_the_lan_proxy_base_whatever_forwarding_headers_it_sends():
    flow = lab_flow("/https://httpbin.org/redirect-to?url=%2Fjson")
    flow.request.headers["X-Forwarded-Proto"] = "https"

    run(flow, tutils.tresp(status_code=302, headers=http.Headers(location="/json"), content=b""))

    assert flow.response.headers["Location"] == "http://192.0.2.10:8080/https://httpbin.org/json"
