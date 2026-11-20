"""The `throttle` Scenario action: a matching flow's response reaches the client
at no more than the rule's bandwidth. Time is the lab's test clock (tests/chain.py):
pacing and latency never really sleep here."""

import pytest
from mitmproxy import http
from mitmproxy.exceptions import OptionsError
from mitmproxy.test import tutils

from chain import Lab, lab_flow

SEGMENT_BYTES = 500_000  # 500 KB


def segment_get():
    return lab_flow("/https://test-streams.mux.dev/video/720p/segment-1.ts")


def origin_segment(size=SEGMENT_BYTES):
    return tutils.tresp(headers=http.Headers(content_type="video/mp2t"), content=b"\x47" * size)


def received_by(received, seconds):
    """Bytes the client had received `seconds` after the response started."""
    return sum(size for when, size in received if when <= seconds)


SLOW_SEGMENTS = '''
[[rule]]
name = "slow segments"
filter = "~u /video/"
throttle = {{ kbps = {kbps} }}
'''


def test_a_throttled_body_reaches_the_client_at_the_capped_rate(scenarios):
    options = scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=400))
    flow = segment_get()

    with Lab(**options) as lab:
        lab.run(flow, origin_segment())
        received = lab.received(flow)

    assert 0 < received_by(received, 1.0) <= 50_000  # 400 kbps is 50 KB a second
    assert received_by(received, 9.5) < SEGMENT_BYTES
    assert received[-1][0] == pytest.approx(10, abs=0.1)
    assert flow.response.content == origin_segment().content


def test_a_flow_the_throttle_does_not_match_arrives_at_once(scenarios):
    options = scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=400))
    flow = lab_flow("/https://test-streams.mux.dev/audio/segment-1.aac")

    with Lab(**options) as lab:
        lab.run(flow, origin_segment())
        received = lab.received(flow)

    assert received_by(received, 0) > SEGMENT_BYTES


def test_throttle_combines_with_latency_for_a_slow_high_latency_link(scenarios):
    options = scenarios("slow-link", '''
[[rule]]
name = "high latency"
filter = "~u /video/"
latency = 0.2

[[rule]]
name = "low bandwidth"
filter = "~u /video/"
throttle = { kbps = 800 }
''')
    flow = segment_get()

    with Lab(**options) as lab:
        lab.run(flow, origin_segment())
        waited = lab.reached_origin_after(flow)
        received = lab.received(flow)

    assert waited == pytest.approx(0.2)
    assert received[-1][0] == pytest.approx(5, abs=0.1)  # 500 KB at 100 KB a second


@pytest.mark.parametrize("active", ["slow,slower", "slower,slow"])
def test_two_active_scenarios_throttling_one_flow_cap_it_at_the_lower_rate(scenarios, active):
    options = scenarios("slow", SLOW_SEGMENTS.format(kbps=800))
    scenarios("slower", SLOW_SEGMENTS.format(kbps=400))
    flow = segment_get()

    with Lab(**{**options, "lab_scenario": active}) as lab:
        lab.run(flow, origin_segment())
        received = lab.received(flow)

    assert received[-1][0] == pytest.approx(10, abs=0.1)  # 500 KB at 50 KB a second


BAD_THROTTLES =["0", "-400", '"fast"', "true", "nan", "inf"]
BAD_TABLES = ["400", "{ rate = 400 }", "{ kbps = 400, burst = 10 }"]


@pytest.mark.parametrize("kbps", BAD_THROTTLES)
def test_a_throttle_without_a_positive_rate_is_refused(scenarios, kbps):
    options = scenarios("broken", SLOW_SEGMENTS.format(kbps=kbps))

    with pytest.raises(OptionsError, match=r"rule 'slow segments': throttle must be \{ kbps = N \}"):
        Lab(**options)


@pytest.mark.parametrize("value", BAD_TABLES)
def test_a_throttle_that_is_not_a_kbps_table_is_refused(scenarios, value):
    options = scenarios("broken", SLOW_SEGMENTS.replace("{{ kbps = {kbps} }}", value))

    with pytest.raises(OptionsError, match=r"throttle must be \{ kbps = N \}"):
        Lab(**options)


def test_a_bad_throttle_edit_is_logged_and_the_last_good_rules_stay(scenarios, caplog):
    options = scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=400))

    with Lab(**options) as lab:
        scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=0))
        flow = segment_get()
        lab.run(flow, origin_segment())
        received = lab.received(flow)

    assert received[-1][0] == pytest.approx(10, abs=0.1)
    assert "not reloaded, keeping its last good rules: rule 'slow segments': throttle must be" in caplog.text


def test_the_end_of_a_throttled_response_reaches_the_client_after_its_last_byte(scenarios):
    options = scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=400))
    flow = segment_get()

    with Lab(**options) as lab:
        lab.run(flow, origin_segment())
        ended = lab.ended(flow)

    assert [how for how, _ in ended] == ["write_eof", "close"]
    assert all(when == pytest.approx(10, abs=0.1) for _, when in ended)


def test_nothing_is_sent_to_a_client_that_hung_up_mid_response(scenarios):
    options = scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=400))
    flow = segment_get()

    with Lab(**options) as lab:
        lab.run(flow, origin_segment(), client_hangs_up_at=2.05)
        received = lab.received(flow)

    assert received[-1][0] < 2.05
    assert received_by(received, 2.05) < SEGMENT_BYTES


def test_a_lab_stopping_mid_response_still_closes_the_client_connection(scenarios):
    options = scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=400))
    flow = segment_get()

    with Lab(**options) as lab:
        lab.run(flow, origin_segment(), lab_stops_at=3)
        received, ended = lab.received(flow), lab.ended(flow)

    assert received_by(received, 3.05) < SEGMENT_BYTES
    assert ended[-1][0] == "close"
    assert ended[-1][1] == pytest.approx(3, abs=0.1)


def test_an_http2_flow_is_not_throttled_and_the_log_says_why(scenarios, caplog):
    options = scenarios("slow-segments", SLOW_SEGMENTS.format(kbps=400))
    flow = segment_get()
    flow.request.http_version = "HTTP/2.0"

    with Lab(**options) as lab:
        lab.run(flow, origin_segment())
        received = lab.received(flow)

    assert received_by(received, 0) > SEGMENT_BYTES
    skipped = [r for r in caplog.records if "not throttled" in r.getMessage()]
    assert len(skipped) == 1
    assert "HTTP/2.0" in skipped[0].getMessage() and "HTTP/1" in skipped[0].getMessage()
