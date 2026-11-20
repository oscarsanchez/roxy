"""VAST and other XML documents come back to the client with every absolute URL as a
Prefixed URL, so the ad, its media and its beacons come back through the lab."""

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import LAN_PROXY_BASE, fixture_response, lab_flow, run_chain


AD_TAG = "https://pubads.g.doubleclick.net/gampad/ads?iu=/21775744923/external/single_ad_samples&output=vast"

# Roku's own sample ad response (SmartXML, not VAST): its media are attribute URLs.
AD_RESPONSE = """<adResponse xmlns="http://www.example.com/ad-response"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.example.com/ad-response http://www.example.com/ad-response.xsd">
 <asset id="1" mimeType="video/mp4" url="http://devtools.web.roku.com/samples/test_ad_1.mp4" />
 <asset id="2" mimeType="video/mp4" url='https://devtools.web.roku.com/samples/test_ad_2.mp4?a=1&amp;b=2'/>
 <note>Relative paths stay: /samples/test_ad_3.mp4</note>
</adResponse>
"""


def client_xml(fixture, content_type="text/xml; charset=UTF-8", origin_url=AD_TAG):
    flow = lab_flow(f"/{origin_url}")
    run_chain(flow, fixture_response(fixture, content_type))
    return flow.response.text


def client_body(origin_url, body, content_type):
    flow = lab_flow(f"/{origin_url}")
    run_chain(flow, tutils.tresp(headers=http.Headers(content_type=content_type), content=body.encode()))
    return flow.response.text


def test_inline_media_files_become_prefixed_urls():
    xml = client_xml("vast-inline.xml")

    assert (
        f"<![CDATA[{LAN_PROXY_BASE}/https://redirector.gvt1.com/api/manifest/progressive/0f6b6bc4a2d5f4c0/18"
        "?id=0f6b&itag=18&source=dclk_video_ads]]>"
    ) in xml
    assert (
        f"<![CDATA[{LAN_PROXY_BASE}/https://redirector.gvt1.com/api/manifest/hls_variant/id/0f6b/itag/0/"
        "source/dclk_video_ads/playlist.m3u8]]></MediaFile>"
    ) in xml


def test_inline_impressions_tracking_errors_and_click_throughs_become_prefixed_urls():
    xml = client_xml("vast-inline.xml")

    assert (
        f"<Impression><![CDATA[{LAN_PROXY_BASE}/https://pagead2.googlesyndication.com/pcs/view"
        "?xai=AKAO&sig=Cg0A&uach_m=%5BUACH%5D&adurl=]]></Impression>"
    ) in xml
    assert (
        f'<Tracking event="start"><![CDATA[{LAN_PROXY_BASE}/https://pagead2.googlesyndication.com/pagead/interaction/'
        "?ai=B3qx&label=part2viewed&ad_mt=%5BAD_MT%5D]]></Tracking>"
    ) in xml
    # A VAST macro's brackets stay part of the URL; the CDATA end stays intact.
    assert (
        f"<Error><![CDATA[{LAN_PROXY_BASE}/https://pagead2.googlesyndication.com/pagead/interaction/"
        "?ai=B3qx&label=videoplayfailed[ERRORCODE]]]></Error>"
    ) in xml
    # A URL embedded in another URL is part of it: prefixed once, at the front.
    assert (
        f'<ClickThrough id="GDFP"><![CDATA[{LAN_PROXY_BASE}/https://pagead2.googlesyndication.com/pcs/click'
        "?xai=AKAO&sig=Cg0A&adurl=https://developers.google.com/interactive-media-ads]]></ClickThrough>"
    ) in xml


def test_urls_in_plain_text_keep_their_entities_and_whitespace():
    xml = client_xml("vast-inline.xml")

    assert (
        '<Tracking event="complete">\n'
        f"        {LAN_PROXY_BASE}/https://pagead2.googlesyndication.com/pagead/interaction/?ai=B3qx&amp;label=videoplaytime100\n"
        "       </Tracking>"
    ) in xml


def test_wrapper_ad_tag_uri_impression_and_tracking_become_prefixed_urls():
    xml = client_xml("vast-wrapper.xml")

    assert (
        f"<VASTAdTagURI><![CDATA[{LAN_PROXY_BASE}/https://pubads.g.doubleclick.net/gampad/ads"
        "?iu=/21775744923/external/utility_samples&sz=640x480&output=vast&env=vp&impl=s"
        "&correlator=1076014185]]></VASTAdTagURI>"
    ) in xml
    assert (
        f"<Impression><![CDATA[{LAN_PROXY_BASE}/https://pagead2.googlesyndication.com/pcs/view"
        "?xai=AKAOjss&sig=Cg0A&uach_m=%5BUACH%5D&adurl=]]></Impression>"
    ) in xml
    assert (
        f'<Tracking event="start"><![CDATA[{LAN_PROXY_BASE}/https://pagead2.googlesyndication.com/pagead/interaction/'
        "?ai=B3qx&label=part2viewed&ad_mt=%5BAD_MT%5D]]></Tracking>"
    ) in xml


def test_namespace_declarations_are_left_alone():
    """A namespace name is an identifier, not a location: rewriting it changes the document."""
    xml = client_xml("vast-wrapper.xml")

    assert (
        '<VAST xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="vast.xsd" version="3.0">'
    ) in xml


@pytest.mark.parametrize(
    "origin_url, content_type",
    [
        ("https://devtools.web.roku.com/ads/response", "application/xml"),
        ("https://devtools.web.roku.com/ads/response", "text/xml"),
        ("https://devtools.web.roku.com/samples/sample.XML", "application/octet-stream"),
    ],
)
def test_absolute_urls_in_any_xml_attribute_or_text_become_prefixed_urls(origin_url, content_type):
    xml = client_body(origin_url, AD_RESPONSE, content_type)

    assert xml == f"""<adResponse xmlns="http://www.example.com/ad-response"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.example.com/ad-response http://www.example.com/ad-response.xsd">
 <asset id="1" mimeType="video/mp4" url="{LAN_PROXY_BASE}/http://devtools.web.roku.com/samples/test_ad_1.mp4" />
 <asset id="2" mimeType="video/mp4" url='{LAN_PROXY_BASE}/https://devtools.web.roku.com/samples/test_ad_2.mp4?a=1&amp;b=2'/>
 <note>Relative paths stay: /samples/test_ad_3.mp4</note>
</adResponse>
"""


@pytest.mark.parametrize("content_type", ["application/xml", "text/xml; charset=utf-8"])
@pytest.mark.parametrize(
    "origin_url, fixture, root_relative_resolved",
    [
        ("https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd", "dash.mpd",
         f"<BaseURL>{LAN_PROXY_BASE}/https://dash.akamaized.net/akamai/bbb_30fps/list/</BaseURL>"),
        ("https://stream.mux.com/videos/master.m3u8", "hls-master.m3u8",
         f"{LAN_PROXY_BASE}/https://stream.mux.com/videos/gear2/prog_index.m3u8"),
    ],
)
def test_a_generic_xml_content_type_yields_to_the_format_the_url_extension_names(
    origin_url, fixture, root_relative_resolved, content_type
):
    """Origins label manifests as plain XML (a .mpd as text/xml): the more specific format wins."""
    flow = lab_flow(f"/{origin_url}")

    run_chain(flow, fixture_response(fixture, content_type))

    # Only the manifest's own rewriter resolves root-relative URLs; generic XML leaves them.
    assert root_relative_resolved in [line.strip() for line in flow.response.text.splitlines()]


def test_rewriting_an_already_rewritten_vast_reprefixes_without_doubling():
    """Server replay sends a recorded, already-rewritten VAST through the chain again."""
    first = lab_flow(f"/{AD_TAG}")
    run_chain(first, fixture_response("vast-wrapper.xml", "text/xml"))
    replay = lab_flow(f"/s3cr3t/{AD_TAG}", host_header="lab.example")
    replay.is_replay = "response"

    run_chain(replay, first.response)

    assert (
        "<VASTAdTagURI><![CDATA[http://lab.example/s3cr3t/https://pubads.g.doubleclick.net/gampad/ads"
        "?iu=/21775744923/external/utility_samples&sz=640x480&output=vast&env=vp&impl=s"
        "&correlator=1076014185]]></VASTAdTagURI>"
    ) in replay.response.text
    assert "192.0.2.10" not in replay.response.text
