"""A mitmweb flow dump for scripts/tests/roxy.sh (roxy flows, Seam C): flows recorded by
the full lab chain, as mitmweb's GET /flows/dump answers with them.
Usage (from proxy/): PYTHONPATH=. uv run python tests/flows_dump.py OUT.mitm

The lab runs the json-503 Scenario, with the settings root in ROXY_CONFIG_DIR and
stubbed DNS (router.example is private, every other host public). Flow i starts at
START + 60 * i and takes 250 ms:
  0. Living Room POSTs 8 bytes to https://httpbin.org/post; the Origin answers 12 bytes.
  1. Bedroom GETs http://router.example/admin; the lab refuses it (origin-address).
  2. Living Room GETs https://httpbin.org/json; the Scenario's rule turns it into a 503.
"""

import socket
import sys

from mitmproxy import http, io
from mitmproxy.test import tutils

from chain import Lab, lab_flow
from conftest import PUBLIC_IP

START = 1763632800  # 2025-11-20T10:00:00Z
BEDROOM = ("192.0.2.55", 51000)


def getaddrinfo(host, port, *args, **kwargs):
    ip = "192.0.2.200" if host == "router.example" else PUBLIC_IP
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


def origin(body):
    return tutils.tresp(headers=http.Headers(content_type="application/json"), content=body)


def main(out):
    socket.getaddrinfo = getaddrinfo
    post = lab_flow("/https://httpbin.org/post")
    post.request.method = "POST"
    post.request.content = b'{"q": 1}'
    flows = [
        (post, origin(b'{"ok": true}')),
        (lab_flow("/http://router.example/admin", peer=BEDROOM), origin(b"")),
        (lab_flow("/https://httpbin.org/json"), origin(b'{"slideshow": {}}')),
    ]
    with Lab(lab_scenario="json-503") as lab, open(out, "wb") as f:
        writer = io.FlowWriter(f)
        for i, (flow, response) in enumerate(flows):
            lab.run(flow, response)
            flow.timestamp_created = flow.request.timestamp_start = START + 60 * i
            flow.response.timestamp_end = flow.request.timestamp_start + 0.25
            writer.add(flow)


if __name__ == "__main__":
    main(sys.argv[1])
