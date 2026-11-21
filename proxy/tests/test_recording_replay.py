"""Recording and replay: a Recording gives the Lab App the same Origin responses again.

start-lab saves every session (mitmproxy's save_stream_file) and, in replay
mode, serves a Recording with mitmproxy's server replay. These tests run
those built-ins after the lab chain, as mitmweb does.
"""

from mitmproxy import http
from mitmproxy.test import tutils

from chain import LAN_PROXY_BASE, Lab, SECRET, TUNNEL_HOST, TUNNEL_PORT, lab_flow, tunnel_flow


REPLAY_MODE = {"server_replay_reuse": True, "server_replay_extra": "404"}  # as start-lab --replay sets it
OUTSIDE_LAN = ("203.0.113.7", 51000)


def uuid_response(uuid):
    """An Origin whose data changes on every request, like httpbin /uuid."""
    return tutils.tresp(
        headers=http.Headers(content_type="application/json"),
        content=f'{{"uuid": "{uuid}"}}'.encode(),
    )


def record(session, *flows_and_responses):
    with Lab(save_stream_file=str(session)) as lab:
        for flow, response in flows_and_responses:
            lab.run(flow, response)


def test_a_replayed_session_answers_with_the_recorded_response_after_the_origin_changes(tmp_path):
    session = tmp_path / "session.mitm"
    record(session, (lab_flow("/https://httpbin.org/uuid"), uuid_response("recorded")))

    with Lab(server_replay=[str(session)], **REPLAY_MODE) as lab:
        replies = []
        for _ in range(2):  # the Lab App may run the case more than once
            flow = lab_flow("/https://httpbin.org/uuid")
            forwarded = lab.run(flow, uuid_response("changed"))
            replies.append((forwarded, flow.response.content))

    assert replies == [(None, b'{"uuid": "recorded"}')] * 2  # the Origin is not contacted


def test_a_session_recorded_from_one_client_replays_with_the_replaying_clients_proxy_base(tmp_path):
    session = tmp_path / "session.mitm"
    redirect = tutils.tresp(status_code=302, headers=http.Headers(location="https://httpbin.org/json"), content=b"")
    record(session, (lab_flow("/https://httpbin.org/redirect/1"), redirect))  # recorded: LAN_PROXY_BASE Proxy Base

    with Lab(server_replay=[str(session)], lab_secret=SECRET, lab_tunnel_port=TUNNEL_PORT, **REPLAY_MODE) as lab:
        flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/redirect/1")
        lab.run(flow, uuid_response("unused"))

    assert flow.response.headers["location"] == f"https://{TUNNEL_HOST}/{SECRET}/https://httpbin.org/json"


def test_a_session_recorded_in_one_separator_form_replays_in_the_replaying_requests_form(tmp_path):
    session = tmp_path / "session.mitm"
    redirect = tutils.tresp(status_code=302, headers=http.Headers(location="https://httpbin.org/json"), content=b"")
    record(session, (lab_flow("/https://httpbin.org/redirect/1"), redirect))  # recorded in the lab's own form

    with Lab(server_replay=[str(session)], **REPLAY_MODE) as lab:
        flow = lab_flow("/;https://httpbin.org/redirect/1")  # replayed in the Charles-style form
        lab.run(flow, uuid_response("unused"))

    assert flow.response.headers["location"] == f"{LAN_PROXY_BASE}/;https://httpbin.org/json"


def test_in_replay_mode_a_request_the_guards_refuse_stays_refused(tmp_path):
    session = tmp_path / "session.mitm"
    record(session, (lab_flow("/https://httpbin.org/uuid"), uuid_response("recorded")))

    with Lab(server_replay=[str(session)], **REPLAY_MODE) as lab:
        flow = lab_flow("/https://httpbin.org/uuid", peer=OUTSIDE_LAN)
        lab.run(flow, uuid_response("changed"))

    assert flow.response.status_code == 403
    assert flow.response.headers["X-Lab-Blocked"] == "client-ip"
    assert not flow.is_replay


def test_in_replay_mode_a_request_the_session_did_not_record_never_reaches_the_origin(tmp_path):
    session = tmp_path / "session.mitm"
    record(session, (lab_flow("/https://httpbin.org/uuid"), uuid_response("recorded")))

    with Lab(server_replay=[str(session)], **REPLAY_MODE) as lab:
        flow = lab_flow("/https://httpbin.org/json")
        forwarded = lab.run(flow, uuid_response("live"))

    assert forwarded is None  # offline: the Origin is not contacted
    assert flow.response.status_code == 404


def test_in_replay_mode_an_unrecorded_request_the_guards_refuse_stays_refused(tmp_path):
    session = tmp_path / "session.mitm"
    record(session, (lab_flow("/https://httpbin.org/uuid"), uuid_response("recorded")))

    with Lab(server_replay=[str(session)], **REPLAY_MODE) as lab:
        flow = lab_flow("/https://httpbin.org/json", peer=OUTSIDE_LAN)
        lab.run(flow, uuid_response("live"))

    assert flow.response.status_code == 403
    assert flow.response.headers["X-Lab-Blocked"] == "client-ip"
