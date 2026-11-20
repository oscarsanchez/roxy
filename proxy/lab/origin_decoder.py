"""Origin decoding: point each incoming request at its Origin.

Prefix Routing: the Origin comes from the Prefixed URL path.
CA Routing (phase 2, option lab_ca_routing): a request that is not a Prefixed URL
is an Origin URL the Lab App called directly, sent here by DNS; its Origin comes
from Host, else SNI.
A fallback Origin (the loaded App Profile's fallback_origin): a bare path on a LAN
listener, which names no Origin, is taken as Prefixed with that Origin and the
client's Proxy Base, in the "/;" form, when the profile's path regex matches it.
"""

from mitmproxy import ctx

from lab.clients import client_scheme, through_tunnel
from lab.prefixed_url import PrefixedUrl, parse_prefixed_url, remember_client
from lab.refusal import refuse


class OriginDecoder:
    def __init__(self, app_profile):
        self.app_profile = app_profile  # its fallback Origin answers a bare path on the LAN

    def load(self, loader):
        loader.add_option(
            "lab_ca_routing", bool, False,
            "CA Routing: take the Origin of a request that is not a Prefixed URL from Host/SNI.",
        )

    def requestheaders(self, flow):
        # Needs keep_host_header=true, or Host is already the dummy reverse target.
        proxy_base = f"{client_scheme(flow)}://{flow.request.host_header}"
        parsed = parse_prefixed_url(f"{proxy_base}{flow.request.path}")
        if parsed is not None:
            self._to_origin(flow, parsed)
        elif (host := self._ca_routed_host(flow)) is not None:
            flow.request.url = f"{client_scheme(flow)}://{host}{flow.request.path}"
            flow.request.host_header = host  # an SNI-only request still tells the Origin its Host
        elif through_tunnel(flow):
            # The Public Endpoint serves only Prefixed URLs behind the secret: a scanner
            # gets the same answer as for a wrong secret, and learns nothing more.
            refuse(flow, 403, "secret-segment")
        elif (origin_url := self._fallback_origin_url(flow)) is not None:
            self._to_origin(flow, PrefixedUrl(proxy_base, "/;", origin_url))
        else:
            refuse(flow, 400, "not-prefixed")

    @staticmethod
    def _to_origin(flow, parsed):
        remember_client(flow, parsed)  # rewriters use the client's own Proxy Base and separator
        flow.request.url = parsed.origin_url

    def _fallback_origin_url(self, flow):
        """The Origin URL the loaded App Profile's fallback Origin gives this bare path, or None."""
        fallback = self.app_profile.fallback_origin
        return fallback and fallback.origin_url(flow.request.path)

    @staticmethod
    def _ca_routed_host(flow):
        """The Origin host of a CA-routed request: Host, else SNI. None when CA Routing
        is off, or for the Public Endpoint (CA Routing is for Physical Devices only)."""
        if not ctx.options.lab_ca_routing or through_tunnel(flow):
            return None
        return flow.request.host_header or flow.client_conn.sni
