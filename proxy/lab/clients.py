"""Who sent a request: a LAN client directly, or a Cloud Device through the tunnel.

cloudflared dials its own listener, the tunnel listener (option
lab_tunnel_port), which is never reachable from the LAN: bound to loopback on
macOS, unpublished under Compose. A request on it "came through the tunnel"
(the Public Endpoint), whatever its peer IP. Only then are the tunnel's headers
trusted; a LAN client sending them is judged by its real IP.
"""

import ipaddress

from mitmproxy import ctx

from lab.prefixed_url import client_proxy_base, device_slug


def ip_address(text):
    """An IP address, IPv4-mapped IPv6 unmapped, scope id dropped. Raises ValueError."""
    ip = ipaddress.ip_address(text.split("%")[0])
    return getattr(ip, "ipv4_mapped", None) or ip


def through_tunnel(flow):
    port = ctx.options.lab_tunnel_port
    return bool(port) and flow.client_conn.proxy_mode.custom_listen_port == port


def tunnel_client_ip(flow):
    """The Cloud Device's IP from the tunnel's client-IP header, or None if absent or invalid."""
    try:
        return ip_address(flow.request.headers.get("CF-Connecting-IP", ""))
    except ValueError:
        return None


def client_scheme(flow):
    """The scheme the client used: the tunnel's forwarded scheme (https at the
    edge), else the listener's own."""
    if through_tunnel(flow) and (forwarded := flow.request.headers.get("X-Forwarded-Proto")):
        return forwarded
    return "https" if flow.client_conn.tls else "http"


def target_device(flow):
    """Which Target Device sent the flow, to tell devices apart (lab.device_labels names them).

    A Physical Device is its IP: it opens a connection per parallel request, each from
    its own port. Every Cloud Device reaches the lab through cloudflared, so all share
    its peer: one is the device slug in its Proxy Base, else its tunnel client IP
    (Cloud Devices without a slug behind one RCE egress IP are one device here)."""
    if not through_tunnel(flow):
        return ip_address(flow.client_conn.peername[0])
    client = client_proxy_base(flow)
    slug = client and device_slug(client.proxy_base)
    return ("slug", slug) if slug else ("tunnel client", tunnel_client_ip(flow))
