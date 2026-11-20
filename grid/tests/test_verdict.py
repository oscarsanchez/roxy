"""The grid runner's oracle: a cell's verdict from its two runs (Seam B's pure logic)."""

from dataclasses import replace

from verdict import Cell, Run, cell_from_config, device_flows, judge, result_line, row

PROXY_BASE = "http://192.0.2.10:8080"

JSON_CELL = Cell(
    flavour="classic",
    device_kind="physical",
    traffic_class="json",
    case="json_get",
    scenario="json-503",
    expect_hosts=["httpbin.org"],
    ok={"status": "200"},
)


def flow(host, status=200, blocked=None):
    headers = [["X-Lab-Blocked", blocked]] if blocked else []
    return {"request": {"host": host, "path": "/x"}, "response": {"status_code": status, "headers": headers}}


def run(result, flows=(), console=""):
    return Run(result=result, flows=list(flows), console=console)


BASELINE = run("LABRESULT json_get run=1 status=200 bytes=429 fp=9274ffd9cf27", [flow("httpbin.org")])
MANIPULATED = run("LABRESULT json_get run=2 status=503 bytes=429 fp=9274ffd9cf27", [flow("httpbin.org", 503)])


def test_a_cell_passes_when_the_lab_saw_the_hosts_and_the_manipulation_changed_the_result():
    v = judge(JSON_CELL, BASELINE, MANIPULATED, PROXY_BASE)
    assert v.outcome == "pass"
    assert "status=200 -> status=503" in v.reason


def test_a_cell_fails_when_the_manipulation_left_the_result_unchanged():
    same = run("LABRESULT json_get run=2 status=200 bytes=429 fp=9274ffd9cf27", [flow("httpbin.org")])
    v = judge(JSON_CELL, BASELINE, same, PROXY_BASE)
    assert v.outcome == "fail"
    assert "json-503 did not change the result" in v.reason


def test_a_run_without_a_result_line_fails_the_cell_and_says_which_run():
    v = judge(JSON_CELL, BASELINE, run(None), PROXY_BASE)
    assert v.outcome == "fail"
    assert "with json-503: no result line" in v.reason


def test_a_crash_on_the_console_is_reported_as_a_crash():
    crashed = run(None, console="Type Mismatch. (runtime error &h18)\r\nBrightScript Debugger> ")
    v = judge(JSON_CELL, crashed, MANIPULATED, PROXY_BASE)
    assert v.outcome == "fail"
    assert "without a scenario: the Lab App crashed" in v.reason


def test_a_cell_fails_when_the_run_without_a_scenario_did_not_succeed():
    broken = run("LABRESULT json_get run=1 status=0 bytes=0 fp=none", [flow("httpbin.org")])
    v = judge(JSON_CELL, broken, MANIPULATED, PROXY_BASE)
    assert v.outcome == "fail"
    assert "without a scenario the Lab App did not succeed (wants status=200): status=0" in v.reason


HLS_CELL = Cell(
    flavour="classic",
    device_kind="physical",
    traffic_class="hls",
    case="hls",
    scenario="hls-404",
    expect_hosts=["stream.mux.com", "manifest-*.mux.com", "chunk-*.mux.com"],
    ok={"state": "playing"},
)
HLS_ERROR = run("LABRESULT hls run=2 state=error errorCode=-1", [flow("stream.mux.com", 404)])


def test_expected_hosts_may_be_patterns():
    playing = run(
        "LABRESULT hls run=1 state=playing errorCode=0",
        [flow("stream.mux.com"), flow("manifest-gcp-us-east1-vop1.edgemv.mux.com"),
         flow("chunk-oci-us-ashburn-1-vop1.fastly.mux.com", 206)],
    )
    assert judge(HLS_CELL, playing, HLS_ERROR, PROXY_BASE).outcome == "pass"


def test_content_the_lab_never_saw_while_the_lab_app_succeeded_is_a_leak():
    # The app played, so its segments came from somewhere: not through the lab.
    playing = run("LABRESULT hls run=1 state=playing errorCode=0", [flow("stream.mux.com"), flow("manifest-a.mux.com")])
    v = judge(HLS_CELL, playing, HLS_ERROR, PROXY_BASE)
    assert v.outcome == "fail"
    assert "leak: chunk-*.mux.com never reached the lab" in v.reason


def test_flows_the_lab_refused_fail_the_cell():
    refused = run(BASELINE.result, [flow("httpbin.org"), flow("192.0.2.10", 400, blocked="not-prefixed")])
    v = judge(JSON_CELL, refused, MANIPULATED, PROXY_BASE)
    assert v.outcome == "fail"
    assert "the lab refused 192.0.2.10/x (not-prefixed)" in v.reason


def test_an_origin_url_on_the_console_is_a_leak_but_a_prefixed_url_is_not():
    console = (
        "segment http://192.0.2.10:8080/https://chunk-a.mux.com/0.ts\r\n"
        "segment https://chunk-b.mux.com/1.ts?sig=x\r\n"
    )
    noisy = run(MANIPULATED.result, MANIPULATED.flows, console)
    v = judge(JSON_CELL, BASELINE, noisy, PROXY_BASE)
    assert v.outcome == "fail"
    assert "leak: the console with json-503 names https://chunk-b.mux.com/1.ts?sig=x" in v.reason
    assert "chunk-a" not in v.reason


def test_an_xml_namespace_name_on_the_console_is_not_a_leak():
    # RAF's debug output prints the VAST body JSON-escaped; a namespace name is never fetched.
    console = (
        '[RAF] getStringFromUrl: <VAST xmlns:xsi=\\"http://www.w3.org/2001/XMLSchema-instance\\" '
        'xmlns=\\"http://www.iab.com/VAST\\"><Impression>https://pagead2.googlesyndication.com/pcs/view'
        "</Impression>\r\n"
    )
    noisy = run(MANIPULATED.result, MANIPULATED.flows, console)
    v = judge(JSON_CELL, BASELINE, noisy, PROXY_BASE)
    assert "w3.org" not in v.reason
    assert "iab.com" not in v.reason
    assert "leak: the console with json-503 names https://pagead2.googlesyndication.com/pcs/view" in v.reason


def test_a_failing_cell_with_a_known_limit_is_reported_as_the_known_limit():
    cell = Cell(**{**JSON_CELL.__dict__, "known_limit": "Roku 3 has no Widevine L1"})
    v = judge(cell, run(None), MANIPULATED, PROXY_BASE)
    assert v.outcome == "known-limit"
    assert v.reason == "Roku 3 has no Widevine L1 (observed: without a scenario: no result line before the timeout)"


def test_the_result_line_is_matched_by_run_id_not_the_replayed_history():
    console = (
        "LABRESULT json_get run=111 status=200 bytes=429 fp=9274ffd9cf27\r\n"  # replayed on connect
        "------ Running dev 'Lab' main ------\r\n"
        "LABRESULT json_get run=222 status=503 bytes=429 fp=9274ffd9cf27\r\n"
    )
    assert result_line(console, "json_get", "222") == "LABRESULT json_get run=222 status=503 bytes=429 fp=9274ffd9cf27"
    assert result_line(console, "json_get", "333") is None
    assert result_line(console, "json_get", "22") is None


def test_an_rsg_result_line_is_found_inside_its_colour_codes_and_timestamp():
    console = "\x1b[34m[12:00:01.123]: LABRESULT json_get run=222 status=200 bytes=429 fp=9274ffd9cf27\x1b[0m\r\n"
    assert result_line(console, "json_get", "222") == "LABRESULT json_get run=222 status=200 bytes=429 fp=9274ffd9cf27"


def test_colour_codes_after_a_url_on_the_console_are_not_part_of_it():
    console = "\x1b[34m[12:00:01.123]: fetch https://chunk-b.mux.com/1.ts\x1b[0m\r\n"
    noisy = run(MANIPULATED.result, MANIPULATED.flows, console)
    assert "names https://chunk-b.mux.com/1.ts;" in judge(JSON_CELL, BASELINE, noisy, PROXY_BASE).reason + ";"


def test_a_line_still_being_written_is_not_a_result_yet():
    assert result_line("LABRESULT json_get run=222 status=50", "json_get", "222") is None


def lab_flow(device, started, host="httpbin.org", peer="192.0.2.54"):
    """A mitmweb /flows.json entry; the lab's device label is its comment."""
    return {
        "comment": device,
        "client_conn": {"peername": [peer, 50000]},
        "request": {"host": host, "path": "/", "timestamp_start": started},
    }


def test_a_runs_flows_are_the_ones_the_lab_labelled_with_the_target_device_during_the_run():
    flows = [
        lab_flow("Living Room", 99.0),  # before the run
        lab_flow("Living Room", 100.0),
        lab_flow("Living Room", 105.0, peer="127.0.0.1"),
        lab_flow("Bedroom", 105.0, peer="192.0.2.55"),  # another Target Device
        lab_flow("", 105.0),  # unlabelled: not a Target Device
        lab_flow("Living Room", 110.0),  # after the run
    ]
    assert [f["request"]["timestamp_start"] for f in device_flows(flows, "Living Room", 100.0, 110.0)] == [100.0, 105.0]


def test_a_cloud_devices_flows_are_the_ones_labelled_with_its_name_whatever_their_peer():
    flows = [
        lab_flow("Living Room", 105.0),
        lab_flow("Cloud Device", 105.0, peer="127.0.0.1"),  # native: cloudflared on loopback
        lab_flow("Cloud Device", 106.0, peer="172.18.0.3"),  # Compose: cloudflared's container
        lab_flow("", 107.0, peer="127.0.0.1"),
    ]
    assert [f["request"]["timestamp_start"] for f in device_flows(flows, "Cloud Device", 100.0, 110.0)] == [105.0, 106.0]


def test_the_verdict_is_a_row_for_the_evaluation_grid():
    v = judge(JSON_CELL, BASELINE, MANIPULATED, PROXY_BASE)
    assert row(JSON_CELL, v) == (
        "| classic | Physical Device | json | pass | json-503 changed the result: status=200 -> status=503 |"
    )


CA_JSON_CELL = replace(JSON_CELL, ca_routing=True)


def test_in_ca_routing_an_origin_url_on_the_console_is_not_a_leak_when_the_lab_saw_its_host():
    # The CA Routing build calls Origin URLs directly; DNS brings them to the lab.
    console = "fetch https://httpbin.org/json\r\n"
    noisy = run(MANIPULATED.result, MANIPULATED.flows, console)
    assert judge(CA_JSON_CELL, BASELINE, noisy, PROXY_BASE).outcome == "pass"


def test_in_ca_routing_a_console_url_whose_host_never_reached_the_lab_in_that_run_is_a_leak():
    # DNS did not send this host to the lab (not rewritten, or resolved over IPv6).
    console = "fetch https://httpbin.org/json\r\nsegment https://chunk-b.mux.com/1.ts\r\n"
    noisy = run(MANIPULATED.result, MANIPULATED.flows, console)
    v = judge(CA_JSON_CELL, BASELINE, noisy, PROXY_BASE)
    assert v.outcome == "fail"
    assert "leak: the console with json-503 names https://chunk-b.mux.com/1.ts" in v.reason
    assert "httpbin.org/json" not in v.reason


def test_in_ca_routing_content_the_lab_never_saw_while_the_lab_app_succeeded_is_still_a_leak():
    # DNS that did not send httpbin.org to the lab: the Lab App reached the Origin directly.
    direct = run(BASELINE.result, [])
    v = judge(CA_JSON_CELL, direct, MANIPULATED, PROXY_BASE)
    assert v.outcome == "fail"
    assert "leak: httpbin.org never reached the lab" in v.reason


def test_a_ca_routing_row_says_so_in_the_device_column():
    v = judge(CA_JSON_CELL, BASELINE, MANIPULATED, PROXY_BASE)
    assert row(CA_JSON_CELL, v).startswith("| classic | Physical Device (CA Routing) | json | pass |")


def test_a_charles_style_row_says_so_in_the_device_column():
    v = judge(JSON_CELL, BASELINE, MANIPULATED, PROXY_BASE)
    assert row(replace(JSON_CELL, separator="/;"), v).startswith("| classic | Physical Device (/; form) | json | pass |")


def test_a_charles_style_prefixed_url_on_the_console_is_not_a_leak():
    console = f"GET {PROXY_BASE}/;https://httpbin.org/json\n"
    cell = replace(JSON_CELL, separator="/;")
    v = judge(cell, run(BASELINE.result, BASELINE.flows, console), MANIPULATED, PROXY_BASE)
    assert v.outcome == "pass", v.reason


CONFIG = {
    "prefix_routing_fields": ["prefixed"],
    "classes": {
        "image": {
            "case": "image", "scenario": "image-404", "expect_hosts": ["dummyjson.com"],
            "ok": {"status": "200", "prefixed": "yes", "poster": "ready"},
            "known_limits": {"rsg.ca-routing": "Poster has no certificate API", "rsg.cloud": "slow"},
        },
    },
}


def test_a_ca_routing_cell_does_not_require_the_prefix_routing_fields():
    cell = cell_from_config(CONFIG, "classic", "physical", "image", ca_routing=True)
    assert cell.ok == {"status": "200", "poster": "ready"}
    assert cell.ca_routing and cell.known_limit == ""


def test_a_ca_routing_cell_takes_its_flavours_ca_routing_known_limit():
    assert cell_from_config(CONFIG, "rsg", "physical", "image", ca_routing=True).known_limit == "Poster has no certificate API"


def test_a_prefix_routing_cell_keeps_every_ok_field_and_its_device_kinds_known_limit():
    cell = cell_from_config(CONFIG, "rsg", "cloud", "image", ca_routing=False)
    assert cell.ok == {"status": "200", "prefixed": "yes", "poster": "ready"}
    assert cell.known_limit == "slow" and not cell.ca_routing


def test_in_ca_routing_urls_inside_a_response_body_raf_printed_are_not_leaks():
    # CA Routing leaves bodies as Origin URLs: a VAST icon or click-through link is
    # content, never fetched by a TV. The URL RAF fetched still counts.
    console = (
        '[RAF] getStringFromUrl("https://httpbin.org/json") = "<VAST><Icon><StaticResource>'
        '<![CDATA[https://imasdk.googleapis.com/formats/wta/help.png]]></StaticResource>'
        '<IconClickThrough>https://adssettings.google.com/whythisad</IconClickThrough></Icon></VAST>"\r\n'
        '[RAF] getStringFromUrl("https://ads.example.com/tag") = "<VAST/>"\r\n'
    )
    noisy = run(MANIPULATED.result, MANIPULATED.flows, console)
    v = judge(CA_JSON_CELL, BASELINE, noisy, PROXY_BASE)
    assert "imasdk" not in v.reason and "adssettings" not in v.reason
    assert "leak: the console with json-503 names https://ads.example.com/tag" in v.reason


def test_in_ca_routing_raf_structure_dumps_are_not_fetches_but_its_beacons_are():
    # getAds()/showAds() print the ad structure, companion banners included, which a TV
    # never loads. fireBeacon names a fetch.
    console = (
        '[RAF] getAds() = [{"ads":[{"companionads":[{"url":"https://pagead2.googlesyndication.com/simgad/1"}]}]}]\r\n'
        '[RAF] showAds([{"ads":[{"companionads":[{"url":"https://pagead2.googlesyndication.com/simgad/2"}]}]}])\r\n'
        '[RAF] fireBeacon("https://beacons.example.com/view", ...)\r\n'
    )
    noisy = run(MANIPULATED.result, MANIPULATED.flows, console)
    v = judge(CA_JSON_CELL, BASELINE, noisy, PROXY_BASE)
    assert "simgad" not in v.reason
    assert "leak: the console with json-503 names https://beacons.example.com/view" in v.reason
