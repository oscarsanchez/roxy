"""CA Routing (phase 2): a Physical Device whose DNS points lab Origins at the Mac
calls Origin URLs directly. The Origin comes from Host, else SNI."""

import pytest
from mitmproxy.test import tutils

from chain import TUNNEL_LISTENER, TUNNEL_OPTIONS, fixture_response, lab_flow, origin_json, run_chain


ORIGIN_HOST = "httpbin.org"


def ca_routed_flow(path, host_header=ORIGIN_HOST, sni=ORIGIN_HOST, tls=True, peer=None):
    """An Origin URL request as the lab's 443 (TLS) or 80 listener sees it."""
    flow = lab_flow(path, host_header=host_header or "", **({"peer": peer} if peer else {}))
    flow.client_conn.tls = tls
    flow.client_conn.sni = sni if tls else None
    if host_header is None:
        del flow.request.headers["host"]
    return flow



def run(flow, origin_response=None, **options):
    return run_chain(flow, origin_response or origin_json(), lab_ca_routing=True, **options)


def test_an_origin_url_over_tls_is_forwarded_to_that_origin():
    flow = ca_routed_flow("/json")

    forwarded = run(flow)

    assert forwarded.url == "https://httpbin.org/json"
    assert forwarded.headers["host"] == "httpbin.org"
    assert flow.response.status_code == 200


def test_an_http2_request_reaches_the_origin_without_connection_specific_headers():
    """A Roku speaks HTTP/2 to the lab's TLS listener. HTTP/2 forbids Connection
    (RFC 9113 8.2.2): httpbin.org's load balancer dropped such requests (502)."""
    flow = ca_routed_flow("/json", host_header=None)
    flow.request.http_version = "HTTP/2.0"
    flow.request.authority = ORIGIN_HOST

    forwarded = run(flow)

    assert forwarded.url == "https://httpbin.org/json"
    assert "connection" not in forwarded.headers
    assert flow.response.status_code == 200


def test_without_a_host_header_the_origin_comes_from_sni():
    flow = ca_routed_flow("/json", host_header=None, sni="httpbin.org")

    forwarded = run(flow)

    assert forwarded.url == "https://httpbin.org/json"
    assert forwarded.headers["host"] == "httpbin.org"


def test_plain_http_on_port_80_keeps_the_http_scheme():
    flow = ca_routed_flow("/get?x=1", tls=False)

    forwarded = run(flow)

    assert forwarded.url == "http://httpbin.org/get?x=1"


def test_a_prefixed_url_is_still_decoded_when_ca_routing_is_on():
    flow = lab_flow("/https://httpbin.org/redirect/1")

    forwarded = run(flow, tutils.tresp(status_code=302, headers=((b"location", b"https://httpbin.org/json"),)))

    assert forwarded.url == "https://httpbin.org/redirect/1"
    assert flow.response.headers["location"] == "http://192.0.2.10:8080/https://httpbin.org/json"


def test_with_ca_routing_off_an_origin_url_is_refused_as_not_prefixed():
    flow = ca_routed_flow("/json")

    forwarded = run_chain(flow, origin_json())

    assert forwarded is None
    assert flow.response.headers["X-Lab-Blocked"] == "not-prefixed"


def test_a_request_with_neither_host_nor_sni_is_refused_as_not_prefixed():
    flow = ca_routed_flow("/json", host_header=None, sni=None)

    forwarded = run(flow)

    assert forwarded is None
    assert flow.response.headers["X-Lab-Blocked"] == "not-prefixed"


def test_ca_routing_is_for_physical_devices_only_so_a_tunnel_request_must_still_be_prefixed():
    flow = ca_routed_flow("/json", tls=False, peer=("127.0.0.1", 52000))
    flow.client_conn.proxy_mode = TUNNEL_LISTENER
    flow.request.headers["CF-Connecting-IP"] = "44.239.29.169"

    forwarded = run(flow, **TUNNEL_OPTIONS)

    assert forwarded is None
    assert flow.response.headers["X-Lab-Blocked"] == "secret-segment"


@pytest.mark.parametrize(
    ("flow_args", "dns_answers", "reason"),
    [
        ({"peer": ("203.0.113.7", 51000)}, {}, "client-ip"),
        # The Mac's own DNS also points the Origin at the lab: forwarding would loop.
        ({}, {ORIGIN_HOST: ["192.0.2.10"]}, "origin-address"),
    ],
)
def test_every_guard_still_applies_to_a_ca_routed_request(dns, flow_args, dns_answers, reason):
    dns.update(dns_answers)
    flow = ca_routed_flow("/json", **flow_args)

    forwarded = run(flow)

    assert forwarded is None
    assert flow.response.status_code == 403
    assert flow.response.headers["X-Lab-Blocked"] == reason


def test_a_ca_routed_request_reaches_a_public_origin_not_on_the_allowlist():
    flow = ca_routed_flow("/json", host_header="not-allowlisted.example", sni="not-allowlisted.example")

    forwarded = run(flow)

    assert forwarded.url == "https://not-allowlisted.example/json"


def test_a_redirect_location_is_left_as_an_origin_url():
    """The client calls Origin URLs directly; DNS already brings them back to the lab."""
    flow = ca_routed_flow("/redirect-to?url=%2Fjson")

    run(flow, tutils.tresp(status_code=302, headers=((b"location", b"https://httpbin.org/json"),)))

    assert flow.response.headers["location"] == "https://httpbin.org/json"


def test_body_urls_are_left_as_origin_urls():
    flow = ca_routed_flow("/products", host_header="dummyjson.com", sni="dummyjson.com")
    origin = fixture_response("catalog.json", "application/json")
    body = origin.content

    run(flow, origin)

    assert flow.response.content == body


def test_scenarios_apply_to_ca_routed_requests(tmp_path):
    (tmp_path / "fail-json.toml").write_text(
        '[[rule]]\nname = "json fails"\nfilter = "~d httpbin.org & ~u /json"\nstatus = 503\n'
    )
    flow = ca_routed_flow("/json")

    run(flow, lab_scenarios_dir=str(tmp_path), lab_scenario="fail-json")

    assert flow.response.status_code == 503
