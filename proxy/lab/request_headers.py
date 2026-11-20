"""Request header cleanup: the Origin sees a normal client request.

Host is already the Origin host (the Origin decoder sets the request URL).
Runs after the guards, which are the last to read the tunnel's headers.
"""

from lab.prefixed_url import parse_prefixed_url
from lab.refusal import refused

# Tunnel (Cloudflare, cloudflared) and forwarding headers: removed from every request.
_STRIPPED_PREFIXES = ("cf-", "x-forwarded-")
_STRIPPED = {"cdn-loop", "forwarded", "x-real-ip", "true-client-ip", "via"}


def _stripped(name):
    name = name.lower()
    return name in _STRIPPED or name.startswith(_STRIPPED_PREFIXES)


class RequestHeaderCleanup:
    def requestheaders(self, flow):
        if refused(flow):  # never reaches an Origin; mitmweb keeps showing who sent it
            return
        headers = flow.request.headers
        for name in {name for name in headers if _stripped(name)}:
            del headers[name]
        for name in ("referer", "origin"):
            if parsed := parse_prefixed_url(headers.get(name, "")):
                headers[name] = parsed.origin_url
