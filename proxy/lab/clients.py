"""Who sent a request: a LAN client directly, a Mobile Device through Proxy Routing,
or a Cloud Device through the tunnel.

cloudflared dials its own listener, the tunnel listener (option
lab_tunnel_port), which is never reachable from the LAN: bound to loopback on
macOS, unpublished under Compose. A request on it "came through the tunnel"
(the Public Endpoint), whatever its peer IP. Only then are the tunnel's headers
trusted; a LAN client sending them is judged by its real IP.

A Mobile Device sets the Proxy Routing listener (option lab_proxy_routing_port), a
`regular` mode LAN listener, as its HTTP proxy: a request on it "came through Proxy
Routing", and carries its Origin URL as is.
"""

import ipaddress

from mitmproxy import ctx


def ip_address(text):
    """An IP address, IPv4-mapped IPv6 unmapped, scope id dropped. Raises ValueError."""
    ip = ipaddress.ip_address(text.split("%")[0])
    return getattr(ip, "ipv4_mapped", None) or ip


def through_tunnel(flow):
    port = ctx.options.lab_tunnel_port
    return bool(port) and flow.client_conn.proxy_mode.custom_listen_port == port


def through_proxy_routing(flow):
    port = ctx.options.lab_proxy_routing_port
    return bool(port) and flow.client_conn.proxy_mode.custom_listen_port == port


def tunnel_client_ip(flow):
    """The Cloud Device's IP from the tunnel's client-IP header, or None if absent or invalid."""
    try:
        return ip_address(flow.request.headers.get("CF-Connecting-IP", ""))
    except ValueError:
        return None


def rce_egress_ips():
    """The client IPs Cloud Devices reach the tunnel from (option lab_rce_egress_ips).
    Raises ValueError for one that is no IP."""
    return {ip_address(ip) for ip in ctx.options.lab_rce_egress_ips}


def from_rce_egress_ip(flow):
    """True if the flow came through the tunnel from an RCE egress IP: a Cloud Device's."""
    return through_tunnel(flow) and tunnel_client_ip(flow) in rce_egress_ips()


def client_scheme(flow):
    """The scheme the client used: the tunnel's forwarded scheme (https at the
    edge), else the listener's own."""
    if through_tunnel(flow) and (forwarded := flow.request.headers.get("X-Forwarded-Proto")):
        return forwarded
    return "https" if flow.client_conn.tls else "http"
