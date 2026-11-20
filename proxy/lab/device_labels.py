"""Device labels: name each flow's Target Device in mitmweb (`flow.comment`).

Shown in the flow list's comment column and filterable with `~comment "Living Room"`.
- A Physical Device is named by its client IP (`ip` in config/devices.json).
- A Cloud Device is named by the device slug in its Proxy Base,
  https://<tunnel-host>/<secret>/<slug> (`slug` in config/devices.json), which
  scripts/launch adds. Without a known slug, a tunnel request from an RCE egress
  IP is labelled "Cloud Device".
"""

from lab.clients import ip_address, through_tunnel, tunnel_client_ip
from lab.config import load_config
from lab.prefixed_url import device_slug

DEVICES = load_config("devices")
PHYSICAL_DEVICES = {ip_address(d["ip"]): name for name, d in DEVICES.items() if "ip" in d}
CLOUD_DEVICES = {d["slug"]: name for name, d in DEVICES.items() if d.get("slug")}


class DeviceLabels:
    """Runs after the Origin decoder (the slug is in the Proxy Base) and before the
    guards, so refused flows are labelled too."""

    def __init__(self, guards):
        self.guards = guards  # for its parsed RCE egress IPs

    def requestheaders(self, flow):
        if not through_tunnel(flow):
            flow.comment = PHYSICAL_DEVICES.get(ip_address(flow.client_conn.peername[0]), "")
        elif name := CLOUD_DEVICES.get(device_slug(flow.metadata.get("proxy_base", ""))):
            flow.comment = name
        elif tunnel_client_ip(flow) in self.guards.rce_egress_ips:
            flow.comment = "Cloud Device"
        else:
            flow.comment = ""
