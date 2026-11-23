"""Seam A harness: run a flow through the full lab addon chain, as mitmweb does.

Tests assert only on what reaches the Origin (the forwarded request) and what
reaches the client (flow.response, and when its bytes arrived: Lab.received),
or on what the lab shows: the flow's mitmweb comment and mark, and the flows
summary (flows_summary). No network: Origin responses are fixtures.
"""

import asyncio
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from mitmproxy import hooks as lifecycle
from mitmproxy import connection, http, io
from mitmproxy.addons import save, serverplayback
from mitmproxy.net.http.http1 import assemble_response
from mitmproxy.proxy.layers import http as hooks
from mitmproxy.proxy import server_hooks
from mitmproxy.proxy.mode_specs import ProxyMode
from mitmproxy.test import taddons, tflow, tutils

from lab import addon_chain, clock, throttle
from lab.lab_session import LabSession

LAN_PROXY_BASE_HOST = "192.0.2.10:8080"
LAN_PROXY_BASE = f"http://{LAN_PROXY_BASE_HOST}"
LAN_CLIENT = ("192.0.2.54", 51000)
LAN_LISTENER = ProxyMode.parse("reverse:http://127.0.0.1:9@8080")
FIXTURES = Path(__file__).parent / "fixtures"
# Connection-specific headers, which HTTP/2 forbids (RFC 9113 8.2.2). A strict Origin
# drops a request carrying one: httpbin.org answered the lab's `connection: close` with
# a reset (502) once a Roku spoke HTTP/2 in CA Routing.
HTTP2_FORBIDDEN_HEADERS = ("connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade")

# The Public Endpoint: cloudflared forwards Cloud Device requests to the tunnel listener.
SECRET = "s3cret-segment"
TUNNEL_HOST = "lab-test.trycloudflare.com"
TUNNEL_PORT = 8082
TUNNEL_LISTENER = ProxyMode.parse(f"reverse:http://127.0.0.1:9@127.0.0.1:{TUNNEL_PORT}")
TUNNEL_PEER = ("127.0.0.1", 52000)  # cloudflared on this Mac
RCE_EGRESS_IP = "44.239.29.169"
TUNNEL_OPTIONS = {"lab_secret": SECRET, "lab_tunnel_port": TUNNEL_PORT}  # as start-lab --tunnel sets them

# Proxy Routing: a Mobile Device sets the lab's `regular` mode listener as its HTTP proxy.
PROXY_ROUTING_PORT = 8090
PROXY_ROUTING_LISTENER = ProxyMode.parse(f"regular@{PROXY_ROUTING_PORT}")
PROXY_ROUTING_OPTIONS = {"lab_proxy_routing_port": PROXY_ROUTING_PORT}  # as start-lab sets it


def lab_flow(path, host_header=LAN_PROXY_BASE_HOST, peer=LAN_CLIENT):
    """A request as the `reverse` mode listener sees it at hook time
    (keep_host_header=true, dummy reverse target, raw origin-form path)."""
    request = tutils.treq(
        host="127.0.0.1", port=9, scheme=b"http", authority=b"",
        path=path.encode(), headers=http.Headers(host=host_header), content=b"",
    )
    flow = tflow.tflow(req=request)
    flow.client_conn.peername = peer
    flow.client_conn.proxy_mode = LAN_LISTENER
    return flow


def tunnel_flow(path, client_ip=RCE_EGRESS_IP, peer=TUNNEL_PEER, listener=TUNNEL_LISTENER):
    """A request as cloudflared forwards it to the tunnel listener (headers per Cloudflare's docs)."""
    flow = lab_flow(path, host_header=TUNNEL_HOST, peer=peer)
    flow.client_conn.proxy_mode = listener
    flow.request.headers.update(
        {
            "CF-Connecting-IP": client_ip,
            "X-Forwarded-For": client_ip,
            "X-Forwarded-Proto": "https",
            "CF-Ray": "230b030023ae2822-SJC",
            "CF-Visitor": '{"scheme":"https"}',
            "CDN-Loop": "cloudflare",
            "CF-IPCountry": "US",
            "Cf-Warp-Tag-Id": "0b6f6c2e-1111-2222-3333-444455556666",
        }
    )
    return flow


def proxy_routing_flow(url, peer=LAN_CLIENT):
    """A request as the Proxy Routing listener (`regular` mode) sees it at hook time: a Mobile
    Device that set the lab as its HTTP proxy, asking for an Origin URL (over HTTPS, inside
    the CONNECT tunnel mitmproxy terminates)."""
    request = http.Request.make("GET", url, headers={"host": urlsplit(url).netloc})
    flow = tflow.tflow(req=request)
    flow.client_conn.peername = peer
    flow.client_conn.proxy_mode = PROXY_ROUTING_LISTENER
    flow.client_conn.tls = request.scheme == "https"
    return flow


def proxy_routing_connect(authority, peer=LAN_CLIENT):
    """A Mobile Device's CONNECT to the Proxy Routing listener, opening a tunnel to AUTHORITY
    (host:port), as the http_connect hook sees it. Run it with Lab.http_connect."""
    host, port = authority.rsplit(":", 1)
    request = tutils.treq(
        method=b"CONNECT", scheme=b"", host=host, port=int(port), authority=authority.encode(),
        path=b"", headers=http.Headers(), content=b"",
    )
    flow = tflow.tflow(req=request)
    flow.client_conn.peername = peer
    flow.client_conn.proxy_mode = PROXY_ROUTING_LISTENER
    return flow


def fixture_response(name, content_type, status=200):
    return tutils.tresp(
        status_code=status,
        headers=http.Headers(content_type=content_type),
        content=(FIXTURES / name).read_bytes(),
    )


def origin_json():
    return fixture_response("httpbin-json.json", "application/json")


def assert_refused(flow, forwarded, reason, status=403):
    """The lab answered the client itself, with `reason`, and the Origin never saw the request."""
    assert forwarded is None
    assert flow.response.status_code == status
    assert flow.response.headers["X-Lab-Blocked"] == reason
    assert flow.marked  # visible in mitmweb


def flows_summary(*flows):
    """FLOWS as `roxy flows --json` sums them up (LabSession.flows), from mitmweb's dump of them."""
    dump = BytesIO()
    writer = io.FlowWriter(dump)
    for flow in flows:
        writer.add(flow)

    class Mitmweb:
        def get(self, path):
            return 200, dump.getvalue()

    return LabSession(Mitmweb()).flows()


def run_chain(flow, origin_response, **options):
    """Run one flow through a freshly started lab. See Lab.run.

    `options` overrides lab options (as `--set` or the mitmweb Options UI would).
    """
    with Lab(**options) as lab:
        return lab.run(flow, origin_response)


class TestClock:
    """The lab's clock in tests (lab/clock.py): sleeping moves time on at once, so latency
    and pacing never really wait, and share one timeline."""

    def __init__(self):
        self.time = 0.0

    def now(self):
        return self.time

    async def sleep(self, seconds):
        self.time += max(seconds, 0)
        await asyncio.sleep(0)


class ClientWriter:
    """The client's end of a connection, as mitmproxy writes to it (an asyncio.StreamWriter):
    records how many bytes reached the client, and when, and how the connection ended.
    A client that hangs up makes the writer closing, as asyncio's does once the peer is gone."""

    def __init__(self, clock):
        self.clock = clock
        self.hangs_up_at = None  # clock time the client hangs up at; None: never
        self.writes = []  # (time, byte count)
        self.ends = []  # ("write_eof" or "close", time)
        self.closed = asyncio.Event()

    def write(self, data):
        self.writes.append((self.clock.now(), len(data)))

    def write_eof(self):
        self.ends.append(("write_eof", self.clock.now()))

    def close(self):
        self.ends.append(("close", self.clock.now()))
        self.closed.set()

    def is_closing(self):
        hung_up = self.hangs_up_at is not None and self.clock.now() >= self.hangs_up_at
        return self.closed.is_set() or hung_up


class Lab:
    """The full lab addon chain, kept running across flows like mitmweb,
    so options can change between flows (as mitmweb's options PUT does).

    mitmweb's server replay and save-to-file built-ins run after it, as in
    mitmweb (both idle unless their options are set). Time is a TestClock.

    The lab reaches past its hooks for two things, and a running flow gets the test's:
    the clock, and its client connection's writer (throttle.client_writer, the one
    mitmproxy internal the lab uses, which tests/test_mitmproxy_contract.py checks)."""

    def __init__(self, **options):
        self.clock = TestClock()
        self._clients = {}  # client connection id -> its ClientWriter, while `run` sends to it
        self._sent = {}  # flow id -> (when its response started, its ClientWriter)
        self._reached_origin = {}  # flow id -> seconds from run to the Origin getting the request
        # owns its own event loop
        self._context = taddons.context(
            *addon_chain(), serverplayback.ServerPlayback(), save.Save()
        )
        manager = self._context.master.addons
        for addon in manager.chain:  # as mitmweb's script loader does after load
            manager.invoke_addon_sync(addon, lifecycle.ConfigureHook(self._context.options.keys()))
        self.set_options(**options)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # As mitmweb does on shutdown: closes the Recording, and unhooks the
        # master's log handler, which would outlive this Lab's event loop.
        self._context.master.event_loop.run_until_complete(self._context.master.done())
        self._context.__exit__(*exc)

    def set_options(self, **options):
        """Raises OptionsError for a rejected value, as mitmweb answers 400."""
        if options:
            self._context.options.update(**options)

    def set_from_command_line(self, *specs):
        """Set options from "name=value" strings, parsed as mitmweb parses `--set`
        (scripts/run-mitmweb); a list option takes one value per spec."""
        self._context.options.set(*specs)

    def run(self, flow, origin_response, client_hangs_up_at=None, lab_stops_at=None):
        """Fire request then response hooks across the whole chain.

        Returns the request as forwarded to the Origin, or None if the lab
        answered the client itself (or killed the flow). flow.response is what
        the client receives.

        `client_hangs_up_at`: seconds after the response starts at which the client
        hangs up. `lab_stops_at`: seconds after the response starts at which mitmweb
        stops, cancelling the tasks still sending it, as asyncio does on the way out.
        """
        return self._run_in_lab(self._run(flow, origin_response, client_hangs_up_at, lab_stops_at))

    def run_together(self, *exchanges):
        """Run several (flow, origin_response) exchanges at once, as `run` does one: concurrent
        requests, each on its own client connection, whose responses all start at the same
        moment (an Origin lookup really waits, so the hooks may finish in any order).
        Returns each forwarded request, in order."""
        return self._run_in_lab(self._run_all(exchanges))

    async def _run_all(self, exchanges):
        clients = {flow.client_conn.id: ClientWriter(self.clock) for flow, _ in exchanges}
        self._clients.update(clients)
        try:
            forwarded = await asyncio.gather(*(self._exchange(flow, response) for flow, response in exchanges))
            answered = [flow for flow, _ in exchanges if flow.response is not None and not flow.error]
            await asyncio.gather(*(self._send(flow, clients[flow.client_conn.id], None) for flow in answered))
            return forwarded
        finally:
            for client_id in clients:
                del self._clients[client_id]

    def _run_in_lab(self, run):
        """Run the coroutine `run` on the lab's event loop, with the test's clock and client writers."""
        real = clock.current, throttle.client_writer
        clock.current, throttle.client_writer = self.clock, self._client_writer
        try:
            return self._context.master.event_loop.run_until_complete(run)
        finally:
            clock.current, throttle.client_writer = real

    def received(self, flow):
        """What reached the client of a flow `run` answered: (seconds since its response
        started, byte count) for each write, the response head included."""
        started, client = self._sent[flow.id]
        return [(when - started, size) for when, size in client.writes]

    def reached_origin_after(self, flow):
        """Seconds on the lab's clock between `run` starting a flow and the Origin getting
        its request (a forwarded flow only)."""
        return self._reached_origin[flow.id]

    def ended(self, flow):
        """How mitmproxy's end of the connection reached the client of a flow `run`
        answered: ("write_eof" or "close", seconds since its response started), in order."""
        started, client = self._sent[flow.id]
        return [(how, when - started) for how, when in client.ends]

    def http_connect(self, flow):
        """mitmproxy runs the http_connect hooks for a client's CONNECT `flow` (a `regular`
        mode listener). True if it then opens the tunnel; False if the lab answered the
        client itself (flow.response)."""
        self._context.master.event_loop.run_until_complete(self._hook(hooks.HttpConnectHook(flow)))
        return flow.response is None

    def connect(self, flow):
        """mitmproxy opens the server connection for a forwarded `flow`, running the
        server_connect hooks as it does before dialling. Returns the address it dials,
        or None if the connection was killed before connect."""
        server = connection.Server(address=(flow.request.host, flow.request.port))
        if flow.request.scheme == "https":
            server.sni = flow.request.host
        data = server_hooks.ServerConnectionHookData(server=server, client=flow.client_conn)
        self._context.master.event_loop.run_until_complete(self._hook(server_hooks.ServerConnectHook(data)))
        self.last_server = server
        return None if server.error else server.address

    def _client_writer(self, flow):
        return self._clients.get(flow.client_conn.id)

    async def _hook(self, hook):
        manager = self._context.master.addons
        for addon in manager.chain:
            await manager.invoke_addon(addon, hook)

    async def _run(self, flow, origin_response, client_hangs_up_at, lab_stops_at):
        client = ClientWriter(self.clock)
        self._clients[flow.client_conn.id] = client
        try:
            forwarded = await self._exchange(flow, origin_response)
            if flow.response is not None and not flow.error:
                if client_hangs_up_at is not None:
                    client.hangs_up_at = self.clock.now() + client_hangs_up_at
                await self._send(flow, client, lab_stops_at)
            return forwarded
        finally:
            del self._clients[flow.client_conn.id]

    async def _send(self, flow, client, lab_stops_at):
        """mitmproxy writes the response to the client, then ends the connection: it
        half-closes it, then closes it (as after a response with Connection: close)."""
        started = self.clock.now()
        self._sent[flow.id] = (started, client)
        already_running = asyncio.all_tasks()
        client.write(assemble_response(flow.response))
        client.write_eof()
        client.close()
        if lab_stops_at is not None:
            while self.clock.now() < started + lab_stops_at and not client.closed.is_set():
                await asyncio.sleep(0)
            for task in asyncio.all_tasks() - already_running - {asyncio.current_task()}:
                task.cancel()
        try:
            await asyncio.wait_for(client.closed.wait(), timeout=2)
        except TimeoutError:
            raise AssertionError("the lab never closed the client connection") from None

    async def _exchange(self, flow, origin_response):
        arrived = self.clock.now()
        manager = self._context.master.addons
        for hook in (hooks.HttpRequestHeadersHook(flow), hooks.HttpRequestHook(flow)):
            for addon in manager.chain:
                await manager.invoke_addon(addon, hook)  # raises, unlike trigger_event
        forwarded = None
        if flow.response is None and not flow.error:
            forwarded = flow.request.copy()
            self._reached_origin[flow.id] = self.clock.now() - arrived
            if forwarded.http_version == "HTTP/2.0":  # checked for every test, whatever it asserts
                sent = [h for h in HTTP2_FORBIDDEN_HEADERS if h in forwarded.headers]
                assert not sent, f"the lab forwarded HTTP/2 with connection-specific headers: {sent}"
            flow.response = origin_response
        if flow.response is not None and not flow.error:
            for hook in (hooks.HttpResponseHeadersHook(flow), hooks.HttpResponseHook(flow)):
                for addon in manager.chain:
                    await manager.invoke_addon(addon, hook)
        return forwarded
