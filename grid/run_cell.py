"""Fill one grid cell on a Target Device through the running lab (Seam B).

Usage: scripts/grid <flavour> <physical|cloud> <traffic-class> [--proxy-base URL] [--ca-routing]

Deploys the flavour, then launches its case twice with scripts/launch: first with the
cell's Manipulation scenario, then with no scenario (so the lab is left with none
active). The oracles are mitmweb's flows and the Lab App's result line on the console.
Cells are defined in grid/cells.toml; the verdict logic is in verdict.py.
"""

import argparse
import json
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from verdict import CRASH_MARKERS, DEVICE_KINDS, Cell, Run, cell_from_config, device_flows, judge, result_line, row, setup

GRID = Path(__file__).resolve().parent
REPO = GRID.parent
SCRIPTS = REPO / "scripts"
CONSOLE_PORT = 8085  # BrightScript console: print output of every thread, one client at a time
LAUNCH_S = 5  # projected time of one scripts/launch call


def lab(snippet: str) -> str:
    """Run a shell snippet with scripts/lib.sh loaded (one source for settings, secrets,
    devices, LAN IP). Its error, which names what is missing, ends the cell."""
    script = f'set -euo pipefail; . "$1"; {snippet}'
    done = subprocess.run(["bash", "-c", script, "lab", str(SCRIPTS / "lib.sh")], stdout=subprocess.PIPE, text=True)
    if done.returncode:
        sys.exit(done.returncode)
    return done.stdout.strip()


def save_log(text: str, *parts: str) -> Path:
    """Write text to out/<parts...> (gitignored) and return the path, relative to the repo."""
    path = REPO / "out" / Path(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path.relative_to(REPO)


def secret(name: str) -> str:
    return lab(f'load_env; require_env {name}; printf %s "${name}"')


class Console:
    """A Target Device's BrightScript console, collected in the background."""

    def __init__(self, chunks, close):
        self.text = ""
        self.ended = False  # the connection closed: no more output can come
        self._close = close
        threading.Thread(target=self._pump, args=(chunks,), daemon=True).start()

    def _pump(self, chunks):
        try:
            for chunk in chunks:
                self.text += chunk
        except Exception:  # the reader ends when the connection closes, whichever way
            pass
        self.ended = True

    def close(self):
        self._close()


def physical_console(ip: str) -> Console:
    """Port 8085 on the LAN. Unlike `nc` without -d, a socket keeps receiving new output."""
    sock = socket.create_connection((ip, CONSOLE_PORT), timeout=10)
    sock.settimeout(None)

    def chunks():
        while data := sock.recv(65536):
            yield data.decode("utf-8", "replace")

    return Console(chunks(), sock.close)


def rce(*args: str, quiet: bool = False) -> str:
    """Run the rce CLI, which does everything RCE for the lab. Its own
    messages go to the terminal; quiet=True returns its stdout instead of showing it.
    On Ctrl-C or a kill it lets rce finish before raising KeyboardInterrupt: a Ctrl-C
    reaches rce too, and it stops a Run its start was waiting on. (subprocess.run would
    kill it 0.25 s in, cutting that stop short.)"""
    process = subprocess.Popen(["rce", *args], stdout=subprocess.PIPE if quiet else None, text=True)
    try:
        out, _ = process.communicate()
    except KeyboardInterrupt:
        while True:  # its output is no longer wanted; communicate() can't be retried
            try:
                process.wait()
                break
            except KeyboardInterrupt:
                pass
        raise
    if process.returncode:
        sys.exit(f"error: rce {' '.join(args)} failed (exit {process.returncode})")
    return out or ""


def has_run(name: str) -> bool:
    """Whether the Cloud Device NAME has a Run, pending or running: it bills from the start request."""
    return json.loads(rce("device", "status", name, "--json", quiet=True))["status"] != "shutdown"


def stop_run(name: str) -> None:
    """Stop the Cloud Device NAME's Run, if it has one, and confirm that it ended."""
    if not has_run(name):
        return
    rce("device", "stop", name, "--wait")
    if has_run(name):
        sys.exit(f"error: {name} is still running and billing: stop it with `rce device stop {name}`")


@contextmanager
def cloud_run(name: str):
    """A Run of the Cloud Device NAME around a cell. Started here if it has none, and then
    stopped here however the cell ends, so a cell never leaves a Run billing. A Run that was
    already going is someone else's: it is used and left running."""
    if has_run(name):
        yield
        return
    try:
        rce("device", "start", name)  # waits until it takes input; stops the Run itself if that fails
    except KeyboardInterrupt:  # the Run can exist before rce guards it. A refused start isn't
        # caught: rce cleaned up, and a Run it was refused for may be someone else's.
        stop_run(name)
        raise
    try:
        yield
    finally:
        stop_run(name)


def cloud_console(name: str) -> Console:
    """The Cloud Device's console, streamed by `rce console` for the whole cell: one client,
    as on a Physical Device. Not `rce console --until`: the run id that the result line must
    carry is known only once scripts/launch prints it, a new connection replays old lines
    (an earlier run's result line or crash), and the verdict needs the run's whole console."""
    proc = subprocess.Popen(["rce", "console", name], stdout=subprocess.PIPE, text=True, errors="replace")

    def close():
        proc.terminate()
        proc.wait()

    return Console(iter(proc.stdout.readline, ""), close)


class Mitmweb:
    """The running lab's mitmweb API on localhost (started by scripts/start-lab)."""

    def __init__(self):
        self.url = f"http://127.0.0.1:{lab('echo $LAB_WEB_PORT')}"
        self.password = secret("MITMWEB_PASSWORD")

    def get(self, path: str):
        req = urllib.request.Request(f"{self.url}/{path}", headers={"Authorization": f"Bearer {self.password}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as answer:
                return json.load(answer)
        except OSError as e:
            sys.exit(f"error: mitmweb at {self.url} did not answer ({e}). Is scripts/start-lab running?")

    def flows(self) -> list[dict]:
        return self.get("flows.json")

    def option(self, name: str):
        return self.get("options.json").get(name, {}).get("value")

    def confirm_ours(self) -> None:
        """Stop unless the lab answering is this checkout's: its scenarios are the ones
        cells.toml names, and nobody else's lab gets a scenario set or a device launched."""
        ours = str(REPO / "proxy" / "scenarios")
        theirs = self.option("lab_scenarios_dir")
        if theirs != ours:
            sys.exit(f"error: the lab at {self.url} is not this checkout's (its scenarios: {theirs}). "
                     f"Start it from here: {SCRIPTS / 'start-lab'}")

    def confirm_ca_routing(self) -> None:
        """Stop unless the lab is in CA Routing: otherwise it refuses every Origin URL."""
        if not self.option("lab_ca_routing"):
            sys.exit(f"error: the lab is not in CA Routing. Start it with {SCRIPTS / 'start-lab'} --ca-routing")


def confirm_rce_cost(config: dict) -> None:
    """Print the projected Cloud Device time and cost, and ask before any RCE call."""
    per_run = config["run_timeout_s"] + config["settle_s"] + LAUNCH_S
    seconds = config["rce_start_s"] + config["rce_deploy_s"] + 2 * per_run
    usd = seconds / 3600 * config["rce_usd_per_device_hour"]
    print(
        f"This cell keeps the Cloud Device busy for up to {seconds / 60:.1f} min "
        f"(start-up {config['rce_start_s']} s + deploy {config['rce_deploy_s']} s + 2 launches x {per_run} s), "
        f"about ${usd:.3f} at ${config['rce_usd_per_device_hour']:.2f} per device-hour.\n"
        "The grid starts the Cloud Device if it has no Run and stops it after the cell, also when "
        "the cell fails or you press Ctrl-C. A Run that was already going is left running."
    )
    try:
        answer = input("Use RCE now? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        sys.exit("RCE not touched.")


@dataclass
class Session:
    """What both launches of a cell share."""

    device: str
    cell: Cell
    proxy_base: str
    console: Console
    mitmweb: Mitmweb
    config: dict


def launch_once(session: Session, scenario: str) -> Run:
    device, cell, console, config = session.device, session.cell, session.console, session.config
    mark, start = len(console.text), time.time()
    out = subprocess.run(
        [str(SCRIPTS / "launch"), "--scenario", scenario, device, cell.case, session.proxy_base],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout
    run_id = next(line[4:] for line in out.splitlines() if line.startswith("run="))

    deadline = time.time() + config["run_timeout_s"]
    result = None
    while time.time() < deadline:
        text = console.text[mark:]
        result = result_line(text, cell.case, run_id)
        if result or any(m in text for m in CRASH_MARKERS):
            break
        time.sleep(0.5)
    time.sleep(config["settle_s"])
    end = time.time()
    flows = device_flows(session.mitmweb.flows(), device, start, end)
    run = Run(result=result, flows=flows, console=console.text[mark:])
    hosts = sorted({f["request"]["host"] for f in flows})
    # Kept for the verdict's evidence: the console and flows behind each launch.
    name = f"{cell.flavour}-{setup(cell.device_kind, cell.ca_routing)}-{cell.traffic_class}-{run_id}"
    log = save_log(run.console, "grid", f"{name}.console.log")
    save_log(json.dumps(flows, indent=1), "grid", f"{name}.flows.json")
    print(f"  {'with ' + scenario if scenario else 'without a scenario'}: {result or 'no result line'}")
    print(f"    {len(flows)} flows from the Target Device: {', '.join(hosts) or 'none'}")
    print(f"    console: {log} (flows: .flows.json beside it)")
    return run


def main(argv: list[str]) -> int:
    config = tomllib.loads((GRID / "cells.toml").read_text())
    parser = argparse.ArgumentParser(prog="scripts/grid", description="Fill one grid cell.")
    parser.add_argument("flavour", choices=sorted(config["flavours"]))
    parser.add_argument("device_kind", choices=sorted(DEVICE_KINDS))
    parser.add_argument("traffic_class", choices=sorted(config["classes"]))
    parser.add_argument("--proxy-base", help="Proxy Base to launch with (a Cloud Device needs the public one)")
    parser.add_argument("--ca-routing", action="store_true",
                        help="CA Routing on the GL.iNet (Physical Devices only, README, CA Routing)")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # a kill stops the Run as Ctrl-C does

    cloud = args.device_kind == "cloud"
    if cloud and args.ca_routing:
        parser.error("CA Routing is for Physical Devices only")
    if cloud and not args.proxy_base:
        parser.error("a Cloud Device needs --proxy-base: the public Proxy Base printed by scripts/start-lab --tunnel")
    cell = cell_from_config(config, args.flavour, args.device_kind, args.traffic_class, args.ca_routing)
    device = lab(f"grid_device {setup(args.device_kind, args.ca_routing)}")
    proxy_base = (args.proxy_base or lab("lan_proxy_base")).rstrip("/")
    device_ip = None if cloud else lab(f"device_field {shlex.quote(device)} ip")
    if not cloud and not device_ip:
        sys.exit(f"error: {device} has no ip in devices.json (settings root)")
    rce_name = lab(f"rce_device_name {shlex.quote(device)}") if cloud else None  # local, free
    if cloud and not rce_name:
        sys.exit(f"error: {device} has no rce_device_name in devices.json (settings root)")

    routing = "CA Routing build" if cell.ca_routing else f"Proxy Base {proxy_base}"
    print(f"cell: {cell.flavour} x {DEVICE_KINDS[cell.device_kind]} x {cell.traffic_class} "
          f"(device {device}, case {cell.case}, scenario {cell.scenario}, {routing})")
    # Everything that can stop the cell is checked before the Target Device is touched.
    mitmweb = Mitmweb()
    mitmweb.confirm_ours()
    if cell.ca_routing:
        mitmweb.confirm_ca_routing()
    if cloud:
        confirm_rce_cost(config)  # before the first RCE call: status, start, console, deploy
    with cloud_run(rce_name) if cloud else nullcontext():
        console = cloud_console(rce_name) if cloud else physical_console(device_ip)
        try:
            time.sleep(1)  # the console replays recent history on connect
            if "already in use" in console.text:
                sys.exit(f"error: {device}'s console is in use by another client (close it and retry)")
            if console.ended:
                sys.exit(f"error: {device}'s console closed before the cell began (see above)")
            ca_routing = ["--ca-routing"] if cell.ca_routing else []
            app = str(REPO / config["flavours"][cell.flavour])
            subprocess.run([str(SCRIPTS / "deploy"), *ca_routing, device, app], check=True)
            # With the scenario first, then without: the lab ends with no scenario active.
            session = Session(device, cell, proxy_base, console, mitmweb, config)
            manipulated = launch_once(session, cell.scenario)
            baseline = launch_once(session, "")
        finally:
            console.close()

    verdict = judge(cell, baseline, manipulated, proxy_base)
    print(row(cell, verdict))
    return 1 if verdict.outcome == "fail" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
