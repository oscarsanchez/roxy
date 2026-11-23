"""The Lab Session client: what bin/roxy and scripts/launch ask the running lab through
mitmweb's API (its state, its active Scenario, its flows), at LabSession's interface.
The lab is FakeMitmweb, mitmweb's API in memory; one test speaks real HTTP to it."""

import json
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from mitmproxy import flowfilter, http, io
from mitmproxy.exceptions import OptionsError
from mitmproxy.test import tutils

from chain import Lab, lab_flow
from lab.lab_session import (
    BadFilter,
    HttpTransport,
    LabDown,
    LabSession,
    LabState,
    RuleFlows,
    ScenarioRefused,
    ScenarioRules,
    WrongPassword,
    new_run_id,
    parse_since,
)

LAB_SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"  # the lab's own, its default folder
START = 1763632800  # 2025-11-20T10:00:00Z


@pytest.fixture
def recorded_flows(dns):
    """Three flows recorded by the full lab chain running the json-503 Scenario, as mitmweb
    keeps them. Flow i starts at START + 60 * i and takes 250 ms:
      0. Living Room POSTs 8 bytes to https://httpbin.org/post; the Origin answers 12 bytes.
      1. Bedroom GETs http://router.example/admin; the lab refuses it (origin-address).
      2. Living Room GETs https://httpbin.org/json; the Scenario's rule turns it into a 503.
    """
    dns["router.example"] = ["192.0.2.200"]  # a private address
    post = lab_flow("/https://httpbin.org/post")
    post.request.method = "POST"
    post.request.content = b'{"q": 1}'
    flows = [
        (post, origin(b'{"ok": true}')),
        (lab_flow("/http://router.example/admin", peer=("192.0.2.55", 51000)), origin(b"")),
        (lab_flow("/https://httpbin.org/json"), origin(b'{"slideshow": {}}')),
    ]
    with Lab(lab_scenario="json-503") as lab:
        for i, (flow, response) in enumerate(flows):
            lab.run(flow, response)
            flow.timestamp_created = flow.request.timestamp_start = START + 60 * i
            flow.response.timestamp_end = flow.request.timestamp_start + 0.25
    return [flow for flow, _ in flows]


def origin(body):
    return tutils.tresp(headers=http.Headers(content_type="application/json"), content=body)


class FakeMitmweb:
    """mitmweb's API in memory, as LabSession's transport: its options, with each options
    PUT checked by a lab started with it (a value the lab rejects gets 400, with the lab's
    message, as from mitmweb), and its flows, dumped through a filter expression as
    mitmweb's GET flows/dump does."""

    def __init__(self, flows=(), **options):
        self.options = {"lab_app": "", "lab_scenario": "", "lab_ca_routing": False,
                        "lab_proxy_routing_port": 8090, "lab_scenarios_dir": str(LAB_SCENARIOS), **options}
        self.flows = list(flows)
        self.up = True
        self.signed_in = True  # False: the password LabSession signs in with is wrong
        self.puts = []  # every PUT, as (path, body)
        self.gets = []  # every GET's path

    def get(self, path):
        self.gets.append(path)
        if refused := self._refusal():
            return refused
        url = urlsplit(path)
        if url.path == "options.json":
            return 200, json.dumps({name: {"value": value} for name, value in self.options.items()}).encode()
        if url.path == "flows/dump":
            return self._dump(parse_qs(url.query).get("filter"))
        return 404, b""

    def _dump(self, filter):
        try:
            match = flowfilter.parse(filter[0]) if filter else lambda flow: True
        except ValueError:
            return 400, b"Invalid filter argument / regex"
        dump = BytesIO()
        writer = io.FlowWriter(dump)
        for flow in self.flows:
            if match(flow):
                writer.add(flow)
        return 200, dump.getvalue()

    def put(self, path, body):
        self.puts.append((path, body))
        if refused := self._refusal():
            return refused
        try:
            with Lab(**{**self.options, **body}):
                pass
        except OptionsError as e:
            return 400, str(e).encode()
        self.options.update(body)
        return 200, b""

    def _refusal(self):
        """None, or the answer mitmweb gives every request: none at all, or a refused sign-in."""
        if not self.up:
            raise LabDown("nothing answers")
        if not self.signed_in:
            return 403, b""


def test_the_state_names_the_loaded_app_profile_the_active_scenarios_in_order_and_where_they_are():
    lab = FakeMitmweb(
        lab_app="example-app", lab_scenario="json-503,hls-404", lab_ca_routing=True, lab_proxy_routing_port=8091,
    )

    assert LabSession(lab).state() == LabState(
        app="example-app", scenarios=["json-503", "hls-404"], ca_routing=True, proxy_routing_port=8091,
        scenarios_dir=str(LAB_SCENARIOS),
    )


def test_the_state_of_a_lab_without_either_is_none_and_no_scenarios():
    state = LabSession(FakeMitmweb()).state()

    assert (state.app, state.scenarios, state.ca_routing) == (None, [], False)


EVERY_OPERATION = {
    "state": lambda session: session.state(),
    "set_scenarios": lambda session: session.set_scenarios(["json-503"]),
    "add_scenario": lambda session: session.add_scenario("json-503"),
    "remove_scenario": lambda session: session.remove_scenario("json-503"),
    "flows": lambda session: session.flows(),
}


@pytest.mark.parametrize("operation", EVERY_OPERATION.values(), ids=EVERY_OPERATION.keys())
def test_a_lab_that_does_not_answer_is_down(operation):
    lab = FakeMitmweb()
    lab.up = False

    with pytest.raises(LabDown):
        operation(LabSession(lab))


@pytest.mark.parametrize("operation", EVERY_OPERATION.values(), ids=EVERY_OPERATION.keys())
def test_a_wrong_password_is_named(operation):
    lab = FakeMitmweb()
    lab.signed_in = False

    with pytest.raises(WrongPassword, match="MITMWEB_PASSWORD"):
        operation(LabSession(lab))


def test_setting_scenarios_replaces_the_active_set_in_that_order():
    session = LabSession(FakeMitmweb(lab_scenario="image-404"))

    session.set_scenarios(["json-503", "hls-404"])

    assert session.state().scenarios == ["json-503", "hls-404"]


def test_setting_one_scenario_sends_just_its_name():
    lab = FakeMitmweb()

    LabSession(lab).set_scenarios(["json-503"])

    assert lab.puts == [("options", {"lab_scenario": "json-503"})]


@pytest.mark.parametrize("names", [[], [""]], ids=["no names", "an empty name"])
def test_setting_no_scenarios_clears_the_active_set(names):
    session = LabSession(FakeMitmweb(lab_scenario="json-503,hls-404"))

    session.set_scenarios(names)

    assert session.state().scenarios == []


def test_adding_a_scenario_appends_it_to_the_active_set():
    session = LabSession(FakeMitmweb(lab_scenario="json-503"))

    session.add_scenario("hls-404")

    assert session.state().scenarios == ["json-503", "hls-404"]


def test_adding_an_active_scenario_leaves_the_set_as_it_is():
    session = LabSession(FakeMitmweb(lab_scenario="json-503,hls-404"))

    session.add_scenario("json-503")

    assert session.state().scenarios == ["json-503", "hls-404"]


def test_removing_a_scenario_drops_only_it():
    session = LabSession(FakeMitmweb(lab_scenario="json-503,hls-404,image-404"))

    session.remove_scenario("hls-404")

    assert session.state().scenarios == ["json-503", "image-404"]


def test_removing_a_scenario_that_is_not_active_is_refused():
    session = LabSession(FakeMitmweb(lab_scenario="json-503"))

    with pytest.raises(ScenarioRefused, match=r"'hls-404' is not active.*json-503"):
        session.remove_scenario("hls-404")
    assert session.state().scenarios == ["json-503"]


REFUSED_CHANGES = {
    "set_scenarios": lambda session: session.set_scenarios(["hls-404", "no-such-scenario"]),
    "add_scenario": lambda session: session.add_scenario("no-such-scenario"),
}


@pytest.mark.parametrize("change", REFUSED_CHANGES.values(), ids=REFUSED_CHANGES.keys())
def test_an_unknown_scenario_is_refused_with_the_labs_reason_and_the_set_stays(change):
    session = LabSession(FakeMitmweb(lab_scenario="json-503"))

    with pytest.raises(ScenarioRefused, match=r"'no-such-scenario'.*no-such-scenario"):
        change(session)
    assert session.state().scenarios == ["json-503"]


def test_flows_are_summed_up_in_the_documented_shape_oldest_first(recorded_flows):
    flows = LabSession(FakeMitmweb(recorded_flows)).flows()

    assert [flow["id"] for flow in flows] == [flow.id for flow in recorded_flows]
    assert {k: v for k, v in flows[0].items() if k != "id"} == {
        "time": "2025-11-20T10:00:00.000Z", "device": "Living Room", "method": "POST", "url": "https://httpbin.org/post",
        "status": 200, "request_bytes": 8, "response_bytes": 12, "duration_ms": 250, "refusal": None, "scenario_rules": [],
    }
    # The example flow in docs/agent-setup.md.
    assert {k: v for k, v in flows[2].items() if k != "id"} == {
        "time": "2025-11-20T10:02:00.000Z", "device": "Living Room", "method": "GET", "url": "https://httpbin.org/json",
        "status": 503, "request_bytes": 0, "response_bytes": 17, "duration_ms": 250, "refusal": None,
        "scenario_rules": ["json-503/httpbin json fails"],
    }


def test_a_flow_the_lab_refused_carries_its_refusal_reason(recorded_flows):
    refused = LabSession(FakeMitmweb(recorded_flows)).flows()[1]

    assert (refused["device"], refused["status"], refused["refusal"]) == ("Bedroom", 403, "origin-address")


def test_a_flow_from_a_client_nothing_names_has_no_device():
    flow = lab_flow("/https://httpbin.org/json", peer=("192.0.2.10", 51000))  # the Mac's own curl
    with Lab() as lab:
        lab.run(flow, origin(b"{}"))

    assert LabSession(FakeMitmweb([flow])).flows()[0]["device"] is None


def test_a_filter_expression_keeps_only_the_flows_mitmweb_matches(recorded_flows):
    flows = LabSession(FakeMitmweb(recorded_flows)).flows(filter='~d httpbin.org & ~comment "Living Room"')

    assert [flow["url"] for flow in flows] == ["https://httpbin.org/post", "https://httpbin.org/json"]


def test_a_filter_expression_mitmweb_rejects_is_named(recorded_flows):
    with pytest.raises(BadFilter, match="~bad"):
        LabSession(FakeMitmweb(recorded_flows)).flows(filter="~bad")


def times(flows):
    return [flow["time"][11:16] for flow in flows]


def test_since_a_run_id_keeps_the_flows_from_that_launch_on(recorded_flows):
    flows = LabSession(FakeMitmweb(recorded_flows)).flows(since=parse_since("176363286012345"))  # launched 10:01

    assert times(flows) == ["10:01", "10:02"]


def test_since_a_time_keeps_the_flows_from_then_on(recorded_flows):
    flows = LabSession(FakeMitmweb(recorded_flows)).flows(since=parse_since("2025-11-20T10:02:00Z"))

    assert times(flows) == ["10:02"]


def test_since_takes_only_a_run_id_or_a_time():
    with pytest.raises(ValueError, match="'yesterday'"):
        parse_since("yesterday")


def test_a_new_run_id_reads_back_as_its_launch_time():
    before = int(time.time())
    run_id = new_run_id()

    assert run_id.isdigit()
    assert before <= parse_since(run_id) <= time.time()


def test_a_limit_keeps_the_last_flows_after_since(recorded_flows):
    session = LabSession(FakeMitmweb(recorded_flows))

    assert times(session.flows(limit=2)) == ["10:01", "10:02"]
    assert times(session.flows(since=parse_since("2025-11-20T10:00:00Z"), limit=1)) == ["10:02"]


def test_a_throttled_flow_is_timed_to_its_last_byte_at_the_client(scenarios):
    options = scenarios("slow-segments", '[[rule]]\nname = "slow"\nfilter = "~u /video/"\nthrottle = { kbps = 400 }\n')
    flow = lab_flow("/https://test-streams.mux.dev/video/720p/segment-1.ts")
    response = tutils.tresp(headers=http.Headers(content_type="video/mp2t"), content=b"\x47" * 500_000)  # 500 KB
    response.timestamp_end = flow.request.timestamp_start + 3  # the Origin took 3 s
    with Lab(**options) as lab:
        lab.run(flow, response)

    [timed] = LabSession(FakeMitmweb([flow])).flows()

    assert timed["duration_ms"] == pytest.approx(13_000, abs=100)  # then 10 s paced


def scenario_rules(lab, app_scenarios_dir=None):
    """The rules of LAB's active Scenarios, as roxy status reads them: its state, then the rules."""
    session = LabSession(lab)
    return session.scenario_rules(session.state(), app_scenarios_dir)


def test_each_active_scenarios_rules_count_the_flows_they_acted_on_in_scenario_then_file_order(recorded_flows):
    session = LabSession(FakeMitmweb(recorded_flows, lab_scenario="hls-404,json-503"))

    assert session.scenario_rules(session.state(), app_scenarios_dir=None) == [
        ScenarioRules("hls-404", [RuleFlows("hls-404", "mux master playlist missing", 0)], None),
        ScenarioRules("json-503", [RuleFlows("json-503", "httpbin json fails", 1)], None),
    ]


def test_since_a_launch_a_rule_counts_only_the_flows_from_then_on(recorded_flows):
    session = LabSession(FakeMitmweb(recorded_flows, lab_scenario="json-503"))

    [after] = session.scenario_rules(session.state(), None, since=parse_since("2025-11-20T10:02:00.001Z"))  # the 503 at 10:02

    assert after.rules == [RuleFlows("json-503", "httpbin json fails", 0)]


def test_a_rule_named_the_same_in_two_scenarios_is_counted_per_scenario(scenarios):
    rule = '[[rule]]\nname = "json fails"\nfilter = "~u /json"\nstatus = {status}\n'
    scenarios("first", rule.format(status=503))
    options = {**scenarios("second", rule.format(status=500)), "lab_scenario": "second,first"}
    flow = lab_flow("/https://httpbin.org/json")
    with Lab(**{**options, "lab_scenario": "first"}) as lab:
        lab.run(flow, origin(b"{}"))

    rules = scenario_rules(FakeMitmweb([flow], **options))

    assert [scenario.rules for scenario in rules] == [
        [RuleFlows("second", "json fails", 0)], [RuleFlows("first", "json fails", 1)],
    ]


def test_an_active_scenario_whose_file_no_longer_loads_says_why_instead_of_its_rules(scenarios):
    options = scenarios("broken", '[[rule]]\nname = "no filter"\nstatus = 503\n')

    [broken] = scenario_rules(FakeMitmweb(**options))

    assert (broken.scenario, broken.rules) == ("broken", [])
    assert "'no filter': needs a filter expression" in broken.error


def test_an_app_profiles_scenario_is_found_in_its_folder_before_the_labs(tmp_path):
    (tmp_path / "catalog-fails.toml").write_text('[[rule]]\nname = "catalog 500"\nfilter = "~u /catalog"\nstatus = 500\n')

    [found] = scenario_rules(FakeMitmweb(lab_app="example-app", lab_scenario="catalog-fails"), tmp_path)

    assert found.rules == [RuleFlows("catalog-fails", "catalog 500", 0)]


def test_with_no_active_scenario_the_rules_need_no_flows_from_the_lab(recorded_flows):
    lab = FakeMitmweb(recorded_flows)  # a long session's flows are large: their bodies come too

    assert scenario_rules(lab) == []
    assert [path for path in lab.gets if path.startswith("flows")] == []


def test_the_rules_fetch_only_the_marked_flows_never_every_body(recorded_flows):
    """Every flow a rule acted on is marked, so ~marked loses none of them; the rest of a long
    session (segments, most traffic) stays in mitmweb with its bodies."""
    lab = FakeMitmweb(recorded_flows, lab_scenario="json-503")

    scenario_rules(lab)

    assert [path for path in lab.gets if path.startswith("flows")] == ["flows/dump?filter=~marked"]


def test_reading_the_flows_never_changes_the_lab(recorded_flows):
    lab = FakeMitmweb(recorded_flows)

    LabSession(lab).flows(filter="~u /json", since=START, limit=1)

    assert lab.puts == []


# HttpTransport, the running lab's, against FakeMitmweb behind a local HTTP server that
# checks requests as mitmweb does: the password as a Bearer token, and for a PUT a JSON
# body and an XSRF cookie matching the X-XSRFToken header.

PASSWORD = "test-password"


@pytest.fixture
def localhost(dns):
    dns["127.0.0.1"] = ["127.0.0.1"]  # the stubbed DNS would send it to a public IP


@pytest.fixture
def mitmweb_port(recorded_flows, localhost):
    lab = FakeMitmweb(recorded_flows)

    class Mitmweb(BaseHTTPRequestHandler):
        def do_GET(self):
            self.answer(lambda: lab.get(self.path.removeprefix("/")))

        def do_PUT(self):
            xsrf = SimpleCookie(self.headers.get("Cookie", "")).get("_mitmproxy_xsrf")
            if not xsrf or xsrf.value != self.headers.get("X-XSRFToken"):
                return self.send(403, b"'_xsrf' argument missing from POST")
            if self.headers.get("Content-Type") != "application/json":
                return self.send(400, b"Invalid Content-Type")
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.answer(lambda: lab.put(self.path.removeprefix("/"), body))

        def answer(self, call):
            if self.headers.get("Authorization") != f"Bearer {PASSWORD}":
                return self.send(403, b"")
            self.send(*call())

        def send(self, status, body):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Mitmweb)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    thread.join()
    server.server_close()


def test_over_http_the_session_signs_in_and_passes_mitmwebs_xsrf_check(mitmweb_port):
    session = LabSession(HttpTransport(mitmweb_port, PASSWORD))

    session.set_scenarios(["json-503"])

    assert session.state().scenarios == ["json-503"]
    assert times(session.flows(filter='~d httpbin.org & ~u "/json"')) == ["10:02"]


def test_over_http_a_wrong_password_is_named(mitmweb_port):
    with pytest.raises(WrongPassword):
        LabSession(HttpTransport(mitmweb_port, "wrong")).state()


def test_over_http_a_port_nothing_listens_on_is_a_lab_down(localhost):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # free once the probe closes

    with pytest.raises(LabDown):
        LabSession(HttpTransport(port, PASSWORD)).state()
