"""A VMAP ad schedule and the VAST wrapper chain it leads to come back with every URL
a Prefixed URL in the request's separator, prefixed once, so RAF fetches every hop,
beacon and creative through the lab."""

import re

import pytest

from chain import FIXTURES, LAN_PROXY_BASE, fixture_response, lab_flow, run_chain

SEPARATORS = pytest.mark.parametrize("separator", ["/", "/;"])

VMAP_TAG = "https://ads.example.com/gampad/ads?iu=/1/vmap_samples&output=vmap&correlator=1700"
URL = re.compile(r"""https?://[^\s<>"'\]]+""")


def client_xml(separator, origin_url, fixture):
    flow = lab_flow(f"{separator}{origin_url}")
    run_chain(flow, fixture_response(fixture, "text/xml; charset=UTF-8"))
    return flow.response.text


@SEPARATORS
def test_vmap_ad_tag_uris_in_cdata_and_text_become_prefixed_urls(separator):
    vmap = client_xml(separator, VMAP_TAG, "vmap.xml")

    base = f"{LAN_PROXY_BASE}{separator}"
    assert (
        f'<vmap:AdTagURI templateType="vast3"><![CDATA[{base}https://ads.example.com/vast/wrapper'
        "?slot=preroll&url=https%3A%2F%2Fpublisher.example%2Fwatch&vpos=preroll&correlator=1700]]></vmap:AdTagURI>"
    ) in vmap
    assert (
        '<vmap:AdTagURI templateType="vast3">\n'
        f"    {base}https://ads.example.com/vast/wrapper?slot=midroll&amp;vpos=midroll&amp;correlator=1700\n"
        "   </vmap:AdTagURI>"
    ) in vmap
    assert (
        f'<vmap:Tracking event="breakStart"><![CDATA[{base}https://beacons.example.net/break'
        "?b=preroll&e=start]]></vmap:Tracking>"
    ) in vmap
    # The namespace name is an identifier, not a location.
    assert '<vmap:VMAP xmlns:vmap="http://www.iab.net/videosuite/vmap" version="1.0">' in vmap


def hop(prefixed_url, fixture):
    """The client requests a Prefixed URL it was handed and the Origin answers with `fixture`:
    returns the URL that reached the Origin and the document that reached the client."""
    assert prefixed_url.startswith(LAN_PROXY_BASE)
    flow = lab_flow(prefixed_url.removeprefix(LAN_PROXY_BASE))
    forwarded = run_chain(flow, fixture_response(fixture, "text/xml; charset=UTF-8"))
    return forwarded.url, flow.response.text


def cdata(document, element):
    return re.search(rf"<{element}[^>]*><!\[CDATA\[(.*?)\]\]>", document)[1]


def prefixed_once(fixture, separator):
    """Every URL in the fixture, in order, as the client must see it: each https URL (all
    the fixtures fetch) once behind the Proxy Base, and the http namespace name as it is."""
    urls = URL.findall((FIXTURES / fixture).read_text())
    return [f"{LAN_PROXY_BASE}{separator}{url}" if url.startswith("https://") else url for url in urls]


@SEPARATORS
def test_following_the_vmap_and_its_wrapper_reaches_every_origin_with_each_url_prefixed_once(separator):
    reached_vmap, vmap = hop(f"{LAN_PROXY_BASE}{separator}{VMAP_TAG}", "vmap.xml")
    reached_wrapper, wrapper = hop(cdata(vmap, "vmap:AdTagURI"), "vast-wrapper-hop.xml")
    reached_inline, inline = hop(cdata(wrapper, "VASTAdTagURI"), "vast-inline-hop.xml")

    assert [reached_vmap, reached_wrapper, reached_inline] == [
        VMAP_TAG,
        "https://ads.example.com/vast/wrapper?slot=preroll&url=https%3A%2F%2Fpublisher.example%2Fwatch"
        "&vpos=preroll&correlator=1700",
        "https://ads.example.net/vast/inline?creative=7&correlator=1700",
    ]
    assert URL.findall(vmap) == prefixed_once("vmap.xml", separator)
    assert URL.findall(wrapper) == prefixed_once("vast-wrapper-hop.xml", separator)
    assert URL.findall(inline) == prefixed_once("vast-inline-hop.xml", separator)
    assert cdata(inline, "MediaFile") == f"{LAN_PROXY_BASE}{separator}https://media.example.org/ads/inline-7/640x360.mp4"


@pytest.mark.parametrize("recorded", ["/", "/;"])
@SEPARATORS
def test_a_replayed_wrapper_recorded_in_either_form_is_reprefixed_once_in_the_current_form(recorded, separator):
    """Server replay sends a recorded, already-rewritten VAST through the chain again."""
    record = lab_flow(f"{recorded}{VMAP_TAG}", host_header="rec.example")
    run_chain(record, fixture_response("vast-wrapper-hop.xml", "text/xml"))
    replay = lab_flow(f"{separator}{VMAP_TAG}")
    replay.is_replay = "response"

    run_chain(replay, record.response)

    assert URL.findall(replay.response.text) == prefixed_once("vast-wrapper-hop.xml", separator)
