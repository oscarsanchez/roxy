"""HLS playlists come back to the client with every non-relative URI as a Prefixed URL."""

from chain import LAN_PROXY_BASE, fixture_response, lab_flow, run_chain


MASTER_URL = "https://stream.mux.com/videos/master.m3u8"


def client_playlist(path, fixture):
    flow = lab_flow(path)
    run_chain(flow, fixture_response(fixture, "application/vnd.apple.mpegurl"))
    return flow.response.text.splitlines()


def test_absolute_uri_lines_become_prefixed_urls_with_their_query_kept():
    lines = client_playlist(f"/{MASTER_URL}", "hls-master.m3u8")

    assert (
        f"{LAN_PROXY_BASE}/https://manifest.edgemv.mux.com/tok/rendition.m3u8"
        "?cdn=edgemv&expires=1700000000&skid=a1&signature=x%2Fy"
    ) in lines


def test_root_relative_uri_lines_are_resolved_against_the_origin_then_prefixed():
    lines = client_playlist(f"/{MASTER_URL}", "hls-master.m3u8")

    assert f"{LAN_PROXY_BASE}/https://stream.mux.com/videos/gear2/prog_index.m3u8" in lines


def test_relative_uri_lines_are_left_as_they_are():
    lines = client_playlist(f"/{MASTER_URL}", "hls-master.m3u8")

    assert "gear1/prog_index.m3u8" in lines


def test_uri_attributes_of_media_and_i_frame_tags_are_rewritten():
    lines = client_playlist(f"/{MASTER_URL}", "hls-master.m3u8")

    assert (
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="en",'
        f'URI="{LAN_PROXY_BASE}/https://manifest.edgemv.mux.com/tok/audio.m3u8?skid=a1&signature=x%2Fy"'
    ) in lines
    assert (
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",'
        f'URI="{LAN_PROXY_BASE}/https://stream.mux.com/subs/en/prog_index.m3u8"'
    ) in lines
    assert (
        '#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=150000,RESOLUTION=1280x720,CODECS="avc1.64001f",'
        f'URI="{LAN_PROXY_BASE}/https://stream.mux.com/videos/gear3/iframe_index.m3u8"'
    ) in lines
    assert (
        '#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=80000,RESOLUTION=640x360,CODECS="avc1.64001f",'
        'URI="gear1/iframe_index.m3u8"'
    ) in lines


def test_media_playlist_key_map_and_segment_uris_are_rewritten():
    lines = client_playlist("/https://stream.mux.com/videos/gear1/prog_index.m3u8", "hls-media.m3u8")

    assert lines == [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        "#EXT-X-TARGETDURATION:5",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        f'#EXT-X-KEY:METHOD=AES-128,URI="{LAN_PROXY_BASE}/https://keys.example.com/k/1?token=abc",'
        "IV=0x00000000000000000000000000000001",
        f'#EXT-X-MAP:URI="{LAN_PROXY_BASE}/https://stream.mux.com/v1/init.mp4",BYTERANGE="719@0"',
        "#EXTINF:5.0,",
        f"{LAN_PROXY_BASE}/https://chunk.edgemv.mux.com/v1/chunk/tok/0.ts?skid=a1&signature=x%2Fy",
        "#EXTINF:5.0,",
        f"{LAN_PROXY_BASE}/https://stream.mux.com/v1/chunk/tok/1.ts",
        "#EXTINF:5.0,",
        f"{LAN_PROXY_BASE}/https://cdn2.example.com/v1/chunk/tok/2.ts",
        "#EXTINF:5.0,",
        "3.ts",
        "#EXT-X-BYTERANGE:1000@0",
        "#EXTINF:5.0,",
        "../main.ts",
        "#EXT-X-ENDLIST",
    ]


def test_rewriting_an_already_rewritten_playlist_reprefixes_without_doubling():
    """Server replay sends a recorded, already-rewritten body through the chain again,
    possibly for a client with a different Proxy Base."""
    first = lab_flow(f"/{MASTER_URL}")
    run_chain(first, fixture_response("hls-master.m3u8", "application/vnd.apple.mpegurl"))
    replay = lab_flow(f"/s3cr3t/{MASTER_URL}", host_header="lab.example")
    replay.is_replay = "response"

    run_chain(replay, first.response)

    lines = replay.response.text.splitlines()
    assert "http://lab.example/s3cr3t/https://stream.mux.com/videos/gear2/prog_index.m3u8" in lines
    assert not any("192.0.2.10" in line for line in lines)
