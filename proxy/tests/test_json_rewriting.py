"""JSON documents come back to the client with every absolute http(s) URL value
as a Prefixed URL, and everything else exactly as the Origin sent it."""

import json

from chain import FIXTURES, LAN_PROXY_BASE, fixture_response, lab_flow, run_chain


CATALOG_URL = "https://dummyjson.com/products?limit=1"


def client_catalog():
    flow = lab_flow(f"/{CATALOG_URL}")
    run_chain(flow, fixture_response("catalog.json", "application/json; charset=utf-8"))
    return flow.response.text


def test_an_absolute_url_value_becomes_a_prefixed_url():
    product = json.loads(client_catalog())["products"][0]

    assert product["thumbnail"] == (
        f"{LAN_PROXY_BASE}/https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/thumbnail.webp"
    )


def test_only_absolute_url_values_change_and_every_other_byte_is_kept():
    original = (FIXTURES / "catalog.json").read_text()
    product = "cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess"
    expected = (
        original
        .replace(f'"https://{product}/thumbnail.webp"', f'"{LAN_PROXY_BASE}/https://{product}/thumbnail.webp"')
        .replace(  # escaped slashes are decoded; the query is kept byte for byte
            '"https:\\/\\/cdn.dummyjson.com\\/product-images\\/beauty\\/essence-mascara-lash-princess'
            '\\/1.webp?w=320&sig=a%2Fb"',
            f'"{LAN_PROXY_BASE}/https://{product}/1.webp?w=320&sig=a%2Fb"',
        )
        .replace('"http://dummyjson.com/image/320x180"', f'"{LAN_PROXY_BASE}/http://dummyjson.com/image/320x180"')
        .replace(': "https://dummyjson.com/products/1"', f': "{LAN_PROXY_BASE}/https://dummyjson.com/products/1"')
    )

    assert client_catalog() == expected


def test_a_json_post_body_reaches_the_origin_intact_and_its_echo_comes_back():
    sent = b'{"case":"json_post","n":1,"ok":true}'
    flow = lab_flow("/https://httpbin.org/post")
    flow.request.method = "POST"
    flow.request.headers["content-type"] = "application/json"
    flow.request.content = sent

    forwarded = run_chain(flow, fixture_response("httpbin-post.json", "application/json"))

    assert (forwarded.method, forwarded.url, forwarded.content) == ("POST", "https://httpbin.org/post", sent)
    echo = json.loads(flow.response.text)
    assert echo["data"].encode() == sent  # the echoed body is a string, not a URL: untouched
    assert echo["url"] == f"{LAN_PROXY_BASE}/https://httpbin.org/post"
