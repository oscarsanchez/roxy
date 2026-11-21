"""The grid runner's Cloud Device side, against a fake rce CLI on PATH: the Run around a
cell, and the console. Asserts on the rce commands run, as the fake logged them."""

import os
import shlex
import signal
import threading
import time

import pytest

from run_cell import cloud_console, cloud_run

FAKE_RCE = """#!/usr/bin/env bash
printf '%q ' "$@" >> "$RCE_LOG"; echo >> "$RCE_LOG"
# A refused start: the device has someone else's Run (it started after our status).
[ "$1 $2" = "${FAKE_RCE_FAIL_ON:-}" ] && { echo running > "$RCE_STATE"; echo "rce: refused" >&2; exit 4; }
case "$1 $2" in
  "device status") echo "{\\"id\\": 351, \\"device_name\\": \\"$3\\", \\"status\\": \\"$(cat "$RCE_STATE" 2>/dev/null || echo "$FAKE_STATUS")\\"}"
    [ -z "${FAKE_STATUS_LINGERS_S:-}" ] || { exec >&-; sleep "$FAKE_STATUS_LINGERS_S"; } ;;
  "device start") sleep "${FAKE_START_S:-0}"; [ -n "${FAKE_START_STOPS_ITSELF:-}" ] || echo running > "$RCE_STATE"
    echo "started $3" >> "$RCE_LOG" ;;
  "device stop") [ -n "${FAKE_STOP_FAILS:-}" ] || echo shutdown > "$RCE_STATE" ;;
  "console $2") printf '%s\\n' "$FAKE_CONSOLE"; [ -z "${FAKE_CONSOLE_ENDS:-}" ] || exit 4; exec sleep 30 ;;
esac
"""


@pytest.fixture
def rce_log(tmp_path, monkeypatch):
    """Put the fake rce first on PATH; return a reader of the commands it ran.
    Its Run starts in FAKE_STATUS; its start and stop change it, as RCE's would. A start
    that finishes also logs `started NAME`, so a test can tell it finished."""
    (tmp_path / "rce").write_text(FAKE_RCE)
    (tmp_path / "rce").chmod(0o755)
    log = tmp_path / "rce.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("RCE_LOG", str(log))
    monkeypatch.setenv("RCE_STATE", str(tmp_path / "rce.state"))
    return lambda: [shlex.split(line) for line in log.read_text().splitlines()]


def test_starts_a_cloud_device_without_a_run_and_stops_it_after_the_cell(rce_log, monkeypatch):
    monkeypatch.setenv("FAKE_STATUS", "shutdown")
    with cloud_run("player", 600):
        assert rce_log()[-1] == ["started", "player"]
    assert rce_log() == [
        ["device", "status", "player", "--json"],
        ["device", "start", "player", "--max-runtime", "600"],
        ["started", "player"],
        ["device", "status", "player", "--json"],
        ["device", "stop", "player", "--wait"],
        ["device", "status", "player", "--json"],
    ]


def test_leaves_a_run_it_did_not_start_running(rce_log, monkeypatch):
    monkeypatch.setenv("FAKE_STATUS", "running")
    with cloud_run("player", 600):
        pass
    assert rce_log() == [["device", "status", "player", "--json"]]


def test_stops_the_run_it_started_when_the_cell_fails(rce_log, monkeypatch):
    monkeypatch.setenv("FAKE_STATUS", "shutdown")
    with pytest.raises(KeyboardInterrupt):
        with cloud_run("player", 600):
            raise KeyboardInterrupt
    assert ["device", "stop", "player", "--wait"] in rce_log()


def test_a_refused_start_ends_the_cell_before_it_runs(rce_log, monkeypatch):
    monkeypatch.setenv("FAKE_STATUS", "shutdown")
    monkeypatch.setenv("FAKE_RCE_FAIL_ON", "device start")
    with pytest.raises(SystemExit, match="rce device start player --max-runtime 600 failed"):
        with cloud_run("player", 600):
            pytest.fail("the cell ran without a Run")
    assert not [command for command in rce_log() if command[:2] == ["device", "stop"]]


def test_an_interrupt_during_the_start_stops_the_run_once_the_start_ends(rce_log, monkeypatch):
    """A Ctrl-C reaches rce too, which stops its own Run; the fake doesn't see it, so its
    start finishes with a Run, as one would when rce had not yet begun guarding it."""
    monkeypatch.setenv("FAKE_STATUS", "shutdown")
    monkeypatch.setenv("FAKE_START_S", "2")
    threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGINT)).start()
    with pytest.raises(KeyboardInterrupt):
        with cloud_run("player", 600):
            pytest.fail("the cell ran after an interrupt")
    log = rce_log()
    assert log.index(["started", "player"]) < log.index(["device", "stop", "player", "--wait"])


def test_an_interrupted_start_that_stopped_its_own_run_stops_nothing(rce_log, monkeypatch):
    """What a Ctrl-C usually does: it reaches rce too, and rce stops the Run it was starting."""
    monkeypatch.setenv("FAKE_STATUS", "shutdown")
    monkeypatch.setenv("FAKE_START_S", "1")
    monkeypatch.setenv("FAKE_START_STOPS_ITSELF", "1")
    threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT)).start()
    with pytest.raises(KeyboardInterrupt):
        with cloud_run("player", 600):
            pytest.fail("the cell ran after an interrupt")
    assert ["started", "player"] in rce_log()
    assert not [command for command in rce_log() if command[:2] == ["device", "stop"]]


def test_an_interrupt_while_rce_ends_waits_for_it_and_raises(rce_log, monkeypatch):
    """The status has printed and closed its output; rce is still exiting when Ctrl-C comes."""
    monkeypatch.setenv("FAKE_STATUS", "running")
    monkeypatch.setenv("FAKE_STATUS_LINGERS_S", "1")
    threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT)).start()
    with pytest.raises(KeyboardInterrupt):
        with cloud_run("player", 600):
            pytest.fail("the cell ran after an interrupt")


def test_a_run_still_going_after_its_stop_fails_the_cell(rce_log, monkeypatch):
    monkeypatch.setenv("FAKE_STATUS", "shutdown")
    monkeypatch.setenv("FAKE_STOP_FAILS", "1")
    with pytest.raises(SystemExit, match="stop it with `rce device stop player`"):
        with cloud_run("player", 600):
            pass


def test_console_collects_what_rce_console_prints(rce_log, monkeypatch):
    monkeypatch.setenv("FAKE_CONSOLE", "LABRESULT json_get run=7 status=200")
    console = cloud_console("player")
    deadline = time.time() + 5
    while "LABRESULT" not in console.text and time.time() < deadline:
        time.sleep(0.05)
    console.close()
    assert console.text == "LABRESULT json_get run=7 status=200\n"
    assert rce_log() == [["console", "player"]]


def test_console_tells_when_rce_console_has_ended(rce_log, monkeypatch):
    """rce console exits when it can't read the console (dev mode off, no Run): the cell
    must stop before it deploys, rather than wait for result lines that cannot come."""
    monkeypatch.setenv("FAKE_CONSOLE", "")
    monkeypatch.setenv("FAKE_CONSOLE_ENDS", "1")
    console = cloud_console("player")
    deadline = time.time() + 5
    while not console.ended and time.time() < deadline:
        time.sleep(0.05)
    assert console.ended
    console.close()
