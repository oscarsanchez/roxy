import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import lab_flow, origin_json, run_chain


def test_prefixed_url_is_forwarded_to_its_origin_url():
    flow = lab_flow("/https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == "https://httpbin.org/json"
    assert forwarded.headers["host"] == "httpbin.org"
    assert flow.response.status_code == 200


def test_origin_scheme_port_path_and_query_are_kept_byte_for_byte():
    flow = lab_flow("/http://httpbin.org:8443/a//b%2Fc/json?x=1&y=%2F&z=")

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == "http://httpbin.org:8443/a//b%2Fc/json?x=1&y=%2F&z="
    assert forwarded.headers["host"] == "httpbin.org:8443"


def redirect_to(location):
    return tutils.tresp(status_code=302, headers=http.Headers(location=location), content=b"")


def test_urls_sent_back_carry_the_proxy_base_the_client_used():
    flow = lab_flow("/https://httpbin.org/redirect/1")

    run_chain(flow, redirect_to("https://httpbin.org/json"))

    assert flow.response.headers["location"] == "http://192.0.2.10:8080/https://httpbin.org/json"


def test_the_proxy_base_includes_a_secret_segment_when_present():
    flow = lab_flow("/s3cr3t/http://cdn.example:8443/a/seg.ts", host_header="lab.example")

    forwarded = run_chain(flow, redirect_to("/a/seg2.ts"), lab_origin_allowlist=["cdn.example"])

    assert forwarded.url == "http://cdn.example:8443/a/seg.ts"
    assert flow.response.headers["location"] == "http://lab.example/s3cr3t/http://cdn.example:8443/a/seg2.ts"


@pytest.mark.parametrize("path", ["/", "/json", "/favicon.ico", "/https://", "/ftp://httpbin.org/x"])
def test_a_request_that_is_not_a_prefixed_url_is_rejected_without_reaching_an_origin(path):
    flow = lab_flow(path)

    forwarded = run_chain(flow, origin_json())

    assert forwarded is None
    assert flow.response.status_code == 400
    assert flow.response.headers["X-Lab-Blocked"] == "not-prefixed"
    assert flow.marked


def test_a_client_collapsed_double_slash_is_tolerated():
    flow = lab_flow("/https:/httpbin.org/json")

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == "https://httpbin.org/json"
