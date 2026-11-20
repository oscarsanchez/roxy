"""Which response bodies get rewritten, and that the rest reach the client untouched."""

import gzip
import json

import pytest
from mitmproxy import http
from mitmproxy.exceptions import OptionsError
from mitmproxy.test import tutils

from chain import FIXTURES, LAN_PROXY_BASE, Lab, fixture_response, lab_flow, run_chain


REWRITTEN_VARIANT = f"{LAN_PROXY_BASE}/https://stream.mux.com/videos/gear2/prog_index.m3u8"


def client_body(path, response):
    flow = lab_flow(path)
    run_chain(flow, response)
    return flow.response


@pytest.mark.parametrize(
    "content_type",
    ["application/vnd.apple.mpegurl", "application/x-mpegURL", "audio/mpegurl",
     "application/vnd.apple.mpegurl; charset=utf-8"],
)
def test_a_rewriter_is_chosen_by_content_type(content_type):
    response = client_body("/https://stream.mux.com/videos/playlist?id=7",
                           fixture_response("hls-master.m3u8", content_type))

    assert REWRITTEN_VARIANT in response.text.splitlines()


@pytest.mark.parametrize("content_type", ["application/octet-stream", "text/plain", None])
def test_without_a_known_content_type_the_url_extension_chooses_the_rewriter(content_type):
    response = fixture_response("hls-master.m3u8", content_type or "")
    if content_type is None:
        del response.headers["content-type"]  # e.g. map_local of an unknown extension

    response = client_body("/https://stream.mux.com/videos/master.M3U8?token=1", response)

    assert REWRITTEN_VARIANT in response.text.splitlines()


@pytest.mark.parametrize(
    "path, content_type",
    [
        ("/https://stream.mux.com/v1/0.ts", "video/MP2T"),
        ("/https://stream.mux.com/v1/0.ts", "application/octet-stream"),
        ("/https://httpbin.org/image/jpeg", "image/jpeg"),
        ("/https://httpbin.org/html", "text/html; charset=utf-8"),
    ],
)
def test_bodies_with_no_rewriter_pass_through_byte_for_byte(path, content_type):
    body = b"\x47\x40\x00\x10\xff\xfe\n/v1/1.ts\nhttps://cdn.example.com/x.ts\n\x00\x80"
    origin = tutils.tresp(headers=http.Headers(content_type=content_type), content=body)

    response = client_body(path, origin)

    assert response.raw_content == body


CATALOG_THUMBNAIL = "https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/thumbnail.webp"


def catalog_thumbnail(path, content_type, **options):
    flow = lab_flow(path)
    run_chain(flow, fixture_response("catalog.json", content_type), **options)
    return json.loads(flow.response.text)["products"][0]["thumbnail"]


def test_a_content_type_added_to_a_format_option_gets_that_rewriter():
    path = "/https://dummyjson.com/products"

    assert catalog_thumbnail(path, "application/x-catalog") == CATALOG_THUMBNAIL
    assert catalog_thumbnail(
        path, "application/x-catalog",
        lab_rewrite_json=["application/json", "application/X-Catalog"],
    ) == f"{LAN_PROXY_BASE}/{CATALOG_THUMBNAIL}"


@pytest.mark.parametrize("content_type", ["application/vnd.api+json", "application/problem+JSON; charset=utf-8"])
def test_a_json_suffixed_content_type_gets_the_json_rewriter(content_type):
    assert catalog_thumbnail("/https://dummyjson.com/products", content_type) == f"{LAN_PROXY_BASE}/{CATALOG_THUMBNAIL}"


def test_an_xml_suffixed_content_type_gets_the_xml_rewriter():
    body = '<ad><media url="https://ads.example.com/ad.mp4"/></ad>'
    flow = lab_flow("/https://ads.example.com/ad")
    run_chain(flow, tutils.tresp(headers=http.Headers(content_type="application/vnd.example+xml"), content=body.encode()))

    assert flow.response.text == f'<ad><media url="{LAN_PROXY_BASE}/https://ads.example.com/ad.mp4"/></ad>'


def test_a_url_extension_wins_over_a_suffixed_content_type():
    flow = lab_flow("/https://media.example.com/live/master.m3u8")
    origin = tutils.tresp(
        headers=http.Headers(content_type="application/vnd.example+json"), content=b"#EXTM3U\n/live/720p.m3u8\n"
    )

    run_chain(flow, origin)

    assert flow.response.text == f"#EXTM3U\n{LAN_PROXY_BASE}/https://media.example.com/live/720p.m3u8\n"


def test_a_suffix_entry_removed_from_a_format_option_turns_its_suffix_off():
    assert catalog_thumbnail(
        "/https://dummyjson.com/products", "application/vnd.api+json", lab_rewrite_json=["application/json"]
    ) == CATALOG_THUMBNAIL


def test_a_url_extension_added_to_a_format_option_gets_that_rewriter():
    path = "/https://dummyjson.com/products.data"

    assert catalog_thumbnail(path, "text/plain") == CATALOG_THUMBNAIL
    assert catalog_thumbnail(path, "text/plain", lab_rewrite_json=[".data"]) == f"{LAN_PROXY_BASE}/{CATALOG_THUMBNAIL}"


def test_a_format_option_can_be_set_from_the_command_line():
    flow = lab_flow("/https://dummyjson.com/products.data")

    with Lab() as lab:
        lab.set_from_command_line("lab_rewrite_json=application/json", "lab_rewrite_json=.data")
        lab.run(flow, fixture_response("catalog.json", "text/plain"))

    assert json.loads(flow.response.text)["products"][0]["thumbnail"] == f"{LAN_PROXY_BASE}/{CATALOG_THUMBNAIL}"


def test_a_format_whose_option_is_emptied_passes_bodies_through():
    assert catalog_thumbnail("/https://dummyjson.com/products.json", "application/json",
                             lab_rewrite_json=[]) == CATALOG_THUMBNAIL


@pytest.mark.parametrize("entry", ["json", "", "m3u8"])
def test_a_format_option_entry_that_is_neither_a_content_type_nor_an_extension_is_refused(entry):
    with pytest.raises(OptionsError, match="lab_rewrite_hls"):
        run_chain(lab_flow("/https://httpbin.org/json"), tutils.tresp(), lab_rewrite_hls=[entry])


def test_a_compressed_playlist_is_rewritten_and_stays_compressed():
    origin = tutils.tresp(
        headers=http.Headers(content_type="application/vnd.apple.mpegurl", content_encoding="gzip"),
        content=b"",
    )
    origin.raw_content = gzip.compress((FIXTURES / "hls-master.m3u8").read_bytes())

    response = client_body("/https://stream.mux.com/videos/master.m3u8", origin)

    assert response.headers["content-encoding"] == "gzip"
    assert REWRITTEN_VARIANT in gzip.decompress(response.raw_content).decode().splitlines()
