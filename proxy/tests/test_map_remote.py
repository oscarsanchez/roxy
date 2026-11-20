"""The map_remote Scenario action: send matching requests to another Origin host."""

import pytest
from mitmproxy.exceptions import OptionsError

from chain import (
    LAN_PROXY_BASE,
    Lab,
    SECRET,
    TUNNEL_OPTIONS,
    assert_refused,
    fixture_response,
    lab_flow,
    origin_json,
    run_chain,
    tunnel_flow,
)


@pytest.fixture
def map_remote(tmp_path):
    """Activate a Scenario with one map_remote rule; returns its lab options."""

    def activate(target, filter_expr="~d httpbin.org"):
        (tmp_path / "swap.toml").write_text(
            f'[[rule]]\nname = "swap"\nfilter = "{filter_expr}"\nmap_remote = "{target}"\n'
        )
        return {"lab_scenarios_dir": str(tmp_path), "lab_scenario": "swap"}

    return activate


def test_scheme_host_and_port_are_swapped_and_path_query_and_host_header_follow(map_remote):
    flow = lab_flow("/https://httpbin.org/anything/json?case=1&n=2")

    forwarded = run_chain(flow, origin_json(), **map_remote("http://postman-echo.com:8080"))

    assert forwarded.url == "http://postman-echo.com:8080/anything/json?case=1&n=2"
    assert forwarded.headers["host"] == "postman-echo.com:8080"
    assert flow.response.status_code == 200


@pytest.mark.parametrize("target", [
    "postman-echo.com",  # no scheme
    "ftp://postman-echo.com",
    "https://",  # no host
    "https://postman-echo.com/anything",  # a path: only scheme, host and port swap
    "https://postman-echo.com?x=1",
    "https://user@postman-echo.com",
    "https://postman-echo.com:99999",
])
def test_an_invalid_target_is_rejected_and_the_active_scenario_stays(map_remote, tmp_path, target):
    good = map_remote("https://postman-echo.com")
    (tmp_path / "broken.toml").write_text(f'[[rule]]\nname = "bad"\nfilter = "~all"\nmap_remote = "{target}"\n')

    with Lab(**good) as lab:
        with pytest.raises(OptionsError):
            lab.set_options(lab_scenario="broken")
        forwarded = lab.run(lab_flow("/https://httpbin.org/json"), origin_json())

    assert forwarded.url == "https://postman-echo.com/json"


def test_a_swap_to_a_host_that_resolves_private_is_refused(map_remote, dns):
    dns["postman-echo.com"] = ["10.0.0.7"]
    flow = lab_flow("/https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json(), **map_remote("https://postman-echo.com"))

    assert_refused(flow, forwarded, "origin-address")


def test_through_the_public_endpoint_a_swap_to_a_non_allowlisted_host_is_refused(map_remote):
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json(), **TUNNEL_OPTIONS, **map_remote("https://example.net"))

    assert_refused(flow, forwarded, "origin-host")


def test_a_manifest_from_the_swapped_host_is_rewritten_with_the_requests_proxy_base(map_remote):
    flow = lab_flow("/https://stream.mux.com/videos/master.m3u8")
    swap = map_remote("https://test-streams.mux.dev", filter_expr="~d stream.mux.com")

    forwarded = run_chain(flow, fixture_response("hls-master.m3u8", "application/vnd.apple.mpegurl"), **swap)

    assert forwarded.url == "https://test-streams.mux.dev/videos/master.m3u8"
    lines = flow.response.text.splitlines()
    assert f"{LAN_PROXY_BASE}/https://test-streams.mux.dev/videos/gear2/prog_index.m3u8" in lines  # root-relative
    assert (
        f"{LAN_PROXY_BASE}/https://manifest.edgemv.mux.com/tok/rendition.m3u8"
        "?cdn=edgemv&expires=1700000000&skid=a1&signature=x%2Fy"
    ) in lines
