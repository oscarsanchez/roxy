"""The mitmproxy contract: the lab in a real mitmdump, not the Seam A harness.

tests/chain.py stands in for the one mitmproxy internal the lab reaches into: the
client connection's writer, which the `throttle` Scenario action takes over. Here the
lab runs as scripts/run-mitmweb starts it, in a local mitmdump on loopback, and a raw
HTTP/1 client asks it for a Prefixed URL. A mitmproxy upgrade that moves that internal
fails here, while the harness keeps passing. Real time: about 1 s of pacing.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROXY_DIR = Path(__file__).resolve().parents[1]
MITMDUMP = Path(sys.executable).with_name("mitmdump")  # the project's pinned mitmproxy
BODY = b"\x47" * 50_000  # 50 KB: about 1 s at 400 kbps (50 KB a second)
SLOW_MOCK = '''
[[rule]]
name = "mocked segment"
filter = "~u /segment"
map_local = "mocks/segment.ts"

[[rule]]
name = "slow segment"
filter = "~u /segment"
throttle = { kbps = 400 }
'''


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def lab_port(tmp_path):
    """The lab in mitmdump on a free loopback port, with the slow mock Scenario active.

    Its flags are scripts/run-mitmweb's that the lab's behaviour depends on (its other
    flags are mitmweb's UI, its fixed ports and the saved session). The settings root is
    the test's temp one (conftest.py); the client is this Mac, so its LAN subnet is loopback.
    """
    scenarios = tmp_path / "scenarios"
    (scenarios / "mocks").mkdir(parents=True)
    (scenarios / "mocks" / "segment.ts").write_bytes(BODY)
    (scenarios / "slow-mock.toml").write_text(SLOW_MOCK)
    port = free_port()
    log = (tmp_path / "mitmdump.log").open("w+")
    lab = subprocess.Popen(
        [
            MITMDUMP,
            "--mode", f"reverse:http://127.0.0.1:9@127.0.0.1:{port}",
            "--set", "keep_host_header=true",
            "--set", "connection_strategy=lazy",
            "--set", f"confdir={tmp_path / 'mitmproxy'}",  # never the user's CA
            "--set", "lab_lan_subnets=127.0.0.0/8",
            "--set", f"lab_scenarios_dir={scenarios}",
            "--set", "lab_scenario=slow-mock",
            "-s", "entry.py",
        ],
        cwd=PROXY_DIR, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        wait_for_listener(lab, port, log)
        yield port
    finally:
        lab.terminate()
        lab.wait(timeout=5)
        log.close()


def wait_for_listener(lab, port, log, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lab.poll() is not None:
            log.seek(0)
            pytest.fail(f"mitmdump exited before listening:\n{log.read()}")
        try:
            with socket.socket() as s:
                s.connect(("127.0.0.1", port))
                return
        except ConnectionRefusedError:
            time.sleep(0.05)
    pytest.fail(f"mitmdump never listened on {port}")


def test_a_throttled_answer_reaches_a_real_client_paced_and_the_connection_ends_cleanly(lab_port):
    with socket.socket() as client:
        client.settimeout(5)
        client.connect(("127.0.0.1", lab_port))
        started = time.monotonic()
        client.sendall(
            b"GET /https://origin.invalid/video/segment-1.ts HTTP/1.1\r\n"
            b"Host: 127.0.0.1:%d\r\nConnection: close\r\n\r\n" % lab_port
        )
        received, first_byte_at = b"", None
        while chunk := client.recv(65536):  # b"": mitmproxy ended the connection (a reset raises)
            first_byte_at = first_byte_at or time.monotonic() - started
            received += chunk
        ended_at = time.monotonic() - started

    head, _, body = received.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200 ")
    assert body == BODY
    assert first_byte_at < 0.5  # paced, not delayed: it starts at once
    assert 0.9 <= ended_at < 2.5  # and arrives at about 50 KB a second
