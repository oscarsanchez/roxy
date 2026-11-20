"""App Profiles: one Product App's Public Endpoint allowlist, Scenarios and mocks, kept in
the user's settings root (apps/<name>/) and loaded for a session with `lab_app`."""

import json

import pytest

from chain import SECRET, TUNNEL_OPTIONS, assert_refused, run_chain, tunnel_flow, origin_json


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
