"""Manifest-edit scenario actions: what the client gets after the lab edits an HLS playlist or a DASH MPD."""

import pytest
from mitmproxy import http
from mitmproxy.exceptions import OptionsError
from mitmproxy.test import tutils

from chain import LAN_PROXY_BASE, Lab, fixture_response, lab_flow, run_chain


MASTER_URL = "https://stream.mux.com/videos/master.m3u8"
MEDIA_URL = "https://stream.mux.com/videos/gear1/prog_index.m3u8"


@pytest.fixture
def edited(tmp_path):
    """Run a manifest fixture through the lab with a one-rule scenario; returns
    the manifest lines the client receives."""

    def run(action, fixture="hls-master.m3u8", url=MASTER_URL):
        (tmp_path / "edit.toml").write_text(f'[[rule]]\nname = "edit"\nfilter = "~u example|mux|akamaized"\n{action}\n')
        flow = lab_flow(f"/{url}")
        content_type = "application/dash+xml" if fixture.endswith(".mpd") else "application/vnd.apple.mpegurl"
        run_chain(flow, fixture_response(fixture, content_type),
                  lab_scenarios_dir=str(tmp_path), lab_scenario="edit")
        return flow.response.text.splitlines()

    return run


def variants(lines):
    """(STREAM-INF line, URI line) pairs of a master playlist."""
    return [(tag, lines[i + 1]) for i, tag in enumerate(lines) if tag.startswith("#EXT-X-STREAM-INF:")]


def test_all_but_the_lowest_variant_are_dropped(edited):
    lines = edited('drop_variants = { all_but = "lowest" }')

    assert variants(lines) == [(
        '#EXT-X-STREAM-INF:BANDWIDTH=600000,RESOLUTION=640x360,CODECS="avc1.64001f,mp4a.40.2",AUDIO="aud",SUBTITLES="subs"',
        "gear1/prog_index.m3u8",
    )]


@pytest.mark.parametrize("criterion, kept_bandwidths", [
    ("bandwidth_above = 1200000", ["1200000", "600000"]),
    ("bandwidth_below = 1200000", ["2516000", "1200000"]),
    ('resolution = "960x540"', ["2516000", "600000"]),
])
def test_variants_are_dropped_by_bandwidth_or_resolution(edited, criterion, kept_bandwidths):
    lines = edited(f"drop_variants = {{ {criterion} }}")

    assert [tag.split(",")[0].removeprefix("#EXT-X-STREAM-INF:BANDWIDTH=") for tag, _ in variants(lines)] == kept_bandwidths


def test_dropping_variants_leaves_i_frame_variants_and_renditions_alone(edited):
    lines = edited('drop_variants = { all_but = "lowest" }')

    assert sum(line.startswith("#EXT-X-I-FRAME-STREAM-INF:") for line in lines) == 2
    assert sum(line.startswith("#EXT-X-MEDIA:") for line in lines) == 3


def renditions(lines):
    return [line for line in lines if line.startswith("#EXT-X-MEDIA:")]


def test_renditions_matching_every_given_attribute_are_dropped(edited):
    lines = edited('drop_renditions = { type = "AUDIO", language = "en" }')

    assert [r.split(",")[0] for r in renditions(lines)] == [
        "#EXT-X-MEDIA:TYPE=SUBTITLES",
        "#EXT-X-MEDIA:TYPE=CLOSED-CAPTIONS",
    ]
    assert len(variants(lines)) == 3


def test_renditions_are_matched_by_group_id_too(edited):
    lines = edited('drop_renditions = { group_id = "subs" }')

    assert [r.split(",")[0] for r in renditions(lines)] == [
        "#EXT-X-MEDIA:TYPE=AUDIO",
        "#EXT-X-MEDIA:TYPE=CLOSED-CAPTIONS",
    ]


def media(edited, action):
    return edited(action, fixture="hls-media.m3u8", url=MEDIA_URL)


def segment_uris(lines):
    return [line for line in lines if line and not line.startswith("#")]


def test_a_range_of_segments_is_removed_with_their_own_tags(edited):
    lines = media(edited, "drop_segments = { from = 1, to = 2 }")

    assert segment_uris(lines) == [
        f"{LAN_PROXY_BASE}/https://chunk.edgemv.mux.com/v1/chunk/tok/0.ts?skid=a1&signature=x%2Fy",
        "3.ts",
        "../main.ts",
    ]
    assert sum(line.startswith("#EXTINF:") for line in lines) == 3


def test_removing_segments_keeps_tags_that_apply_to_later_segments(edited):
    lines = media(edited, "drop_segments = { from = 0, to = 0 }")

    assert segment_uris(lines)[0] == f"{LAN_PROXY_BASE}/https://stream.mux.com/v1/chunk/tok/1.ts"
    assert [line.split(":")[0] for line in lines if line.startswith("#EXT-X-")] == [
        "#EXT-X-VERSION", "#EXT-X-TARGETDURATION", "#EXT-X-MEDIA-SEQUENCE", "#EXT-X-PLAYLIST-TYPE",
        "#EXT-X-KEY", "#EXT-X-MAP", "#EXT-X-BYTERANGE", "#EXT-X-ENDLIST",
    ]


def test_segments_from_an_index_to_the_end_are_removed(edited):
    lines = media(edited, "drop_segments = { from = 3 }")

    assert len(segment_uris(lines)) == 3
    assert lines[-1] == "#EXT-X-ENDLIST"
    assert not any(line.startswith("#EXT-X-BYTERANGE:") for line in lines)


def test_a_segment_uri_is_altered_and_a_relative_one_resolves_through_the_prefixed_url(edited):
    lines = media(edited, 'alter_segments = { from = 1, to = 1, uri = "missing.ts" }')

    assert segment_uris(lines)[:3] == [
        f"{LAN_PROXY_BASE}/https://chunk.edgemv.mux.com/v1/chunk/tok/0.ts?skid=a1&signature=x%2Fy",
        "missing.ts",
        f"{LAN_PROXY_BASE}/https://cdn2.example.com/v1/chunk/tok/2.ts",
    ]


def test_an_absolute_altered_segment_uri_still_routes_through_the_lab(edited):
    lines = media(edited, 'alter_segments = { from = 4, uri = "https://other.example.com/x.ts" }')

    assert segment_uris(lines)[4] == f"{LAN_PROXY_BASE}/https://other.example.com/x.ts"


def test_segment_durations_are_altered(edited):
    lines = media(edited, "alter_segments = { from = 0, to = 1, duration = 1.5 }")

    assert [line for line in lines if line.startswith("#EXTINF:")] == [
        "#EXTINF:1.5,", "#EXTINF:1.5,", "#EXTINF:5.0,", "#EXTINF:5.0,", "#EXTINF:5.0,",
    ]


def test_segment_edits_leave_master_playlists_alone(edited):
    lines = edited("drop_segments = { from = 0 }")

    assert len(variants(lines)) == 3


def test_a_segment_that_matches_the_filter_is_not_touched(tmp_path):
    (tmp_path / "edit.toml").write_text('[[rule]]\nname = "edit"\nfilter = "~all"\ndrop_segments = { from = 0 }\n')
    flow = lab_flow("/https://stream.mux.com/v1/chunk/tok/0.ts")
    segment = tutils.tresp(headers=http.Headers(content_type="video/MP2T"), content=b"#EXTINF:\x47\xff\x00")

    run_chain(flow, segment, lab_scenarios_dir=str(tmp_path), lab_scenario="edit")

    assert flow.response.content == b"#EXTINF:\x47\xff\x00"


@pytest.mark.parametrize("action", [
    "drop_variants = { all_but = \"middle\" }",
    "drop_variants = { bandwidth_above = \"lots\" }",
    "drop_variants = { bandwidth_above = 1, resolution = \"640x360\" }",
    "drop_variants = { codecs = \"avc1\" }",
    "drop_renditions = {}",
    "drop_renditions = { langauge = \"en\" }",
    "drop_renditions = { type = \"AUDIO\", lang = \"en\" }",  # HLS and DASH keys mixed
    "drop_segments = { to = 3 }",
    "drop_segments = { from = 3, to = 1 }",
    "drop_segments = { from = -1 }",
    "alter_segments = { from = 0 }",
    "alter_segments = { from = 0, duration = \"long\" }",
    "alter_segments = { from = 0, uri = 404 }",
])
def test_an_invalid_manifest_edit_is_rejected(tmp_path, action):
    (tmp_path / "bad.toml").write_text(f'[[rule]]\nname = "bad"\nfilter = "~all"\n{action}\n')

    with Lab(lab_scenarios_dir=str(tmp_path)) as lab, pytest.raises(OptionsError):
        lab.set_options(lab_scenario="bad")


def test_the_shipped_hls_lowest_variant_scenario_keeps_only_the_lowest_variant():
    flow = lab_flow(f"/{MASTER_URL}")

    run_chain(flow, fixture_response("hls-master.m3u8", "application/vnd.apple.mpegurl"),
              lab_scenario="hls-lowest-variant")

    assert [uri for _, uri in variants(flow.response.text.splitlines())] == ["gear1/prog_index.m3u8"]


MPD_URL = "https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd"


def representation_ids(lines):
    return [line.split('id="')[1].split('"')[0] for line in lines if line.strip().startswith("<Representation ")]


@pytest.mark.parametrize("criterion, kept", [
    # Each AdaptationSet keeps its own lowest: audio and the single-variant video stay.
    ('all_but = "lowest"', ["bbb_30fps_320x180_200k", "audio_128k", "base_480p"]),
    ('all_but = "highest"', ["bbb_30fps_320x180_200k", "audio_128k", "list_720p"]),
    ("bandwidth_above = 1000000", ["bbb_30fps_320x180_200k", "audio_128k", "base_480p"]),
    ("bandwidth_below = 200000", ["bbb_30fps_320x180_200k", "list_720p", "base_480p"]),
    ('resolution = "320x180"', ["audio_128k", "list_720p", "base_480p"]),
])
def test_dash_representations_are_dropped_like_hls_variants(edited, criterion, kept):
    lines = edited(f"drop_variants = {{ {criterion} }}", fixture="dash.mpd", url=MPD_URL)

    assert representation_ids(lines) == kept


@pytest.mark.parametrize("criterion", ['content_type = "audio"', 'mime_type = "audio/mp4"', 'lang = "en"'])
def test_dash_adaptation_sets_are_dropped_as_renditions(edited, criterion):
    lines = edited(f"drop_renditions = {{ {criterion} }}", fixture="dash.mpd", url=MPD_URL)

    assert representation_ids(lines) == ["bbb_30fps_320x180_200k", "list_720p", "base_480p"]
    assert not any("AdaptationSet" in line and "audio" in line for line in lines)
    assert not any("audio/$Number" in line for line in lines)  # its SegmentTemplate went with it


def test_hls_rendition_keys_leave_dash_alone_and_dash_keys_leave_hls_alone(edited):
    dash = edited('drop_renditions = { type = "AUDIO" }', fixture="dash.mpd", url=MPD_URL)
    hls = edited('drop_renditions = { lang = "en" }')

    assert representation_ids(dash) == ["bbb_30fps_320x180_200k", "audio_128k", "list_720p", "base_480p"]
    assert len(renditions(hls)) == 3


def test_a_dropped_dash_representation_takes_its_segment_list_with_it(edited):
    lines = edited('drop_variants = { all_but = "lowest" }', fixture="dash.mpd", url=MPD_URL)

    assert not any("SegmentURL" in line or "list/init.mp4" in line for line in lines)
    assert not any("/akamai/bbb_30fps/list/" in line for line in lines)
    assert "        <BaseURL>base_480p.mp4</BaseURL>" in lines


def test_edits_run_after_url_rewriting_so_kept_uris_still_route_through_the_lab(edited):
    lines = edited('drop_variants = { all_but = "highest" }')

    assert [uri for _, uri in variants(lines)] == [
        f"{LAN_PROXY_BASE}/https://manifest.edgemv.mux.com/tok/rendition.m3u8"
        "?cdn=edgemv&expires=1700000000&skid=a1&signature=x%2Fy"
    ]
