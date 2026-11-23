"""The Target Device: which device sent each flow, decided once per flow. mitmweb's comment and
`roxy flows` show its name; the throttle shares a cap on its key, so two devices with one name
still get a cap each. One decision gives both."""

import json

import pytest
from mitmproxy import http
from mitmproxy.test import tutils

from chain import (
    PROXY_ROUTING_OPTIONS,
    RCE_EGRESS_IP,
    SECRET,
    TUNNEL_OPTIONS,
    Lab,
    flows_summary,
    lab_flow,
    proxy_routing_flow,
    run_chain,
    tunnel_flow,
)

SEGMENT = "https://test-streams.mux.dev/video/720p/segment-1.ts"
SEGMENT_BYTES = 500_000


def physical(ip="192.0.2.54"):
    return lab_flow(f"/{SEGMENT}", peer=(ip, 51000))


def cloud(slug=None, client_ip=RCE_EGRESS_IP):
    """A request through the tunnel, with SLUG in its Proxy Base (None: no slug)."""
    return tunnel_flow(f"/{SECRET}/{slug + '/' if slug else ''}{SEGMENT}", client_ip=client_ip)


def proxied(ip="192.0.2.60"):
    """A request through Proxy Routing, from a Proxied Device at IP."""
    return proxy_routing_flow(SEGMENT, peer=(ip, 51000))


def lan_client_with_tunnel_headers():
    """A LAN client sending what cloudflared sends: it is judged by its LAN IP."""
    flow = physical()
    flow.request.headers.update({"CF-Connecting-IP": RCE_EGRESS_IP, "X-Forwarded-Proto": "https"})
    return flow


def origin_segment():
    return tutils.tresp(headers=http.Headers(content_type="video/mp2t"), content=b"\x47" * SEGMENT_BYTES)


TARGET_DEVICES = {
    "a Physical Device, by its IP": (physical, "Living Room"),
    "a Cloud Device, by the named slug in its Proxy Base": (lambda: cloud("cloud-device"), "Cloud Device"),
    "a Cloud Device with a slug nobody named, from an RCE egress IP": (lambda: cloud("no-such-device"), "Cloud Device"),
    "a Cloud Device without a slug, by its RCE egress IP": (cloud, "Cloud Device"),
    "a tunnel client from another IP, unnamed": (lambda: cloud(client_ip="198.51.100.7"), None),
    "a LAN client that is no Target Device, unnamed": (lambda: physical("192.0.2.10"), None),
    "a LAN client sending tunnel headers, by its LAN IP": (lan_client_with_tunnel_headers, "Living Room"),
    "a Proxied Device through Proxy Routing, by its IP": (proxied, "Phone"),
}


@pytest.mark.parametrize("make_flow, name", TARGET_DEVICES.values(), ids=TARGET_DEVICES.keys())
def test_mitmweb_and_roxy_flows_name_each_flows_target_device(make_flow, name):
    flow = make_flow()

    run_chain(flow, origin_segment(), **TUNNEL_OPTIONS, **PROXY_ROUTING_OPTIONS)

    assert flow.comment == (name or "")
    assert [summary["device"] for summary in flows_summary(flow)] == [name]


@pytest.mark.parametrize("kind", ["proxied", "mobile"], ids=["kind proxied", "kind mobile, as 0.2.0 wrote it"])
def test_a_proxied_device_is_named_by_its_ip_whichever_kind_registered_it(settings, kind):
    (settings / "devices.json").write_text(json.dumps({"Tablet": {"ip": "192.0.2.61", "kind": kind}}))
    flow = proxied("192.0.2.61")

    run_chain(flow, origin_segment(), **PROXY_ROUTING_OPTIONS)

    assert flow.comment == "Tablet"
    assert [summary["device"] for summary in flows_summary(flow)] == ["Tablet"]


ONE_DEVICE = {
    "a Physical Device on two connections": (physical, physical),
    "a Physical Device and a LAN client sending tunnel headers from its IP": (physical, lan_client_with_tunnel_headers),
    "a Cloud Device's slug on two requests": (lambda: cloud("cloud-device"), lambda: cloud("cloud-device")),
    "Cloud Devices without a slug behind one RCE egress IP": (cloud, cloud),
}
TWO_DEVICES = {
    "a named slug and a slug nobody named, both 'Cloud Device'": (lambda: cloud("cloud-device"), lambda: cloud("no-such-device")),
    "a slug and no slug from one RCE egress IP": (lambda: cloud("cloud-device"), cloud),
    "two LAN clients that are no Target Device, both unnamed": (lambda: physical("192.0.2.10"), lambda: physical("192.0.2.11")),
}
SLOW_SEGMENTS = '''
[[rule]]
name = "slow segments"
filter = "~u /video/"
throttle = { kbps = 400 }
'''


@pytest.mark.parametrize(
    "make_flows, seconds",
    [(flows, 20) for flows in ONE_DEVICE.values()] + [(flows, 10) for flows in TWO_DEVICES.values()],
    ids=[*ONE_DEVICE, *TWO_DEVICES],
)
def test_the_throttle_shares_a_cap_between_the_flows_of_one_target_device_only(scenarios, make_flows, seconds):
    options = scenarios("slow-segments", SLOW_SEGMENTS)
    flows = [make() for make in make_flows]

    with Lab(**options, **TUNNEL_OPTIONS) as lab:
        lab.run_together(*((flow, origin_segment()) for flow in flows))
        received = [lab.received(flow) for flow in flows]

    # 500 KB each at 50 KB a second: 10 s on a cap of its own, 20 s sharing one
    for r in received:
        assert r[-1][0] == pytest.approx(seconds, abs=0.2)
