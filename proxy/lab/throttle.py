"""The `throttle` Scenario action: a bandwidth cap on what the client receives.

`throttle = { kbps = N }` sends a matching flow's response to the client at no
more than N kilobits per second, per flow. The response is paced, not delayed:
it starts at once and arrives slowly, as over a slow link.

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
import time

from mitmproxy import ctx

TICK = 0.1  # seconds of bandwidth sent at a time


class Clock:
    now = staticmethod(time.monotonic)
    sleep = staticmethod(asyncio.sleep)


clock = Clock()  # every pause goes through it; tests/chain.py swaps in a test clock


def paced_seconds(flow):
    """How long the throttle took to send the flow's response on to the client once
    mitmproxy had it whole (roxy flows adds it to the duration); 0 if it was not paced."""
    return flow.metadata.get("lab_paced_seconds", 0)


class Throttle:
    def __init__(self, value, scenario_dir):
        kbps = value.get("kbps") if isinstance(value, dict) and set(value) == {"kbps"} else None
        if type(kbps) not in (int, float) or not 0 < kbps < math.inf:
            raise ValueError(f"throttle must be {{ kbps = N }} with N a positive number, got {value!r}")
        self.bytes_per_second = kbps * 1000 / 8

    def response(self, flow):
        if not flow.request.http_version.startswith("HTTP/1"):
            logging.warning(
                f"{flow.request.url} not throttled: its client speaks {flow.request.http_version}, "
                "and throttle paces HTTP/1 connections only"
            )
            return
        writer = client_writer(flow)
        if writer is not None:
            PacedWriter.take_over(writer, self.bytes_per_second, flow)


def client_writer(flow):
    """mitmproxy's writer for the flow's client connection; None if the client is gone
    (or never was, as for a flow replayed from mitmweb)."""
    handler = ctx.master.addons.get("proxyserver").connections.get(flow.client_conn.id)
    transport = handler and handler.transports.get(flow.client_conn)
    return transport and transport.writer


class PacedWriter:
    """Holds a client writer's writes and sends them on at a fixed rate. Closing the
    connection waits for the queue, so the client still gets the whole response."""

    sending = set()  # running pacers, kept referenced until they finish

    @classmethod
    def take_over(cls, writer, bytes_per_second, flow):
        pacer = getattr(writer, "pacer", None)
        if pacer is None:
            writer.pacer = cls(writer, bytes_per_second, flow)
        else:  # two throttle rules matched: the lower cap wins
            pacer.bytes_per_second = min(pacer.bytes_per_second, bytes_per_second)

    def __init__(self, writer, bytes_per_second, flow):
        self.writer = writer
        self.flow = flow  # the flow whose response is paced
        self.bytes_per_second = bytes_per_second
        self.queue = bytearray()
        self.endings = []  # mitmproxy's write_eof and close, held in order until the queue is sent
        self.task = None
        self.send_on, self.close_on, self.write_eof_on = writer.write, writer.close, writer.write_eof
        writer.write, writer.close, writer.write_eof = self.write, self.close, self.write_eof

    def write(self, data):
        self.queue += data
        if self.task is None:
            self.task = asyncio.create_task(self.send())
            PacedWriter.sending.add(self.task)
            self.task.add_done_callback(PacedWriter.sending.discard)

    def close(self):
        self.end(self.close_on)

    def write_eof(self):
        self.end(self.write_eof_on)

    def end(self, ending):
        self.endings.append(ending)
        if self.task is None:
            self.hand_back()

    async def send(self):
        """Pace the queue out. The writer goes back to mitmproxy however this ends: the
        queue sent, the client gone, a failed write, or the lab stopping (cancelled)."""
        started, sent = clock.now(), 0
        try:
            while self.queue:
                chunk_size = max(1, round(self.bytes_per_second * TICK))
                chunk = bytes(self.queue[:chunk_size])
                del self.queue[:chunk_size]
                sent += len(chunk)
                await clock.sleep(started + sent / self.bytes_per_second - clock.now())
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
