"""Request header cleanup and response header rewriting, through the full chain."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import LAN_PROXY_BASE, lab_flow, run_chain


def origin_response(status=200, headers=()):
    return tutils.tresp(status_code=status, headers=http.Headers(headers), content=b"")


@pytest.mark.parametrize("name", ["referer", "origin"])
def test_a_prefixed_url_in_referer_or_origin_is_turned_back_into_the_original_url(name):
    flow = lab_flow("/https://httpbin.org/json")
    flow.request.headers[name] = f"{LAN_PROXY_BASE}/https://cdn.example/page?a=1"

    forwarded = run_chain(flow, origin_response())

    assert forwarded.headers[name] == "https://cdn.example/page?a=1"


def test_a_referer_that_is_not_a_prefixed_url_is_forwarded_unchanged():
    flow = lab_flow("/https://httpbin.org/json")
    flow.request.headers["referer"] = "https://cdn.example/page"

    forwarded = run_chain(flow, origin_response())

    assert forwarded.headers["referer"] == "https://cdn.example/page"


def test_redirect_location_becomes_a_prefixed_url():
    flow = lab_flow("/https://httpbin.org/redirect-to?url=x")

    run_chain(flow, origin_response(302, [(b"location", b"https://httpbin.org/json")]))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}/https://httpbin.org/json"


@pytest.mark.parametrize(
    "location, origin_url",
    [
        ("/json", "https://httpbin.org/json"),
        ("get?a=1", "https://httpbin.org/redirect/get?a=1"),
        ("//cdn.example/x", "https://cdn.example/x"),
    ],
)
def test_a_relative_location_is_resolved_against_the_origin_url_first(location, origin_url):
    flow = lab_flow("/https://httpbin.org/redirect/1")

    run_chain(flow, origin_response(302, [(b"location", location.encode())]))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}/{origin_url}"


@pytest.mark.parametrize("status", [201, 301, 302, 303, 307, 308])
def test_location_is_rewritten_on_redirects_and_created(status):
    flow = lab_flow("/https://httpbin.org/anything")

    run_chain(flow, origin_response(status, [(b"location", b"/next")]))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}/https://httpbin.org/next"


def test_location_on_other_statuses_is_left_alone():
    flow = lab_flow("/https://httpbin.org/anything")

    run_chain(flow, origin_response(200, [(b"location", b"/next")]))

    assert flow.response.headers["location"] == "/next"


def test_content_location_becomes_a_prefixed_url():
    flow = lab_flow("/https://httpbin.org/catalog")

    run_chain(flow, origin_response(200, [(b"content-location", b"/catalog.json")]))

    assert flow.response.headers["content-location"] == f"{LAN_PROXY_BASE}/https://httpbin.org/catalog.json"


def test_every_link_url_becomes_a_prefixed_url():
    flow = lab_flow("/https://httpbin.org/page/1")
    link = '<https://cdn.example/a.css>; rel="preload"; as=style, </page/2?x=1>; rel=next'

    run_chain(flow, origin_response(200, [(b"link", link.encode())]))

    assert flow.response.headers["link"] == (
        f'<{LAN_PROXY_BASE}/https://cdn.example/a.css>; rel="preload"; as=style, '
        f"<{LAN_PROXY_BASE}/https://httpbin.org/page/2?x=1>; rel=next"
    )


@pytest.mark.parametrize(
    "refresh, rewritten",
    [
        ("5; url=/next", f"5; url={LAN_PROXY_BASE}/https://httpbin.org/next"),
        ("0;URL='https://cdn.example/x'", f"0;URL='{LAN_PROXY_BASE}/https://cdn.example/x'"),
        ("30", "30"),
    ],
)
def test_refresh_url_becomes_a_prefixed_url(refresh, rewritten):
    flow = lab_flow("/https://httpbin.org/wait")

    run_chain(flow, origin_response(200, [(b"refresh", refresh.encode())]))

    assert flow.response.headers["refresh"] == rewritten


def test_set_cookie_loses_its_domain_and_its_path_is_prefixed_with_the_origin():
    flow = lab_flow("/https://httpbin.org:8443/cookies/set?x=1")
    cookies = [
        (b"set-cookie", b"x=1; Domain=.httpbin.org; Secure; Path=/"),
        (b"set-cookie", b"session=a=b; path=/cookies; HttpOnly; Max-Age=60"),
        (b"set-cookie", b"y=2; DOMAIN=httpbin.org"),
    ]

    run_chain(flow, origin_response(302, cookies))

    assert flow.response.headers.get_all("set-cookie") == [
        "x=1; Secure; Path=/https://httpbin.org:8443/",
        "session=a=b; path=/https://httpbin.org:8443/cookies; HttpOnly; Max-Age=60",
        "y=2",
    ]


def test_cookie_path_includes_the_secret_segment_of_the_proxy_base():
    flow = lab_flow("/s3cr3t/https://httpbin.org/cookies/set", host_header="lab.example")

    run_chain(flow, origin_response(302, [(b"set-cookie", b"x=1; Path=/")]))

    assert flow.response.headers["set-cookie"] == "x=1; Path=/s3cr3t/https://httpbin.org/"


def test_rewritten_urls_use_the_proxy_base_of_the_requesting_client():
    lan = lab_flow("/https://httpbin.org/redirect/1")
    other = lab_flow("/s3cr3t/https://httpbin.org/redirect/1", host_header="lab.example")

    run_chain(lan, origin_response(302, [(b"location", b"/get")]))
    run_chain(other, origin_response(302, [(b"location", b"/get")]))

    assert lan.response.headers["location"] == f"{LAN_PROXY_BASE}/https://httpbin.org/get"
    assert other.response.headers["location"] == "http://lab.example/s3cr3t/https://httpbin.org/get"


def test_a_replayed_response_is_reprefixed_for_the_current_client_not_double_prefixed():
    """Server replay re-runs the response hooks on headers the lab already rewrote
    when it recorded them, with the recording client's Proxy Base."""
    recorded = "http://rec.example/old/https://httpbin.org"
    flow = lab_flow("/https://httpbin.org/cookies/set?x=1")
    flow.is_replay = "response"

    run_chain(flow, origin_response(302, [
        (b"location", f"{recorded}/cookies".encode()),
        (b"link", f"<{recorded}/a.css>; rel=preload".encode()),
        (b"set-cookie", b"x=1; Path=/old/https://httpbin.org/"),
    ]))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}/https://httpbin.org/cookies"
    assert flow.response.headers["link"] == f"<{LAN_PROXY_BASE}/https://httpbin.org/a.css>; rel=preload"
    assert flow.response.headers["set-cookie"] == "x=1; Path=/https://httpbin.org/"


def test_a_live_origin_url_that_embeds_another_url_is_prefixed_as_is():
    flow = lab_flow("/https://httpbin.org/redirect-to?url=archived")

    run_chain(flow, origin_response(302, [(b"location", b"https://web.archive.org/web/https://example.com/")]))

    assert flow.response.headers["location"] == (
        f"{LAN_PROXY_BASE}/https://web.archive.org/web/https://example.com/"
    )
