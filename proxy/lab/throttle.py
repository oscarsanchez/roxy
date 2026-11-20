"""The `throttle` Scenario action: a bandwidth cap on what the client receives.

`throttle = { kbps = N }` sends the responses a rule matches to a Target Device at
no more than N kilobits per second together: concurrent responses to one device
share the rule's bucket for that device, each taking the next tick of it in turn
(a player's parallel requests add up to N, not k x N). A response is paced, not
delayed: it starts at once and arrives slowly, as over a slow link.

mitmproxy has no hook while it sends a body, and a `flow.response.stream`
callable runs on the event loop, so it cannot wait without stalling every flow
(and a streamed body would skip the lab's body rewriting). So the action waits
until the response is final, at the `response` hook, then takes over the client
connection's writer: mitmproxy's writes queue there, and a task sends them on
at the paced rate before handing the writer back.

HTTP/1 only. An HTTP/2 (or HTTP/3) connection carries many flows at once, so
taking its writer over would pace every other flow on it too: such a flow is
sent unthrottled, and the event log says so.
"""

import asyncio
import logging
import math

from mitmproxy import ctx

from lab import clock
from lab.clients import target_device

TICK = 0.1  # seconds of bandwidth sent at a time


def paced_seconds(flow):
    """How long the throttle took to send the flow's response on to the client once
    mitmproxy had it whole (roxy flows adds it to the duration); 0 if it was not paced."""
    return flow.metadata.get("lab_paced_seconds", 0)


class Throttle:
    def __init__(self, value, scenario_dir):
        kbps = value.get("kbps") if isinstance(value, dict) and set(value) == {"kbps"} else None
        if type(kbps) not in (int, float) or not 0 < kbps < math.inf:
            raise ValueError(f"throttle must be {{ kbps = N }} with N a positive number, got {value!r}")
        self.buckets = Buckets(kbps * 1000 / 8)

    def response(self, flow):
        if not flow.request.http_version.startswith("HTTP/1"):
            logging.warning(
                f"{flow.request.url} not throttled: its client speaks {flow.request.http_version}, "
                "and throttle paces HTTP/1 connections only"
            )
            return
        writer = client_writer(flow)
        if writer is not None:
            PacedWriter.take_over(writer, self.buckets, target_device(flow), flow)


def client_writer(flow):
    """mitmproxy's writer for the flow's client connection; None if the client is gone
    (or never was, as for a flow replayed from mitmweb).

    The lab's one reach into mitmproxy's internals: tests/chain.py stands in for it,
    and tests/test_mitmproxy_contract.py checks it against a real mitmdump."""
    handler = ctx.master.addons.get("proxyserver").connections.get(flow.client_conn.id)
    transport = handler and handler.transports.get(flow.client_conn)
    return transport and transport.writer


class Buckets:
    """A throttle rule's bandwidth: a bucket of it per key (a Target Device), kept only
    while a response is paced through it."""

    def __init__(self, bytes_per_second):
        self.bytes_per_second = bytes_per_second
        self.by_key = {}  # key -> Bucket

    def join(self, key):
        bucket = self.by_key.get(key)
        if bucket is None:
            bucket = self.by_key[key] = Bucket(self.bytes_per_second)
        bucket.pacers += 1
        return bucket

    def leave(self, key):
        bucket = self.by_key[key]
        bucket.pacers -= 1
        if not bucket.pacers:
            del self.by_key[key]


class Bucket:
    """Bandwidth the responses paced through it share: each reserves the next free stretch
    of it in turn, so k of them get about 1/k each, and one alone gets it all."""

    def __init__(self, bytes_per_second):
        self.bytes_per_second = bytes_per_second
        self.free_at = clock.now()  # reserved until then: in use, it never idles
        self.pacers = 0  # responses paced through it now

    async def wait_to_send(self, size):
        """Reserve the next `size` bytes of the bucket, and wait until they are sent."""
        self.free_at += size / self.bytes_per_second
        await clock.sleep(self.free_at - clock.now())


class PacedWriter:
    """Holds a client writer's writes and sends them on through a bucket. Closing the
    connection waits for the queue, so the client still gets the whole response."""

    sending = set()  # running pacers, kept referenced until they finish

    @classmethod
    def take_over(cls, writer, buckets, key, flow):
        pacer = getattr(writer, "pacer", None)
        if pacer is None:
            writer.pacer = cls(writer, buckets, key, flow)
        elif buckets.bytes_per_second < pacer.buckets.bytes_per_second:  # two throttle rules matched: the lower cap wins
            pacer.buckets, pacer.key = buckets, key

    def __init__(self, writer, buckets, key, flow):
        self.writer = writer
        self.flow = flow  # the flow whose response is paced
        self.buckets, self.key = buckets, key  # the bucket it sends through, from its first write
        self.queue = bytearray()
        self.endings = []  # mitmproxy's write_eof and close, held in order until the queue is sent
        self.task = None
        self.send_on, self.close_on, self.write_eof_on = writer.write, writer.close, writer.write_eof
        writer.write, writer.close, writer.write_eof = self.write, self.close, self.write_eof

    def write(self, data):
        self.queue += data
        if self.task is None:
            bucket = self.buckets.join(self.key)  # now, so its time starts with the response
            self.task = asyncio.create_task(self.send(bucket))
            PacedWriter.sending.add(self.task)
            self.task.add_done_callback(PacedWriter.sending.discard)
            self.task.add_done_callback(lambda _: self.buckets.leave(self.key))

    def close(self):
        self.end(self.close_on)

    def write_eof(self):
        self.end(self.write_eof_on)

    def end(self, ending):
        self.endings.append(ending)
        if self.task is None:
            self.hand_back()

    async def send(self, bucket):
        """Pace the queue out. The writer goes back to mitmproxy however this ends: the
        queue sent, the client gone, a failed write, or the lab stopping (cancelled)."""
        started = clock.now()
        try:
            while self.queue:
                chunk_size = max(1, round(bucket.bytes_per_second * TICK))
                chunk = bytes(self.queue[:chunk_size])
                del self.queue[:chunk_size]
                await bucket.wait_to_send(len(chunk))
                if self.writer.is_closing():  # the client went while the chunk waited
                    break
                self.send_on(chunk)
        finally:
            self.flow.metadata["lab_paced_seconds"] = clock.now() - started
            self.hand_back()

    def hand_back(self):
        del self.writer.write, self.writer.close, self.writer.write_eof, self.writer.pacer
        for ending in self.endings:
            ending()
