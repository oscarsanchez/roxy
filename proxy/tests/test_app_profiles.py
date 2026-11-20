"""App Profiles: one Product App's Public Endpoint allowlist, Scenarios and mocks, kept in
the user's settings root (apps/<name>/) and loaded for a session with `lab_app`."""

import re
import subprocess

import pytest
from mitmproxy.exceptions import OptionsError

from chain import Lab, SECRET, TUNNEL_OPTIONS, assert_refused, lab_flow, origin_json, run_chain, tunnel_flow
from lab.app_profiles import (
    AppProfileExists,
    AppProfiles,
    BadAppProfileName,
    BadProfile,
    NotInGitRepo,
    ScenarioInBoth,
    UnknownAppProfile,
)


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


# AppProfiles: the layout, resolution, creation and Scenario lookup that bin/roxy and
# scripts/start-lab use through proxy/cli.py, against the temp settings root and temp git repos.


@pytest.fixture
def lab_scenarios(tmp_path):
    folder = tmp_path / "lab-scenarios"
    folder.mkdir()
    for name in ("json-503", "hls-404"):
        (folder / f"{name}.toml").touch()
    return folder


@pytest.fixture
def profiles(settings, lab_scenarios, monkeypatch):
    # A git hook (scripts/check from the pre-commit hook) exports the checkout's GIT_DIR,
    # which would point git in the temp repos at the roxy repo.
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    return AppProfiles(settings, lab_scenarios)


@pytest.fixture
def repo(tmp_path):
    """A new git repo, with a nested folder; returns its git root (symlinks resolved)."""

    def make(name):
        root = tmp_path / "repos" / name
        (root / "src" / "nested").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        return root.resolve()

    return make


def test_new_records_the_git_root_of_a_nested_folder(profiles, repo):
    root = repo("app-a")

    profiles.new("app-a", cwd=root / "src" / "nested")

    assert profiles.profile("app-a").repo == root
    assert profiles.profile("app-a").origin_allowlist == []


def test_new_refuses_a_name_that_exists_keeping_that_profile(profiles, repo):
    root_a, root_b = repo("app-a"), repo("app-b")
    profiles.new("app-a", cwd=root_a)

    with pytest.raises(AppProfileExists, match="the App Profile 'app-a' already exists, in .*apps/app-a"):
        profiles.new("app-a", cwd=root_b)

    assert profiles.profile("app-a").repo == root_a


def test_new_refuses_a_folder_outside_any_git_repo(profiles, tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()

    with pytest.raises(NotInGitRepo, match="run roxy app new inside the app's git repo"):
        profiles.new("loose", cwd=loose)

    assert profiles.profiles() == []


def test_new_refuses_a_name_that_is_a_path(profiles, repo, settings):
    root = repo("app-a")

    with pytest.raises(BadAppProfileName, match="letters, digits, '.', '_' and '-': '../escape'"):
        profiles.new("../escape", cwd=root)

    assert not (settings / "escape").exists()


def test_profiles_lists_every_app_profile_by_name(profiles, repo):
    profiles.new("app-b", cwd=repo("app-b"))
    profiles.new("app-a", cwd=repo("app-a"))

    assert profiles.profiles() == ["app-a", "app-b"]


def test_resolve_takes_the_profile_named_wherever_it_runs(profiles, repo):
    root_a = repo("app-a")
    profiles.new("app-a", cwd=root_a)
    profiles.new("app-b", cwd=repo("app-b"))

    assert profiles.resolve("app-b", cwd=root_a) == "app-b"


def test_resolve_refuses_an_unknown_name(profiles, tmp_path):
    with pytest.raises(UnknownAppProfile, match=r"unknown App Profile 'nope' \(roxy app list shows them\)"):
        profiles.resolve("nope", cwd=tmp_path)


def test_resolve_takes_the_deepest_profile_whose_repo_holds_the_folder(profiles, repo, tmp_path):
    outer = repo("outer")
    inner = outer / "src" / "inner"
    subprocess.run(["git", "init", "-q", str(inner)], check=True)
    (inner / "lib").mkdir()
    profiles.new("inner", cwd=inner)
    profiles.new("outer", cwd=outer)

    assert profiles.resolve(cwd=inner / "lib") == "inner"
    assert profiles.resolve(cwd=outer / "src" / "nested") == "outer"


def test_resolve_takes_none_outside_every_profiles_repo(profiles, repo, tmp_path):
    profiles.new("app-a", cwd=repo("app-a"))
    (tmp_path / "repos" / "app-a-sibling").mkdir()

    assert profiles.resolve(cwd=tmp_path / "repos" / "app-a-sibling") is None


@pytest.mark.parametrize(
    "content",
    ["{not json", '{"origin_allowlist": []}', '{"repo": "/repos/example", "origin_allowlist": "api.example"}'],
)
def test_a_bad_profile_json_is_refused_naming_the_profile(profiles, app_profile, content):
    (app_profile("example-app") / "profile.json").write_text(content)

    with pytest.raises(BadProfile, match="App Profile 'example-app'"):
        profiles.profile("example-app")


@pytest.mark.parametrize(
    "fallback_origin, reason",
    [
        ({"path": "^/vod/(", "origin": "https://cdn.example"}, "fallback_origin path is not a regex"),
        ({"path": "^/vod/", "origin": "cdn.example"}, "fallback_origin origin must be http(s)://host[:port]"),
        ({"path": "^/vod/", "origin": "https://cdn.example/vod"}, "fallback_origin origin must be http(s)://host"),
        ({"path": "^/vod/", "origin": "ftp://cdn.example"}, "fallback_origin origin must be http(s)://host"),
        ({"path": "^/vod/"}, "fallback_origin must be"),
        ("https://cdn.example", "fallback_origin must be"),
    ],
)
def test_a_bad_fallback_origin_is_refused_naming_the_profile(profiles, app_profile, fallback_origin, reason):
    app_profile("example-app", fallback_origin=fallback_origin)

    with pytest.raises(BadProfile, match=rf"App Profile 'example-app': {re.escape(reason)}"):
        profiles.profile("example-app")


def test_a_bad_fallback_origin_stops_the_lab_from_starting(app_profile):
    app_profile("example-app", fallback_origin={"path": "(", "origin": "https://cdn.example"})

    with pytest.raises(OptionsError, match="App Profile 'example-app': fallback_origin path is not a regex"):
        Lab(lab_app="example-app")


def test_scenarios_lists_the_profiles_then_the_labs_each_with_its_source(profiles, repo):
    profiles.new("app-a", cwd=repo("app-a"))
    (profiles.profile("app-a").scenarios_dir / "empty-catalog.toml").touch()

    assert profiles.scenarios("app-a") == [
        ("empty-catalog", "App Profile app-a"),
        ("hls-404", "lab"),
        ("json-503", "lab"),
    ]
    assert profiles.scenarios(None) == [("hls-404", "lab"), ("json-503", "lab")]


def test_a_scenario_in_both_is_listed_once_refused(profiles, repo):
    profiles.new("app-a", cwd=repo("app-a"))
    (profiles.profile("app-a").scenarios_dir / "json-503.toml").touch()

    listed = profiles.scenarios("app-a")

    assert [name for name, _ in listed] == ["json-503", "hls-404"]
    refused = dict(listed)["json-503"]
    assert isinstance(refused, ScenarioInBoth)
    assert re.search(r"'json-503' is in both the lab's Scenarios .* and the App Profile's .*app-a", str(refused))


def test_source_names_where_one_scenario_comes_from(profiles, repo):
    profiles.new("app-a", cwd=repo("app-a"))
    scenarios = profiles.profile("app-a").scenarios_dir
    (scenarios / "empty-catalog.toml").touch()
    (scenarios / "hls-404.toml").touch()

    assert profiles.source("app-a", "empty-catalog") == "App Profile app-a"
    assert profiles.source("app-a", "json-503") == "lab"
    assert profiles.source(None, "json-503") == "lab"
    with pytest.raises(ScenarioInBoth, match="'hls-404' is in both"):
        profiles.source("app-a", "hls-404")
