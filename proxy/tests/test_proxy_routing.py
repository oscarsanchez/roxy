"""Proxy Routing: a Mobile Device sets the lab's Proxy Routing listener as its HTTP
proxy, so its requests arrive as the Origin URLs they are. No Proxy Base, no Prefixed URLs."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import (
    PROXY_ROUTING_OPTIONS,
    Lab,
    assert_refused,
    fixture_response,
    flows_summary,
    lab_flow,
    origin_json,
    proxy_routing_connect,
    proxy_routing_flow,
    run_chain,
)


def run(flow, origin_response=None, **options):
    return run_chain(flow, origin_response or origin_json(), **PROXY_ROUTING_OPTIONS, **options)


def test_a_request_reaches_its_own_origin():
    flow = proxy_routing_flow("https://httpbin.org/json?x=1")

    forwarded = run(flow)

    assert forwarded.url == "https://httpbin.org/json?x=1"
    assert forwarded.headers["host"] == "httpbin.org"
    assert flow.response.status_code == 200


def test_a_redirect_location_is_left_as_an_origin_url():
    flow = proxy_routing_flow("https://httpbin.org/redirect/1")

    run(flow, tutils.tresp(status_code=302, headers=((b"location", b"https://httpbin.org/json"),)))

    assert flow.response.headers["location"] == "https://httpbin.org/json"


def test_body_urls_are_left_as_origin_urls():
    flow = proxy_routing_flow("https://dummyjson.com/products")
    origin = fixture_response("catalog.json", "application/json")
    body = origin.content

    run(flow, origin)

    assert flow.response.content == body


def test_a_rule_with_placeholders_leaves_it_alone(scenarios):
    options = scenarios("media-host", '''
[[rule]]
name = "cdn through the lab"
filter = "~s & ~d api.example.com"
body = { pattern = 'mediaHost="', replacement = 'mediaHost="{proxy_base_no_scheme}{separator}https://' }
''')
    flow = proxy_routing_flow("https://api.example.com/config.xml")
    origin = tutils.tresp(
        headers=http.Headers(content_type="application/xml"),
        content=b'<config mediaHost="cdn.example.com/media"/>',
    )

    run(flow, origin, **options)

    assert flow.response.text == '<config mediaHost="cdn.example.com/media"/>'


def test_a_prefixed_looking_path_is_an_ordinary_origin_path():
    flow = proxy_routing_flow("http://api.example.com/https://httpbin.org/json")

    forwarded = run(flow)

    assert forwarded.url == "http://api.example.com/https://httpbin.org/json"
    assert forwarded.headers["host"] == "api.example.com"


def test_a_client_outside_the_lan_subnets_is_refused():
    flow = proxy_routing_flow("https://httpbin.org/json", peer=("203.0.113.7", 51000))

    assert_refused(flow, run(flow), "client-ip")


def test_a_client_outside_the_lan_subnets_gets_no_tunnel():
    """Refused at its CONNECT: no TLS or raw TCP through the lab, whatever it sends next."""
    flow = proxy_routing_connect("httpbin.org:443", peer=("203.0.113.7", 51000))

    with Lab(**PROXY_ROUTING_OPTIONS) as lab:
        opened = lab.http_connect(flow)

    assert not opened
    assert flow.response.status_code == 403
    assert flow.response.headers["X-Lab-Blocked"] == "client-ip"


def test_a_lan_client_gets_its_tunnel():
    flow = proxy_routing_connect("httpbin.org:443")

    with Lab(**PROXY_ROUTING_OPTIONS) as lab:
        assert lab.http_connect(flow)


def test_a_status_scenario_acts_on_it_and_shows_in_the_flows_summary(scenarios):
    options = scenarios("json-503", '[[rule]]\nname = "json fails"\nfilter = "~d httpbin.org & ~u /json"\nstatus = 503\n')
    flow = proxy_routing_flow("https://httpbin.org/json")

    run(flow, **options)

    assert flow.response.status_code == 503
    [summary] = flows_summary(flow)
    assert (summary["url"], summary["status"]) == ("https://httpbin.org/json", 503)
    assert summary["scenario_rules"] == ["json-503/json fails"]


def test_a_map_local_scenario_answers_it_and_shows_in_the_flows_summary(scenarios, tmp_path):
    (tmp_path / "mocks").mkdir()
    (tmp_path / "mocks" / "empty.json").write_text('{"slideshow": null}')
    options = scenarios("mock-json", '[[rule]]\nname = "json is mocked"\nfilter = "~u /json"\nmap_local = "mocks/empty.json"\n')
    flow = proxy_routing_flow("https://httpbin.org/json")

    forwarded = run(flow, **options)

    assert forwarded is None
    assert flow.response.content == b'{"slideshow": null}'
    [summary] = flows_summary(flow)
    assert (summary["url"], summary["status"]) == ("https://httpbin.org/json", 200)
    assert summary["scenario_rules"] == ["mock-json/json is mocked"]


def test_a_private_origin_is_refused(dns):
    dns["router.example"] = ["192.0.2.1"]
    flow = proxy_routing_flow("http://router.example/admin")

    assert_refused(flow, run(flow), "origin-address")


def test_a_public_origin_off_the_allowlist_is_forwarded():
    flow = proxy_routing_flow("https://not-allowlisted.example/json")

    forwarded = run(flow, lab_origin_allowlist=["httpbin.org"])

    assert forwarded.url == "https://not-allowlisted.example/json"
    assert not flow.marked


THIS_MAC = {"IPv4": ("127.0.0.1", 51000), "IPv6": ("::1", 51000, 0, 0)}  # an iOS Simulator or Android Emulator


@pytest.mark.parametrize("peer", THIS_MAC.values(), ids=THIS_MAC.keys())
def test_a_mobile_device_on_this_mac_is_forwarded_and_named_this_mac(peer):
    flow = proxy_routing_flow("https://httpbin.org/json", peer=peer)

    forwarded = run(flow)

    assert forwarded.url == "https://httpbin.org/json"
    assert flow.comment == "This Mac"
    assert [summary["device"] for summary in flows_summary(flow)] == ["This Mac"]


@pytest.mark.parametrize("peer", THIS_MAC.values(), ids=THIS_MAC.keys())
def test_a_mobile_device_on_this_mac_gets_its_tunnel(peer):
    flow = proxy_routing_connect("httpbin.org:443", peer=peer)

    with Lab(**PROXY_ROUTING_OPTIONS) as lab:
        assert lab.http_connect(flow)


@pytest.mark.parametrize("peer", THIS_MAC.values(), ids=THIS_MAC.keys())
def test_this_mac_on_the_lan_listener_is_still_refused(peer):
    """Loopback is allowed on the Proxy Routing listener only."""
    flow = lab_flow("/https://httpbin.org/json", peer=peer)

    assert_refused(flow, run(flow), "client-ip")
