"""Nested Prefixed URLs: an app that prefixed a URL twice reaches the real Origin, marked
double-prefixed. Only a Prefixed URL nested with the client's own Proxy Base is unwrapped."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import (
    LAN_PROXY_BASE,
    SECRET,
    TUNNEL_HOST,
    TUNNEL_OPTIONS,
    assert_refused,
    flows_summary,
    lab_flow,
    origin_json,
    run_chain,
    tunnel_flow,
)

CLOUD_PROXY_BASE = f"https://{TUNNEL_HOST}/{SECRET}/cloud-device"  # settings.example/devices.json's slug


@pytest.mark.parametrize("outer, inner", [("/", "/"), ("/;", "/;"), ("/", "/;"), ("/;", "/")])
def test_a_nested_prefixed_url_for_this_client_in_either_form_reaches_the_real_origin_marked(outer, inner):
    flow = lab_flow(f"{outer}{LAN_PROXY_BASE}{inner}https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == "https://httpbin.org/json"
    assert forwarded.headers["host"] == "httpbin.org"
    assert flow.response.status_code == 200
    assert flow.comment == "Living Room | double-prefixed"
    [summary] = flows_summary(flow)
    assert (summary["url"], summary["double_prefixed"]) == ("https://httpbin.org/json", True)


def test_a_url_prefixed_three_times_reaches_the_real_origin_marked():
    flow = lab_flow(f"/{LAN_PROXY_BASE}/;{LAN_PROXY_BASE}/https://httpbin.org/json?a=1")

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == "https://httpbin.org/json?a=1"
    assert flow.comment == "Living Room | double-prefixed"


def test_a_nested_prefixed_url_through_the_public_endpoint_reaches_the_real_origin_marked():
    flow = tunnel_flow(f"/{SECRET}/cloud-device/{CLOUD_PROXY_BASE}/;https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json(), **TUNNEL_OPTIONS)

    assert forwarded.url == "https://httpbin.org/json"
    assert flow.comment == "Cloud Device | double-prefixed"
    assert [summary["double_prefixed"] for summary in flows_summary(flow)] == [True]


@pytest.mark.parametrize(
    "nested_base",
    [
        "http://192.0.2.10:8888",  # this Mac, another port
        "http://192.0.2.11:8080",  # another Mac
    ],
)
def test_a_nested_prefixed_url_with_another_proxy_base_is_refused_as_its_origin(dns, nested_base):
    """The lab never fetches through another proxy: the nested Proxy Base is the Origin."""
    host = nested_base.removeprefix("http://").split(":")[0]
    dns[host] = [host]  # an IP literal resolves to itself
    flow = lab_flow(f"/{nested_base}/https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json())

    assert_refused(flow, forwarded, "origin-address")
    assert [summary["double_prefixed"] for summary in flows_summary(flow)] == [False]


def test_a_nested_prefixed_url_with_another_cloud_devices_slug_is_refused_through_the_public_endpoint():
    flow = tunnel_flow(f"/{SECRET}/cloud-device/https://{TUNNEL_HOST}/{SECRET}/other-device/https://httpbin.org/json")

    assert_refused(flow, run_chain(flow, origin_json(), **TUNNEL_OPTIONS), "origin-host")


def test_a_prefixed_url_in_the_query_is_not_unwrapped():
    origin_url = f"https://httpbin.org/redirect-to?url={LAN_PROXY_BASE}/https://httpbin.org/json"
    flow = lab_flow(f"/{origin_url}")

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == origin_url
    assert [summary["double_prefixed"] for summary in flows_summary(flow)] == [False]


def test_a_private_real_origin_in_a_nested_prefixed_url_is_refused(dns):
    dns["router.example"] = ["192.0.2.200"]
    flow = lab_flow(f"/{LAN_PROXY_BASE}/http://router.example/admin")

    assert_refused(flow, run_chain(flow, origin_json()), "origin-address")


def test_urls_in_the_response_are_prefixed_once_in_the_form_the_client_used():
    flow = lab_flow(f"/;{LAN_PROXY_BASE}/https://httpbin.org/redirect/1")

    run_chain(flow, tutils.tresp(status_code=302, headers=http.Headers(location="/get"), content=b""))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}/;https://httpbin.org/get"


def test_a_scenario_rule_for_the_real_origin_acts_on_a_double_prefixed_flow(scenarios):
    options = scenarios("fail-json", '''
[[rule]]
name = "json fails"
filter = "~d httpbin.org & ~u /json"
status = 418
''')
    flow = lab_flow(f"/{LAN_PROXY_BASE}/https://httpbin.org/json")

    run_chain(flow, origin_json(), **options)

    assert flow.response.status_code == 418
    assert flow.comment == "Living Room | fail-json/json fails | double-prefixed"
    [summary] = flows_summary(flow)
    assert (summary["scenario_rules"], summary["double_prefixed"]) == (["fail-json/json fails"], True)


def test_an_ordinary_flow_is_not_double_prefixed():
    flow = lab_flow("/https://httpbin.org/json")

    run_chain(flow, origin_json())

    assert flow.comment == "Living Room"
    assert [summary["double_prefixed"] for summary in flows_summary(flow)] == [False]
