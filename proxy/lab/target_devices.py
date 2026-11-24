"""The Target Device: which device sent a flow, decided once per flow, and how mitmweb shows it.

A Target Device has a key, which tells devices apart (the throttle shares a rule's
bandwidth per key), and a name from the user's devices registry
(<settings root>/devices.json), None when nothing names it:
- A Physical Device is its client IP, named by `ip` in the registry. It opens a
  connection per parallel request, each from its own port. So is a Proxied Device
  (`"kind": "proxied"`, or `"mobile"` as 0.2.0 wrote it, beside its `ip`), whose flows come
  through Proxy Routing.
- An iOS Simulator or Android Emulator on this Mac reaches the Proxy Routing listener from
  loopback, named "This Mac".
- Every Cloud Device reaches the lab through cloudflared, so all share its peer. One is
  the device slug in its Proxy Base, https://<tunnel-host>/<secret>/<slug> (scripts/launch
  adds it), named by `slug` in the registry; else its tunnel client IP (Cloud Devices
  without a slug behind one RCE egress IP are one device here). Without a known slug, a
  tunnel request from an RCE egress IP is named "Cloud Device".
Tunnel headers count only on the tunnel listener (lab.clients): a LAN client sending
them is its LAN IP.

mitmweb shows the name in the flow's comment (filter `~comment "Living Room"`), then the
Scenario rules that acted on the flow (annotate); `roxy flows` reads target_device.
"""

from typing import NamedTuple

from lab.clients import from_rce_egress_ip, from_this_mac, ip_address, through_tunnel, tunnel_client_ip
from lab.config import settings_root
from lab.prefixed_url import client_proxy_base, device_slug, double_prefixed
from lab.settings_root import CLOUD_DEVICE, SettingsRoot

THIS_MAC = "This Mac"  # the name of an iOS Simulator or Android Emulator on this Mac, through Proxy Routing


class TargetDevice(NamedTuple):
    key: str
    name: str | None


def target_device(flow):
    """The TargetDevice that sent the flow; None if the lab has not seen its request."""
    device = flow.metadata.get("lab_target_device")  # plain values: Recordings keep it
    return device and TargetDevice(**device)


def annotate(flow, applied):
    """Show the flow in mitmweb with APPLIED, the Scenario rules that acted on it (passed in:
    lab.scenarios, which owns them, imports this module through the throttle). The comment
    is `<name> | <scenario>/<rule>, ... | double-prefixed`, each part left out when empty (the
    last when the flow did not arrive as a Nested Prefixed URL), and a flow a rule acted on
    is marked unless it has a mark (a refusal keeps its own). Nothing reads the comment
    back; the mark narrows what roxy status fetches (LabSession.scenario_rules)."""
    device = target_device(flow)
    double_prefixed_label = "double-prefixed" if double_prefixed(flow) else None
    flow.comment = " | ".join(filter(None, [device and device.name, ", ".join(applied), double_prefixed_label]))
    if applied:
        flow.marked = flow.marked or ":test_tube:"


class TargetDevices:
    """Decides each flow's Target Device, at a CONNECT and at request headers. Runs after the
    Origin decoder (the slug is in the Proxy Base) and before the guards, which allow a LAN
    client it names, and the Scenarios, which leave the client alone."""

    def __init__(self):
        self.physical_devices = {}  # IP -> name, Proxied Devices included
        self.cloud_devices = {}  # slug -> name

    def load(self, loader):
        devices = SettingsRoot(settings_root()).devices()
        self.physical_devices = {ip_address(d.ip): d.name for d in devices if d.ip}
        self.cloud_devices = {d.slug: d.name for d in devices if d.slug}

    def http_connect(self, flow):
        """A CONNECT on the Proxy Routing listener: the guards judge its client by it too."""
        self.requestheaders(flow)

    def requestheaders(self, flow):
        flow.metadata["lab_target_device"] = self.identify(flow)._asdict()

    def identify(self, flow):
        if not through_tunnel(flow):
            ip = ip_address(flow.client_conn.peername[0])
            return TargetDevice(f"ip {ip}", THIS_MAC if from_this_mac(flow) else self.physical_devices.get(ip))
        client = client_proxy_base(flow)
        unnamed = CLOUD_DEVICE if from_rce_egress_ip(flow) else None  # shown under its kind's name
        if slug := client and device_slug(client.proxy_base):
            return TargetDevice(f"slug {slug}", self.cloud_devices.get(slug, unnamed))
        return TargetDevice(f"tunnel client {tunnel_client_ip(flow)}", unnamed)

