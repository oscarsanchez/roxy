"""Device labels: every flow in mitmweb names the Target Device that sent it."""

import json

import pytest
from mitmproxy import flowfilter

from chain import RCE_EGRESS_IP, SECRET, TUNNEL_OPTIONS, lab_flow, origin_json, run_chain, tunnel_flow


@pytest.mark.parametrize(
    "client_ip, device",
    [("192.0.2.54", "Living Room"), ("192.0.2.55", "Bedroom")],
)
def test_a_physical_device_is_named_by_its_client_ip(client_ip, device):
    flow = lab_flow("/https://httpbin.org/json", peer=(client_ip, 51000))

    run_chain(flow, origin_json())

    assert flow.comment == device
    assert flowfilter.match(f'~comment "{device}"', flow)  # mitmweb's flow filter


def test_target_devices_are_named_from_the_devices_registry_in_the_settings_root(settings):
    (settings / "devices.json").write_text(json.dumps({"Den": {"ip": "192.0.2.77"}}))
    flow = lab_flow("/https://httpbin.org/json", peer=("192.0.2.77", 51000))

    run_chain(flow, origin_json())

    assert flow.comment == "Den"


CLOUD_DEVICE_SLUG = "cloud-device"  # settings.example/devices.json: "Cloud Device" has this slug


@pytest.mark.parametrize("client_ip", [RCE_EGRESS_IP, "8.8.8.8"])
def test_a_cloud_device_is_named_by_the_device_slug_in_its_proxy_base(client_ip):
    flow = tunnel_flow(f"/{SECRET}/{CLOUD_DEVICE_SLUG}/https://httpbin.org/json", client_ip=client_ip)

    run_chain(flow, origin_json(), **TUNNEL_OPTIONS)

    assert flow.comment == "Cloud Device"


@pytest.mark.parametrize(
    "path",
    [
        f"/{SECRET}/https://httpbin.org/json",  # no device slug
        f"/{SECRET}/no-such-device/https://httpbin.org/json",
        "/https://httpbin.org/json",  # refused (no secret): mitmweb still shows who sent it
    ],
)
def test_without_a_known_slug_a_tunnel_request_from_an_rce_egress_ip_is_a_cloud_device(path):
    flow = tunnel_flow(path)

    run_chain(flow, origin_json(), **TUNNEL_OPTIONS)

    assert flow.comment == "Cloud Device"


def test_without_a_known_slug_a_tunnel_request_from_any_other_ip_gets_no_label():
    flow = tunnel_flow(f"/{SECRET}/https://httpbin.org/json", client_ip="8.8.8.8")

    run_chain(flow, origin_json(), **TUNNEL_OPTIONS)

    assert flow.comment == ""


def test_an_rce_egress_ip_on_the_lan_listener_is_not_a_cloud_device():
    # Cloud Devices reach the lab only through the tunnel; the peer IP proves nothing.
    flow = lab_flow("/https://httpbin.org/json", peer=(RCE_EGRESS_IP, 51000))

    run_chain(flow, origin_json(), lab_lan_subnets=["0.0.0.0/0"])

    assert flow.comment == ""


def test_a_client_that_is_no_target_device_gets_no_label():
    flow = lab_flow("/https://httpbin.org/json", peer=("192.0.2.10", 51000))  # the Mac's own curl

    run_chain(flow, origin_json())

    assert flow.comment == ""
