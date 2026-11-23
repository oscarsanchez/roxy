"""Guards: keep the lab from being an open relay.

A request is forwarded only if every guard passes; otherwise the lab answers
it with a 403 and the failing guard's reason. Defaults come from
config/guards.json and the user's settings (LAN subnets), and can be changed
live as mitmproxy options. The loaded App Profile's allowlist (lab.app_profile,
empty with none) joins the lab's own on the Public Endpoint.
"""

import asyncio
import hmac
import ipaddress
import socket
from collections.abc import Sequence  # what mitmproxy's --set parser matches list options by

from mitmproxy import ctx
from mitmproxy.exceptions import OptionsError

from lab.clients import from_rce_egress_ip, ip_address, rce_egress_ips, through_proxy_routing, through_tunnel
from lab.config import load_config, load_settings
from lab.prefixed_url import client_proxy_base, secret_segment
from lab.refusal import refuse

CONFIG = load_config("guards")


async def _origin_addresses(host, port):
    """The Origin's addresses, IPv4 first; empty if it does not resolve."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return sorted({ip_address(sockaddr[0]) for *_, sockaddr in infos}, key=lambda ip: ip.version)


def _non_public(addresses):
    """True if any address is not public (private, loopback, link-local,
    unique-local, unspecified...)."""
    return any(not ip.is_global for ip in addresses)


def _host_allowed(host, allowlist):
    """Exact match, or a leading-dot entry (".mux.com") for any subdomain."""
    host = host.lower().rstrip(".")
    return any(
        host.endswith(entry) if entry.startswith(".") else host == entry
        for entry in (e.lower() for e in allowlist)
    )


class Guards:
    def __init__(self, app_profile):
        self.app_profile = app_profile  # its allowlist joins the lab's own on the Public Endpoint
        self.lan_subnets = []

    def load(self, loader):
        loader.add_option(
            "lab_lan_subnets", Sequence[str], load_settings("settings")["lan_subnets"],
            "Client subnets (CIDR) allowed to use the LAN listener.",
        )
        loader.add_option(
            "lab_origin_allowlist", Sequence[str], CONFIG["origin_allowlist"],
            'Origin hosts the Public Endpoint (the tunnel) forwards to. A leading dot (".mux.com") allows any subdomain.',
        )
        loader.add_option(
            "lab_rce_egress_ips", Sequence[str], CONFIG["rce_egress_ips"],
            "Client IPs allowed to use the Public Endpoint (the tunnel): Roku Cloud Emulator's egress IPs.",
        )
        loader.add_option(
            "lab_secret", str, "",
            "Secret path segment required on Public Endpoint (tunnel) requests. Empty refuses them all.",
        )
        loader.add_option(
            "lab_tunnel_port", int, 0,
            "Port of the tunnel listener, the one only cloudflared dials. 0: no tunnel listener.",
        )

    def configure(self, updated):
        if "lab_lan_subnets" in updated:
            try:
                self.lan_subnets = [ipaddress.ip_network(s) for s in ctx.options.lab_lan_subnets]
            except ValueError as e:
                raise OptionsError(f"lab_lan_subnets: {e}") from e
        if "lab_rce_egress_ips" in updated:
            try:
                rce_egress_ips()  # each must be an IP
            except ValueError as e:
                raise OptionsError(f"lab_rce_egress_ips: {e}") from e

    def _client_allowed(self, flow):
        if through_tunnel(flow):
            return from_rce_egress_ip(flow)
        client = ip_address(flow.client_conn.peername[0])
        if through_proxy_routing(flow) and client.is_loopback:
            return True  # an iOS Simulator or Android Emulator on this Mac
        return any(client in subnet for subnet in self.lan_subnets)

    def _origin_allowlist(self):
        """The lab's own Public Endpoint allowlist, then the loaded App Profile's."""
        return [*ctx.options.lab_origin_allowlist, *self.app_profile.origin_allowlist]

    def _secret_given(self, flow):
        secret = ctx.options.lab_secret
        proxy_base, _ = client_proxy_base(flow)
        given = secret_segment(proxy_base)
        return bool(secret) and hmac.compare_digest(given.encode(), secret.encode())

    def http_connect(self, flow):
        """A CONNECT, on the Proxy Routing listener: no tunnel for a client the LAN guard
        refuses, or it could relay raw TCP that no request hook ever sees."""
        if not self._client_allowed(flow):
            refuse(flow, 403, "client-ip")

    async def requestheaders(self, flow):
        if flow.response is not None:  # already answered by the lab
            return
        # Secret first: without it, a scanner learns nothing about the other guards.
        if through_tunnel(flow) and not self._secret_given(flow):
            refuse(flow, 403, "secret-segment")
        elif not self._client_allowed(flow):
            refuse(flow, 403, "client-ip")
        elif through_tunnel(flow) and not _host_allowed(flow.request.host, self._origin_allowlist()):
            # The Public Endpoint only: the LAN relays to any public Origin, as Charles does.
            refuse(flow, 403, "origin-host")
        elif _non_public(await _origin_addresses(flow.request.host, flow.request.port)):
            # Unresolvable passes: the Origin connect fails, an Origin failure, not a guard block.
            refuse(flow, 403, "origin-address")
        elif flow.request.http_version.startswith("HTTP/1"):
            # The pinned connection (server_connect) is never reused, so let it close after
            # its response: mitmproxy keeps at most 5 open per address per client connection,
            # and cloudflared's long-lived connections hit that, stalling the 6th request.
            # HTTP/1 only: HTTP/2 forbids Connection, and strict Origins drop the request.
            flow.request.headers["connection"] = "close"

    async def server_connect(self, data):
        """Dial an address checked here, not whatever DNS answers mitmproxy's own
        lookup: a name that turns private after the request check (DNS rebinding)
        is never dialled. SNI and Host stay the Origin's name. The cost: a pinned
        connection is not reused for the next request to the same Origin, so each
        request asks the Origin to close it (requestheaders)."""
        host, port = data.server.address
        addresses = await _origin_addresses(host, port)
        if _non_public(addresses):
            data.server.error = "lab refused: origin-address"
        elif addresses:
            data.server.address = (str(addresses[0]), port)
