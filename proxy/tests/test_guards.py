import ipaddress
import json

import pytest

from chain import Lab, assert_refused, lab_flow, origin_json, run_chain


@pytest.mark.parametrize("peer", [("8.8.8.8", 4000), ("10.0.0.5", 4000), ("198.51.100.1", 4000)])
def test_a_client_outside_the_lan_subnet_is_refused(peer):
    flow = lab_flow("/https://httpbin.org/json", peer=peer)

    forwarded = run_chain(flow, origin_json())

    assert_refused(flow, forwarded, "client-ip")


def test_a_lan_client_is_recognised_on_an_ipv4_mapped_ipv6_connection():
    flow = lab_flow("/https://httpbin.org/json", peer=("::ffff:192.0.2.54", 4000, 0, 0))

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == "https://httpbin.org/json"


DOCKER_DESKTOP_HOST = ("192.168.65.1", 4000)  # every published-port client under Docker Desktop (macOS)


def test_docker_desktops_host_address_is_not_a_lan_client_by_default():
    flow = lab_flow("/https://httpbin.org/json", peer=DOCKER_DESKTOP_HOST)

    assert_refused(flow, run_chain(flow, origin_json()), "client-ip")


def test_under_compose_the_lan_subnets_add_docker_desktops_host_address():
    """As scripts/run-mitmweb passes compose.yaml's LAB_LAN_SUBNETS: one `--set` per subnet."""
    flow = lab_flow("/https://httpbin.org/json", peer=DOCKER_DESKTOP_HOST)

    with Lab() as lab:
        lab.set_from_command_line("lab_lan_subnets=192.0.2.0/24", "lab_lan_subnets=192.168.65.1/32")
        forwarded = lab.run(flow, origin_json())

    assert forwarded.url == "https://httpbin.org/json"


def test_the_lan_subnets_come_from_the_settings_root(settings):
    (settings / "settings.json").write_text(json.dumps({"lan_subnets": ["198.51.100.0/24"]}))
    inside = lab_flow("/https://httpbin.org/json", peer=("198.51.100.7", 4000))
    old_lan = lab_flow("/https://httpbin.org/json")

    assert run_chain(inside, origin_json()) is not None
    assert_refused(old_lan, run_chain(old_lan, origin_json()), "client-ip")


def test_the_lan_subnet_is_set_in_config():
    inside = lab_flow("/https://httpbin.org/json", peer=("10.1.2.3", 4000))
    old_lan = lab_flow("/https://httpbin.org/json")

    assert run_chain(inside, origin_json(), lab_lan_subnets=["10.0.0.0/8"]) is not None
    assert_refused(old_lan, run_chain(old_lan, origin_json(), lab_lan_subnets=["10.0.0.0/8"]), "client-ip")


def test_an_origin_host_not_on_the_allowlist_is_refused():
    flow = lab_flow("/https://evil.example/json")

    forwarded = run_chain(flow, origin_json())

    assert_refused(flow, forwarded, "origin-host")


@pytest.mark.parametrize("host", ["stream.mux.com", "a.b.mux.com", "STREAM.MUX.COM", "stream.mux.com."])
def test_a_leading_dot_allowlist_entry_allows_subdomains(host):
    flow = lab_flow(f"/https://{host}/x.m3u8")

    assert run_chain(flow, origin_json()) is not None


@pytest.mark.parametrize("host", ["mux.com", "evilmux.com", "httpbin.org.evil.example", "evilhttpbin.org"])
def test_lookalike_hosts_are_not_allowed(host):
    flow = lab_flow(f"/https://{host}/json")

    assert_refused(flow, run_chain(flow, origin_json()), "origin-host")


def test_the_origin_allowlist_is_set_in_config():
    added = lab_flow("/https://new-origin.example/json")
    removed = lab_flow("/https://httpbin.org/json")

    assert run_chain(added, origin_json(), lab_origin_allowlist=["new-origin.example"]) is not None
    assert_refused(
        removed, run_chain(removed, origin_json(), lab_origin_allowlist=["new-origin.example"]), "origin-host"
    )


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1", "172.16.5.5", "192.0.2.10",  # private
        "127.0.0.1", "::1",  # loopback
        "169.254.169.254", "fe80::1",  # link-local
        "fd12:3456::1",  # IPv6 unique-local
        "0.0.0.0", "::ffff:127.0.0.1",
    ],
)
def test_an_origin_that_resolves_to_a_non_public_address_is_refused(dns, address):
    dns["httpbin.org"] = [address]
    flow = lab_flow("/https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json())

    assert_refused(flow, forwarded, "origin-address")


def test_an_origin_is_refused_if_any_of_its_addresses_is_not_public(dns):
    dns["httpbin.org"] = ["93.184.215.14", "10.0.0.1"]
    flow = lab_flow("/https://httpbin.org/json")

    assert_refused(flow, run_chain(flow, origin_json()), "origin-address")


def test_an_origin_with_public_addresses_is_forwarded(dns):
    dns["httpbin.org"] = ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"]
    flow = lab_flow("/https://httpbin.org/json")

    forwarded = run_chain(flow, origin_json())

    assert forwarded.url == "https://httpbin.org/json"
    assert flow.response.status_code == 200


def test_a_forwarded_request_asks_the_origin_to_close_its_pinned_connection(dns):
    """A pinned Origin connection is never reused, and mitmproxy keeps at most 5 open
    per address per client connection. cloudflared sends many requests over one
    connection to the tunnel listener, so the 6th to the same Origin waited forever
    unless each pinned connection closes after its response."""
    dns["storage.googleapis.com"] = ["142.251.209.123"]
    flow = lab_flow("/https://storage.googleapis.com/wvmedia/cenc/h264/tears/tears_sd.mpd")
    flow.request.headers["connection"] = "keep-alive"

    forwarded = run_chain(flow, origin_json())

    assert forwarded.headers.get("connection") == "close"


def test_an_unresolvable_origin_is_left_to_fail_as_an_origin_failure_not_a_guard_block(dns):
    dns["httpbin.org"] = []
    flow = lab_flow("/https://httpbin.org/json")

    assert run_chain(flow, origin_json()) is not None
    assert not flow.marked


def test_the_lab_dials_the_address_the_guard_validated_not_a_later_dns_answer(dns):
    """DNS rebinding: the Origin's name answers public for the check, private for the connect."""
    dns["httpbin.org"] = ["93.184.215.14"]
    flow = lab_flow("/https://httpbin.org/json")
    with Lab() as lab:
        assert lab.run(flow, origin_json()) is not None
        dns["httpbin.org"] = ["127.0.0.1"]

        dialled = lab.connect(flow)

    assert dialled is None or ipaddress.ip_address(dialled[0]).is_global


def test_the_lab_dials_the_origins_public_address_and_keeps_its_name_for_tls(dns):
    dns["httpbin.org"] = ["2606:2800:21f:cb07:6820:80da:af6b:8b2c", "93.184.215.14"]
    flow = lab_flow("/https://httpbin.org/json")
    with Lab() as lab:
        lab.run(flow, origin_json())

        dialled = lab.connect(flow)

    assert dialled == ("93.184.215.14", 443)  # IPv4 first: the lab Mac may have no IPv6 route
    assert lab.last_server.sni == "httpbin.org"


def test_an_origin_that_now_resolves_to_a_private_address_is_never_dialled(dns):
    flow = lab_flow("/https://httpbin.org/json")
    with Lab() as lab:
        lab.run(flow, origin_json())
        dns["httpbin.org"] = ["93.184.215.14", "10.0.0.1"]

        assert lab.connect(flow) is None

    assert "origin-address" in lab.last_server.error
