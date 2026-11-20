"""App Profiles: one Product App's Public Endpoint allowlist, Scenarios and mocks, kept in
the user's settings root (apps/<name>/) and loaded for a session with `lab_app`."""

import json

import pytest
from mitmproxy.exceptions import OptionsError

from chain import Lab, SECRET, TUNNEL_OPTIONS, assert_refused, lab_flow, origin_json, run_chain, tunnel_flow


@pytest.fixture
def app_profile(settings):
    """Write an App Profile into the temp settings root, as `roxy app new` lays it out;
    returns its folder."""

    def write(name, origin_allowlist=()):
        folder = settings / "apps" / name
        (folder / "scenarios").mkdir(parents=True)
        (folder / "profile.json").write_text(
            json.dumps({"repo": "/repos/example", "origin_allowlist": list(origin_allowlist)})
        )
        return folder

    return write


def test_the_loaded_profiles_allowlist_admits_its_host_through_the_public_endpoint(app_profile):
    app_profile("example-app", origin_allowlist=["api.example-app.example"])
    flow = tunnel_flow(f"/{SECRET}/https://api.example-app.example/catalog")

    forwarded = run_chain(flow, origin_json(), lab_app="example-app", **TUNNEL_OPTIONS)

    assert forwarded.url == "https://api.example-app.example/catalog"
    assert flow.response.status_code == 200


def test_without_the_profile_the_public_endpoint_refuses_that_host(app_profile):
    app_profile("example-app", origin_allowlist=["api.example-app.example"])
    flow = tunnel_flow(f"/{SECRET}/https://api.example-app.example/catalog")

    assert_refused(flow, run_chain(flow, origin_json(), **TUNNEL_OPTIONS), "origin-host")


def test_a_profile_scenarios_map_local_answers_from_the_profiles_mocks(app_profile):
    scenarios = app_profile("example-app") / "scenarios"
    (scenarios / "mocks").mkdir()
    (scenarios / "mocks" / "catalog.json").write_text('{"items": []}')
    (scenarios / "empty-catalog.toml").write_text('''
[[rule]]
name = "the catalog is empty"
filter = "~u /json"
map_local = "mocks/catalog.json"
''')
    flow = lab_flow("/https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json(), lab_app="example-app", lab_scenario="empty-catalog")

    assert forwarded is None
    assert flow.response.status_code == 200
    assert flow.response.content == b'{"items": []}'


def test_a_profile_scenario_named_like_one_of_the_labs_own_is_refused(app_profile):
    scenarios = app_profile("example-app") / "scenarios"
    (scenarios / "json-503.toml").write_text('[[rule]]\nname = "mine"\nfilter = "~u /json"\nstatus = 500\n')

    with pytest.raises(OptionsError, match=r"'json-503' is in both the lab's Scenarios .* and the App Profile's"):
        Lab(lab_app="example-app", lab_scenario="json-503")
