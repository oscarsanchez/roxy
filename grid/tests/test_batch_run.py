"""A batch of grid cells, run end to end against fakes: scripts/deploy and scripts/launch, a
roxy whose lab is this checkout's and has no flows, a Physical Device console on loopback,
and the rce CLI. Every fake logs to one file, so a test reads what ran in what order.
With no flows and no result lines, every cell fails unless cells.toml makes it a known limit."""

import json
import os
import re
import shlex
import signal
import socket
import threading

import pytest

import run_cell
from run_cell import main

FAKE_SCRIPT = """#!/usr/bin/env bash
printf '%q ' "$(basename "$0")" "$@" >> "$EVENTS"; echo >> "$EVENTS"
case "$(basename "$0") $*" in
  launch*" case=${FAKE_LAUNCH_FAILS_ON:-none} "*) exit 3 ;;
  launch*" case=${FAKE_LAUNCH_INTERRUPTS_ON:-none} "*) kill -INT "$PPID"; sleep 1 ;;
esac
[ "$(basename "$0")" = launch ] || exit 0
n=$(( $(cat "$EVENTS.runs" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$EVENTS.runs"; echo "run=$n"
"""
FAKE_RCE = """#!/usr/bin/env bash
printf '%q ' rce "$@" >> "$EVENTS"; echo >> "$EVENTS"
case "$1 $2" in
  "device status") echo "{\\"status\\": \\"$(cat "$EVENTS.rce" 2>/dev/null || echo "$FAKE_STATUS")\\"}" ;;
  "device start") echo running > "$EVENTS.rce" ;;
  "device stop") echo shutdown > "$EVENTS.rce" ;;
  "console "*) exec sleep 30 ;;
esac
"""


@pytest.fixture
def events(settings, tmp_path, monkeypatch):
    """Install the fakes and point the grid at them; return a reader of the commands run.
    The cells time out at once (run_timeout_s and settle_s 0)."""
    log = tmp_path / "events"
    log.touch()
    monkeypatch.setenv("EVENTS", str(log))
    monkeypatch.setenv("FAKE_STATUS", "shutdown")

    grid = tmp_path / "grid"
    grid.mkdir()
    cells = (run_cell.GRID / "cells.toml").read_text()
    cells = re.sub(r"(?m)^(run_timeout_s|settle_s) = \d+", r"\1 = 0", cells)
    (grid / "cells.toml").write_text(cells)
    monkeypatch.setattr(run_cell, "GRID", grid)

    scripts, bin_dir = tmp_path / "scripts", tmp_path / "bin"
    scripts.mkdir()
    bin_dir.mkdir()
    (scripts / "lib.sh").symlink_to(run_cell.SCRIPTS / "lib.sh")
    for fake in ("deploy", "launch"):
        (scripts / fake).write_text(FAKE_SCRIPT)
    (bin_dir / "rce").write_text(FAKE_RCE)
    state = {"app": None, "scenarios": [], "ca_routing": False, "scenarios_dir": str(tmp_path / "proxy" / "scenarios")}
    roxy = f"#!/usr/bin/env bash\n[ \"$1\" = status ] && echo '{json.dumps(state)}' || echo '[]'\n"
    (bin_dir / "roxy").write_text(roxy)
    for fake in (scripts / "deploy", scripts / "launch", bin_dir / "rce", bin_dir / "roxy"):
        fake.chmod(0o755)
    monkeypatch.setattr(run_cell, "SCRIPTS", scripts)
    monkeypatch.setattr(run_cell, "REPO", tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    # The Physical Devices' console: a loopback port that takes the connection and stays quiet.
    server = socket.create_server(("127.0.0.1", 0))
    threading.Thread(target=hold_connections, args=(server,), daemon=True).start()
    monkeypatch.setattr(run_cell, "CONSOLE_PORT", server.getsockname()[1])
    devices = {"Living Room": {"ip": "127.0.0.1"}, "Travel Stick": {"ip": "127.0.0.1"},
               "Cloud Device": {"rce_device_name": "player", "slug": "cloud-device"}}
    (settings / "devices.json").write_text(json.dumps(devices))

    yield lambda: [shlex.split(line) for line in log.read_text().splitlines()]
    server.close()


def hold_connections(server: socket.socket) -> None:
    held = []
    try:
        while True:
            held.append(server.accept())
    except OSError:  # the server closed: the test is over
        pass


def test_a_batch_deploys_each_flavour_once_before_its_cells(events):
    assert main(["classic,rsg", "physical", "json,hls", "--proxy-base", "http://192.0.2.10:8080"]) == 1
    steps = [(e[0], e[-1].rsplit("/", 1)[-1] if e[0] == "deploy" else e[-2]) for e in events()]
    assert steps == [
        ("deploy", "classic"),
        ("launch", "case=json_get"), ("launch", "case=json_get"),
        ("launch", "case=hls"), ("launch", "case=hls"),
        ("deploy", "rsg"),
        ("launch", "case=json_get"), ("launch", "case=json_get"),
        ("launch", "case=hls"), ("launch", "case=hls"),
    ]


def test_a_failing_cell_does_not_stop_the_rest_and_the_batch_ends_with_a_table(events, monkeypatch, capfd):
    monkeypatch.setenv("FAKE_LAUNCH_FAILS_ON", "json_get")
    assert main(["classic", "physical", "json,hls", "--proxy-base", "http://192.0.2.10:8080"]) == 1
    assert [e[-2] for e in events() if e[0] == "launch"] == ["case=json_get", "case=hls", "case=hls"]
    out = capfd.readouterr().out
    assert out[out.index("| flavour | Target Device |"):].splitlines() == [
        "| flavour | Target Device | traffic class | outcome | reason |",
        "| --- | --- | --- | --- | --- |",
        "| classic | Physical Device | json | fail | scripts/launch failed (exit 3, see above) |",
        "| classic | Physical Device | hls | fail | without a scenario: no result line before the timeout; "
        "with hls-404: no result line before the timeout |",
        "0 pass, 0 known-limit, 2 fail",
    ]


def test_a_batch_of_known_limits_exits_0(events, monkeypatch, capfd):
    """Without result lines every cell fails; rsg's image and raf cells in CA Routing are known limits."""
    roxy = run_cell.REPO / "bin" / "roxy"
    roxy.write_text(roxy.read_text().replace('"ca_routing": false', '"ca_routing": true'))
    assert main(["rsg", "physical", "image,raf", "--ca-routing"]) == 0
    assert capfd.readouterr().out.endswith("0 pass, 2 known-limit, 0 fail\n")
    assert [e for e in events() if e[0] == "deploy"] == [
        ["deploy", "--ca-routing", "Travel Stick", str(run_cell.REPO / "apps" / "rsg")]
    ]


def test_one_cell_prints_its_lines_and_row_as_before_with_no_table(events, capfd):
    assert main(["classic", "physical", "json", "--proxy-base", "http://192.0.2.10:8080"]) == 1
    assert capfd.readouterr().out.splitlines() == [
        "cell: classic x Physical Device x json (device Living Room, case json_get, scenario json-503, "
        "Proxy Base http://192.0.2.10:8080, separator /)",
        "  with json-503: no result line",
        "    0 flows from the Target Device: none",
        "    console: out/grid/classic-physical-json-1.console.log (flows: .flows.json beside it)",
        "  without a scenario: no result line",
        "    0 flows from the Target Device: none",
        "    console: out/grid/classic-physical-json-2.console.log (flows: .flows.json beside it)",
        "| classic | Physical Device | json | fail | without a scenario: no result line before the timeout; "
        "with json-503: no result line before the timeout |",
    ]


@pytest.fixture
def answers(monkeypatch):
    """Answer yes to the RCE cost question; return the questions asked."""
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "y")
    return asked


CLOUD_BATCH = ["classic,rsg", "cloud", "json,hls", "--proxy-base", "https://203.0.113.5/s3cret"]
STOP = ["rce", "device", "stop", "player", "--wait"]
STATUS = ["rce", "device", "status", "player", "--json"]


def test_a_cloud_batch_asks_once_and_runs_every_cell_in_one_capped_run(events, answers, capfd):
    assert main(CLOUD_BATCH) == 1
    assert len(answers) == 1
    assert ("These 4 cells keep the Cloud Device busy for up to 4.7 min "
            "(start-up 120 s + 2 deploys x 60 s + 8 launches x 5 s), about $0.016") in capfd.readouterr().out
    log = events()
    assert [e for e in log if e[:3] == ["rce", "device", "start"]] == [
        ["rce", "device", "start", "player", "--max-runtime", "580"]  # 280 s projected + the 300 s margin
    ]
    launches = [i for i, e in enumerate(log) if e[0] == "launch"]
    assert len(launches) == 8
    assert log[launches[-1] + 1:] == [STATUS, STOP, STATUS]


def test_a_cloud_batch_launches_with_the_secret_and_prints_it_nowhere(events, answers, settings, capfd):
    (settings / "secrets.env").write_text("LAB_SECRET=s3cret\nMITMWEB_PASSWORD=\n")
    main(CLOUD_BATCH)
    launches = [e for e in events() if e[0] == "launch"]
    assert launches and all(e[e.index("--proxy-base") + 1] == "https://203.0.113.5/s3cret" for e in launches)
    out, err = capfd.readouterr()
    assert "Proxy Base https://203.0.113.5/<secret>, separator /)" in out
    assert "s3cret" not in out + err


def test_a_cloud_batch_leaves_a_run_it_did_not_start_running(events, answers, monkeypatch):
    monkeypatch.setenv("FAKE_STATUS", "running")
    main(CLOUD_BATCH)
    assert [e for e in events() if e[:2] == ["rce", "device"] and e[2] != "resolve"] == [STATUS]


def test_an_interrupt_ends_the_batch_after_stopping_the_run(events, answers, monkeypatch):
    monkeypatch.setenv("FAKE_LAUNCH_INTERRUPTS_ON", "json_get")
    with pytest.raises(KeyboardInterrupt):
        main(CLOUD_BATCH)
    log = events()
    launches = [i for i, e in enumerate(log) if e[0] == "launch"]
    assert len(launches) == 1
    assert log[launches[0] + 1:] == [STATUS, STOP, STATUS]


def test_a_mixed_batch_runs_the_physical_cells_before_the_run(events, answers):
    main(["classic", "physical,cloud", "json", "--proxy-base", "http://192.0.2.10:8080"])
    log = events()
    steps = [e[-3] if e[0] == "launch" else "start"
             for e in log if e[0] == "launch" or e[:3] == ["rce", "device", "start"]]
    assert steps == ["Living Room", "Living Room", "start", "Cloud Device", "Cloud Device"]
    assert log[-2:] == [STOP, STATUS]
