"""The Target Device: which device sent each flow, decided once per flow. The throttle shares
on its key; mitmweb's comment and `roxy flows` show its name. One decision gives both."""

import pytest

from chain import RCE_EGRESS_IP, SECRET, TUNNEL_OPTIONS, lab_flow, origin_json, run_chain, target_device, tunnel_flow


def lan_client_with_tunnel_headers():
    """A LAN client sending what cloudflared sends: it is judged by its LAN IP."""
    flow = lab_flow(f"/{SECRET}/cloud-device/https://httpbin.org/json", peer=("192.0.2.54", 51000))
    flow.request.headers.update({"CF-Connecting-IP": RCE_EGRESS_IP, "X-Forwarded-Proto": "https"})
    return flow


TARGET_DEVICES = {
    "a Physical Device, by its IP": (
        lambda: lab_flow("/https://httpbin.org/json", peer=("192.0.2.54", 51000)),
        ("ip 192.0.2.54", "Living Room"),
    ),
    "a Cloud Device, by the named slug in its Proxy Base": (
        lambda: tunnel_flow(f"/{SECRET}/cloud-device/https://httpbin.org/json"),
        ("slug cloud-device", "Cloud Device"),
    ),
    "a Cloud Device with a slug nobody named, by the slug": (
        lambda: tunnel_flow(f"/{SECRET}/no-such-device/https://httpbin.org/json"),
        ("slug no-such-device", "Cloud Device"),
    ),
    "a Cloud Device without a slug, by its RCE egress IP": (
        lambda: tunnel_flow(f"/{SECRET}/https://httpbin.org/json"),
        (f"tunnel client {RCE_EGRESS_IP}", "Cloud Device"),
    ),
    "a tunnel client from another IP, unnamed": (
        lambda: tunnel_flow(f"/{SECRET}/https://httpbin.org/json", client_ip="198.51.100.7"),
        ("tunnel client 198.51.100.7", None),
    ),
    "a LAN client that is no Target Device, unnamed": (
        lambda: lab_flow("/https://httpbin.org/json", peer=("192.0.2.10", 51000)),
        ("ip 192.0.2.10", None),
    ),
    "a LAN client sending tunnel headers, by its LAN IP": (
        lan_client_with_tunnel_headers,
        ("ip 192.0.2.54", "Living Room"),
    ),
}


@pytest.mark.parametrize("make_flow, key_and_name", TARGET_DEVICES.values(), ids=TARGET_DEVICES.keys())
def test_each_flow_has_one_target_device_whose_key_and_name_agree(make_flow, key_and_name):
    flow = make_flow()

    run_chain(flow, origin_json(), **TUNNEL_OPTIONS)

    assert target_device(flow) == key_and_name
