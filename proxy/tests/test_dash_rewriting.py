"""DASH manifests come back to the client with every non-relative URL as a Prefixed URL."""

import pytest

from chain import LAN_PROXY_BASE, fixture_response, lab_flow, run_chain


MPD_URL = "https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd"


def client_manifest(path=f"/{MPD_URL}", content_type="application/dash+xml"):
    flow = lab_flow(path)
    run_chain(flow, fixture_response("dash.mpd", content_type))
    return [line.strip() for line in flow.response.text.splitlines()]


def test_absolute_base_urls_become_prefixed_urls():
    lines = client_manifest()

    assert f'<BaseURL serviceLocation="cdn-a">{LAN_PROXY_BASE}/https://cdn-a.example.com/bbb/</BaseURL>' in lines


@pytest.mark.parametrize(
    "path, content_type",
    [
        ("/https://dash.akamaized.net/manifest?id=7", "application/dash+xml; charset=utf-8"),
        # GCS serves its MPDs (Widevine tears.mpd too) as octet-stream.
        ("/https://storage.googleapis.com/wvmedia/cenc/h264/tears/tears_sd.mpd", "application/octet-stream"),
    ],
)
def test_a_dash_manifest_is_recognised_by_content_type_or_mpd_extension(path, content_type):
    lines = client_manifest(path, content_type)

    assert f'<BaseURL serviceLocation="cdn-a">{LAN_PROXY_BASE}/https://cdn-a.example.com/bbb/</BaseURL>' in lines


def test_the_manifest_refresh_location_becomes_a_prefixed_url():
    lines = client_manifest()

    assert f"<Location>{LAN_PROXY_BASE}/{MPD_URL}?refresh=1</Location>" in lines


def test_root_relative_base_urls_are_resolved_against_the_origin_then_prefixed():
    lines = client_manifest()

    assert f"<BaseURL>{LAN_PROXY_BASE}/https://dash.akamaized.net/akamai/bbb_30fps/list/</BaseURL>" in lines


def test_relative_base_urls_are_left_as_they_are():
    lines = client_manifest()

    assert "<BaseURL>./</BaseURL>" in lines
    assert "<BaseURL>base_480p.mp4</BaseURL>" in lines


def test_absolute_and_root_relative_segment_templates_are_rewritten_keeping_their_identifiers():
    lines = client_manifest()

    assert (
        "<SegmentTemplate"
        f' media="{LAN_PROXY_BASE}/https://dash.akamaized.net/akamai/bbb_30fps/audio/$Number%05d$.m4a?tok=a&amp;sig=b%2Fc"'
        f' initialization="{LAN_PROXY_BASE}/https://dash.akamaized.net/akamai/bbb_30fps/audio/init.m4a"'
        ' duration="192512" timescale="48000"/>'
    ) in lines


def test_segment_list_initialization_media_and_index_urls_are_rewritten():
    lines = client_manifest()

    assert f'<Initialization sourceURL="{LAN_PROXY_BASE}/https://cdn-b.example.com/list/init.mp4"/>' in lines
    assert (
        f'<SegmentURL media="{LAN_PROXY_BASE}/https://cdn-b.example.com/list/1.m4s"'
        f' index="{LAN_PROXY_BASE}/https://dash.akamaized.net/akamai/bbb_30fps/list/1.sidx"/>'
    ) in lines
    assert '<SegmentURL media="2.m4s" mediaRange="0-999"/>' in lines


def test_the_dash_absolute_scenario_serves_the_public_manifest_with_an_absolute_base_url_rewritten():
    """No public clear DASH stream uses absolute URLs, so this scenario maps the Lab App's
    DASH manifest to a local copy that does, putting the rewriter on the device's path."""
    flow = lab_flow(f"/{MPD_URL}")

    forwarded = run_chain(flow, None, lab_scenario="dash-absolute")

    assert forwarded is None
    assert f"<BaseURL>{LAN_PROXY_BASE}/https://dash.akamaized.net/akamai/bbb_30fps/</BaseURL>" in flow.response.text


def test_relative_segment_templates_are_left_as_they_are():
    lines = client_manifest()

    assert (
        '<SegmentTemplate media="$RepresentationID$/$RepresentationID$_$Number$.m4v"'
        ' initialization="$RepresentationID$/$RepresentationID$_0.m4v"'
        ' duration="120" timescale="30" startNumber="1"/>'
    ) in lines
