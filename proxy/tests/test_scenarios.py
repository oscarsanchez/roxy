import json
from pathlib import Path

import pytest
from mitmproxy.exceptions import OptionsError

from chain import Lab, fixture_response, lab_flow, origin_json, run_chain


def json_get():
    return lab_flow("/https://httpbin.org/json")


def test_status_override_changes_the_status_the_client_sees(scenarios):
    options = scenarios("fail-json", '''
[[rule]]
name = "httpbin json fails"
filter = "~d httpbin.org & ~u /json"
status = 503
''')
    flow = json_get()

    forwarded = run_chain(flow, origin_json(), **options)

    assert forwarded.url == "https://httpbin.org/json"
    assert flow.response.status_code == 503
    assert flow.response.reason == "Service Unavailable"


def test_a_request_that_matches_no_rule_is_left_alone(scenarios):
    options = scenarios("fail-images", '''
[[rule]]
name = "images fail"
filter = "~u /image"
status = 503
''')
    flow = json_get()

    forwarded = run_chain(flow, origin_json(), **options)

    assert forwarded.url == "https://httpbin.org/json"
    assert flow.response.status_code == 200
    assert flow.response.content == origin_json().content


def test_added_latency_delays_the_request_before_it_reaches_the_origin(scenarios):
    options = scenarios("slow-json", '''
[[rule]]
name = "slow json"
filter = "~u /json"
latency = 0.3
''')
    flow = json_get()

    with Lab(**options) as lab:
        forwarded = lab.run(flow, origin_json())
        waited = lab.reached_origin_after(flow)

    assert waited == pytest.approx(0.3)
    assert forwarded.url == "https://httpbin.org/json"
    assert flow.response.status_code == 200


def test_connection_drop_kills_the_flow_without_reaching_the_origin(scenarios):
    options = scenarios("drop-json", '''
[[rule]]
name = "drop json"
filter = "~u /json"
drop = true
''')
    flow = json_get()

    forwarded = run_chain(flow, origin_json(), **options)

    assert forwarded is None
    assert flow.response is None
    assert flow.error.msg == "Connection killed."


def test_header_replace_sets_a_response_header(scenarios):
    options = scenarios("no-cache", '''
[[rule]]
name = "json is not cacheable"
filter = "~s & ~u /json"
header = { name = "Cache-Control", value = "no-store" }
''')
    flow = json_get()
    origin = origin_json()
    origin.headers["cache-control"] = "max-age=3600"

    forwarded = run_chain(flow, origin, **options)

    assert "cache-control" not in forwarded.headers
    assert flow.response.headers.get_all("cache-control") == ["no-store"]


def test_header_replace_with_an_empty_value_removes_a_request_header(scenarios):
    options = scenarios("no-ua", '''
[[rule]]
name = "anonymous json"
filter = "~q & ~u /json"
header = { name = "User-Agent", value = "" }
''')
    flow = json_get()
    flow.request.headers["user-agent"] = "Roku/DVP-16.0"

    forwarded = run_chain(flow, origin_json(), **options)

    assert "user-agent" not in forwarded.headers


def test_body_replace_rewrites_the_response_body(scenarios):
    options = scenarios("retitle", '''
[[rule]]
name = "retitle the slideshow"
filter = "~s & ~u /json"
body = { pattern = "Sample Slide Show", replacement = "Lab Slide Show" }
''')
    flow = json_get()

    run_chain(flow, origin_json(), **options)

    assert b'"title": "Lab Slide Show"' in flow.response.content
    assert b"Sample Slide Show" not in flow.response.content


def test_map_local_answers_from_a_file_next_to_the_scenario(scenarios, tmp_path):
    (tmp_path / "mocks").mkdir()
    (tmp_path / "mocks" / "empty.json").write_text('{"slideshow": null}')
    options = scenarios("mock-json", '''
[[rule]]
name = "json is mocked"
filter = "~u /json"
map_local = "mocks/empty.json"
''')
    flow = json_get()

    forwarded = run_chain(flow, origin_json(), **options)

    assert forwarded is None
    assert flow.response.status_code == 200
    assert flow.response.content == b'{"slideshow": null}'
    assert flow.response.headers["content-type"] == "application/json"


def test_every_matching_rule_applies_in_file_order(scenarios):
    options = scenarios("broken-json", '''
[[rule]]
name = "json fails"
filter = "~u /json"
status = 500

[[rule]]
name = "and says so"
filter = "~s & ~u /json"
body = { pattern = '\\A.*', replacement = "lab says no" }
''')
    flow = json_get()

    run_chain(flow, origin_json(), **options)

    assert flow.response.status_code == 500
    assert flow.response.content == b"lab says no"


def test_scenario_rules_leave_the_labs_own_refusals_alone(scenarios):
    options = scenarios("everything-fails", '''
[[rule]]
name = "everything fails"
filter = "~all"
status = 503
''')
    flow = lab_flow("/https://httpbin.org/json", peer=("10.9.9.9", 51000))

    forwarded = run_chain(flow, origin_json(), **options)

    assert forwarded is None
    assert flow.response.status_code == 403
    assert flow.response.headers["x-lab-blocked"] == "client-ip"


def test_an_origin_or_a_rule_cannot_pass_its_response_off_as_a_lab_refusal(scenarios):
    options = scenarios("fake-refusal", '''
[[rule]]
name = "claims to be the lab"
filter = "~s & ~u /json"
header = { name = "X-Lab-Blocked", value = "client-ip" }

[[rule]]
name = "json fails"
filter = "~u /json"
status = 503
''')
    from_origin, from_rule = json_get(), json_get()
    origin = origin_json()
    origin.headers["X-Lab-Blocked"] = "origin-host"

    run_chain(from_origin, origin, **options)
    run_chain(from_rule, origin_json(), **options)

    assert from_origin.response.status_code == 503  # later rules still apply
    assert from_rule.response.status_code == 503
    assert not from_origin.marked and not from_rule.marked


FAIL_JSON = '''
[[rule]]
name = "json fails"
filter = "~u /json"
status = {status}
'''


def test_switching_the_active_scenario_applies_to_the_next_flow_without_a_restart(scenarios):
    fail_503 = scenarios("fail-503", FAIL_JSON.format(status=503))
    scenarios("fail-418", FAIL_JSON.format(status=418))

    with Lab(**fail_503) as lab:
        first = json_get()
        lab.run(first, origin_json())
        lab.set_options(lab_scenario="fail-418")
        second = json_get()
        lab.run(second, origin_json())
        lab.set_options(lab_scenario="")
        third = json_get()
        lab.run(third, origin_json())

    assert [f.response.status_code for f in (first, second, third)] == [503, 418, 200]


@pytest.mark.parametrize("toml", [
    '[[rule]]\nfilter = "~u /json"\nstatus = 503\n',
    '[[rule]]\nname = "bad filter"\nfilter = "~nope"\nstatus = 503\n',
    '[[rule]]\nname = "no action"\nfilter = "~u /json"\n',
    '[[rule]]\nname = "unknown action"\nfilter = "~u /json"\nteleport = true\n',
    '[[rule]]\nname = "two actions"\nfilter = "~u /json"\nstatus = 503\ndrop = true\n',
    '[[rule]]\nname = "bad status"\nfilter = "~u /json"\nstatus = "soon"\n',
    '[[rule]]\nname = "missing file"\nfilter = "~u /json"\nmap_local = "nope.json"\n',
    'not toml [',
])
def test_an_invalid_scenario_is_rejected_and_the_active_one_stays(scenarios, toml):
    active = scenarios("fail-503", FAIL_JSON.format(status=503))
    scenarios("broken", toml)

    with Lab(**active) as lab:
        with pytest.raises(OptionsError):
            lab.set_options(lab_scenario="broken")
        flow = json_get()
        lab.run(flow, origin_json())

    assert flow.response.status_code == 503


def test_an_unknown_scenario_name_is_rejected(scenarios):
    options = scenarios("fail-503", FAIL_JSON.format(status=503))

    with Lab(**options) as lab, pytest.raises(OptionsError):
        lab.set_options(lab_scenario="no-such-scenario")


def test_editing_the_active_scenario_file_reloads_it(scenarios):
    options = scenarios("fail-json", FAIL_JSON.format(status=503))

    with Lab(**options) as lab:
        first = json_get()
        lab.run(first, origin_json())
        scenarios("fail-json", FAIL_JSON.format(status=418))
        second = json_get()
        lab.run(second, origin_json())

    assert [first.response.status_code, second.response.status_code] == [503, 418]


SHIPPED = sorted(p.stem for p in (Path(__file__).parent.parent / "scenarios").glob("*.toml"))


@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_scenario_loads(name):
    with Lab(lab_scenario=name):
        pass


def test_the_shipped_json_503_scenario_fails_the_json_get_case():
    flow = json_get()

    run_chain(flow, origin_json(), lab_scenario="json-503")

    assert flow.response.status_code == 503


def test_the_shipped_json_post_edit_scenario_changes_what_the_json_post_case_sends():
    flow = lab_flow("/https://httpbin.org/post")
    flow.request.method = "POST"
    flow.request.headers["content-type"] = "application/json"
    flow.request.content = b'{"case":"json_post","n":1,"ok":true}'  # as both Lab Apps send it
    origin = fixture_response("httpbin-post.json", "application/json")  # echoes ok=true

    forwarded = run_chain(flow, origin, lab_scenario="json-post-edit")

    assert forwarded.content == b'{"case":"json_post","n":1,"ok":false}'
    assert json.loads(flow.response.text)["data"] == '{"case":"json_post","n":1,"ok":true}'  # request only


def test_a_broken_edit_keeps_the_last_good_rules(scenarios):
    options = scenarios("fail-json", FAIL_JSON.format(status=503))

    with Lab(**options) as lab:
        scenarios("fail-json", "not toml [")
        flow = json_get()
        lab.run(flow, origin_json())

    assert flow.response.status_code == 503
