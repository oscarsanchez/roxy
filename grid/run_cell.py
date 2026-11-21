"""Fill grid cells on Target Devices through the running lab (Seam B).

Usage: scripts/grid <flavours> <device-kinds> <traffic-classes> [--proxy-base URL] [--ca-routing]
                    [--separator /|/;|/,/;] [--device NAME]
Each of flavours, device kinds and traffic classes is one value, a comma list or `all`.

Deploys each flavour once per Target Device, then launches each cell's case twice with
scripts/launch: first with the cell's Manipulation scenario, then with no scenario (so the
lab is left with none active). The oracles are the lab's flows (`roxy flows --json`) and
the Lab App's result line on the console. The lab is read through the public roxy commands only.
Cells are defined in grid/cells.toml; the verdict logic is in verdict.py.
"""

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import tomllib
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from itertools import groupby
from operator import attrgetter
from pathlib import Path

from verdict import (
    CRASH_MARKERS, DEVICE_KINDS, Cell, Run, Verdict, cell_from_config, device_flows, judge, origin_host, result_line,
    row, setup, table,
)

GRID = Path(__file__).resolve().parent
REPO = GRID.parent
SCRIPTS = REPO / "scripts"
ROXY = REPO / "bin" / "roxy"
CONSOLE_PORT = 8085  # BrightScript console: print output of every thread, one client at a time
LAUNCH_S = 5  # projected time of one scripts/launch call


class CellFailed(Exception):
    """Something went wrong in one cell: it fails, with this reason, and the batch goes on."""


class CommandFailed(SystemExit):
    """A command failed, and said why on stderr. Inside a cell it fails that cell (fill);
    outside one it ends the grid with the command's exit status."""

    def __init__(self, command: list[str], returncode: int):
        super().__init__(returncode)
        self.reason = f"{' '.join([Path(command[0]).name, *command[1:2]])} failed (exit {returncode}, see above)"


def output(command: list[str]) -> str:
    """The command's output. Its error, which says what is wrong, raises CommandFailed."""
    done = subprocess.run(command, stdout=subprocess.PIPE, text=True)
    if done.returncode:
        raise CommandFailed(command, done.returncode)
    return done.stdout.strip()


def lab(snippet: str) -> str:
    """Run a shell snippet with scripts/lib.sh loaded (one source for settings, secrets,
    devices, LAN IP)."""
    return output(["bash", "-c", f'set -euo pipefail; . "$1"; {snippet}', "lab", str(SCRIPTS / "lib.sh")])


def roxy(*args: str):
    """The running lab's answer to a roxy command, parsed from its JSON (the lab down: roxy
    says so, and the cell ends)."""
    return json.loads(output([str(ROXY), *args]))


def save_log(text: str, *parts: str) -> Path:
    """Write text to <ROXY_OUT_DIR>/<parts...> and return the path, relative to the repo when
    it is in it. scripts/lib.sh exports ROXY_OUT_DIR: the checkout's gitignored out/ by default."""
    path = Path(os.environ["ROXY_OUT_DIR"], *parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path.relative_to(REPO) if path.is_relative_to(REPO) else path


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


def physical_console(device: str, ip: str) -> Console:
    """DEVICE's port 8085 on the LAN. Unlike `nc` without -d, a socket keeps receiving new output."""
    try:
        sock = socket.create_connection((ip, CONSOLE_PORT), timeout=10)
    except OSError as error:
        sys.exit(f"error: {device} did not answer at {ip}:{CONSOLE_PORT} ({error}): "
                 "it may be on another network than this Mac's")
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
def cloud_run(name: str, max_runtime: int):
    """A Run of the Cloud Device NAME around a batch's cells. Started here if it has none,
    capped at MAX_RUNTIME s (a backstop if this process is killed outright), and then
    stopped here however the batch ends, so it never leaves a Run billing. A Run that was
    already going is someone else's: it is used and left running."""
    if has_run(name):
        yield
        return
    try:
        # It waits until the Run takes input, and stops the Run itself if that fails.
        rce("device", "start", name, "--max-runtime", str(max_runtime))
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


def confirm_ours(state: dict) -> None:
    """Stop unless the running lab (its `roxy status --json`) is this checkout's: its
    scenarios are the ones cells.toml names, and nobody else's lab gets a scenario set or a
    device launched."""
    ours = str(REPO / "proxy" / "scenarios")
    if state["scenarios_dir"] != ours:
        sys.exit(f"error: the running lab is not this checkout's (its scenarios: {state['scenarios_dir']}). "
                 f"Start it from here: {ROXY} start")


def confirm_ca_routing(state: dict) -> None:
    """Stop unless the running lab is in CA Routing: otherwise it refuses every Origin URL."""
    if not state["ca_routing"]:
        sys.exit(f"error: the lab is not in CA Routing. Start it with {ROXY} start --ca-routing")


def confirm_rce_cost(config: dict, cells: list[Cell]) -> int:
    """Print the projected Cloud Device time and cost of CELLS (one Run, one deploy per
    flavour), and ask before any RCE call. Returns the projected seconds."""
    per_run = config["run_timeout_s"] + config["settle_s"] + LAUNCH_S
    deploys = len({cell.flavour for cell in cells})
    seconds = config["rce_start_s"] + deploys * config["rce_deploy_s"] + 2 * len(cells) * per_run
    usd = seconds / 3600 * config["rce_usd_per_device_hour"]
    one = len(cells) == 1
    print(
        f"{'This cell keeps' if one else f'These {len(cells)} cells keep'} the Cloud Device busy for up to "
        f"{seconds / 60:.1f} min (start-up {config['rce_start_s']} s + "
        f"{'deploy' if deploys == 1 else f'{deploys} deploys x'} {config['rce_deploy_s']} s + "
        f"{2 * len(cells)} launches x {per_run} s), "
        f"about ${usd:.3f} at ${config['rce_usd_per_device_hour']:.2f} per device-hour.\n"
        f"The grid starts the Cloud Device if it has no Run and stops it after the {'' if one else 'last '}cell, "
        f"also when {'the' if one else 'a'} cell fails or you press Ctrl-C. "
        "A Run that was already going is left running."
    )
    try:
        answer = input("Use RCE now? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        sys.exit("RCE not touched.")
    return seconds


@dataclass
class Session:
    """What both launches of a cell share."""

    device: str
    cell: Cell
    proxy_base: str
    console: Console
    config: dict


def launch_once(session: Session, scenario: str) -> Run:
    device, cell, console, config = session.device, session.cell, session.console, session.config
    mark = len(console.text)
    out = subprocess.run(
        [str(SCRIPTS / "launch"), "--scenario", scenario, "--proxy-base", session.proxy_base, device,
         f"case={cell.case}", f"separator={cell.separator}"],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout
    run_id = next((line[4:] for line in out.splitlines() if line.startswith("run=")), None)
    if not run_id:
        raise CellFailed("scripts/launch printed no run id")

    deadline = time.time() + config["run_timeout_s"]
    while True:
        ended = console.ended  # read before the text: once ended, the text is whole
        text = console.text[mark:]
        result = result_line(text, cell.case, run_id)
        crashed = any(m in text for m in CRASH_MARKERS)
        if result or crashed or ended or time.time() >= deadline:
            break
        time.sleep(0.5)
    if ended and not (result or crashed):
        raise CellFailed(f"{device}'s console closed before a result line")
    time.sleep(config["settle_s"])
    # Before the next launch: since this run id, the lab holds this run's flows only.
    flows = device_flows(roxy("flows", "--json", "--since", run_id), device)
    run = Run(result=result, flows=flows, console=console.text[mark:])
    hosts = sorted({origin_host(f) for f in flows})
    # Kept for the verdict's evidence: the console and flows behind each launch.
    name = f"{cell.flavour}-{setup(cell.device_kind, cell.ca_routing)}-{cell.traffic_class}-{run_id}"
    log = save_log(run.console, "grid", f"{name}.console.log")
    save_log(json.dumps(flows, indent=1), "grid", f"{name}.flows.json")
    print(f"  {'with ' + scenario if scenario else 'without a scenario'}: {result or 'no result line'}")
    print(f"    {len(flows)} flows from the Target Device: {', '.join(hosts) or 'none'}")
    print(f"    console: {log} (flows: .flows.json beside it)")
    return run


def values(choices: list[str]):
    """An argparse type: a comma list of CHOICES, or `all`, as the CHOICES it names, in
    CHOICES' order and each once (the batch's fixed order)."""

    def parse(text: str) -> list[str]:
        given = choices if text == "all" else text.split(",")
        unknown = [v for v in given if v not in choices]
        if unknown:
            raise argparse.ArgumentTypeError(f"unknown {', '.join(unknown)} (choose from {', '.join(choices)} or all)")
        return [c for c in choices if c in given]

    return parse


def parse_args(argv: list[str], config: dict) -> argparse.Namespace:
    """The command line, with `cells`: every cell it names, in the order they run (Physical
    Device cells first, then by flavour, separator and traffic class)."""
    parser = argparse.ArgumentParser(prog="scripts/grid", description="Fill grid cells.")
    parser.add_argument("flavour", type=values(list(config["flavours"])), help="comma list or all")
    parser.add_argument("device_kind", type=values(list(DEVICE_KINDS)), help="comma list or all")
    parser.add_argument("traffic_class", type=values(list(config["classes"])), help="comma list or all")
    parser.add_argument("--proxy-base", help="Proxy Base to launch with (default: the LAN one for a Physical Device, "
                                             "the running tunnel's public one for a Cloud Device)")
    parser.add_argument("--ca-routing", action="store_true",
                        help="CA Routing, on the Physical Device behind the CA Routing router (README, CA Routing)")
    parser.add_argument("--separator", type=values(["/", "/;"]), default=["/"],
                        help="the Prefixed URL form the Lab App builds: / (the lab's own), /; (Charles-style) "
                             "or both ('/,/;')")
    parser.add_argument("--device", help="the Target Device for this call, a name from devices.json, instead of "
                                         "grid_devices in settings.json (one device kind only)")
    args = parser.parse_args(argv)
    if args.device and len(args.device_kind) > 1:
        parser.error("--device is for one device kind: its Target Device fills that kind's cells")
    if args.ca_routing and "cloud" in args.device_kind:
        parser.error("CA Routing is for Physical Devices only")
    if args.ca_routing and args.separator != ["/"]:
        parser.error("--separator is for Prefix Routing: a CA Routing build calls Origin URLs directly")
    args.cells = [
        replace(cell_from_config(config, flavour, kind, traffic_class, args.ca_routing), separator=separator)
        for kind in args.device_kind
        for flavour in args.flavour
        for separator in args.separator
        for traffic_class in args.traffic_class
    ]
    return args


@dataclass
class Target:
    """The Target Device a batch fills one kind's cells on, as the settings name it."""

    device: str
    proxy_base: str
    shown_proxy_base: str  # proxy_base as the grid prints it: its secret as <secret> (scripts/lib.sh redact_secret)
    ip: str | None = None  # a Physical Device's, for its console
    rce_name: str | None = None  # a Cloud Device's


def target(device_kind: str, ca_routing: bool, proxy_base: str | None, device: str | None) -> Target:
    """The Target Device for DEVICE_KIND cells: DEVICE, else the one the settings root names.
    Local and free."""
    cloud = device_kind == "cloud"
    device = device or lab(f"grid_device {setup(device_kind, ca_routing)}")
    proxy_base = (proxy_base or lab("require_public_proxy_base" if cloud else "lan_proxy_base")).rstrip("/")
    if cloud:
        rce_name = lab(f"rce_device_name {shlex.quote(device)}")
        if not rce_name:
            sys.exit(f"error: {device} has no rce_device_name in devices.json (settings root)")
        shown = lab(f"load_env; redact_secret {shlex.quote(proxy_base)}")
        return Target(device, proxy_base, shown, rce_name=rce_name)
    ip = lab(f"device_field {shlex.quote(device)} ip")
    if not ip:
        sys.exit(f"error: {device} has no ip in devices.json (settings root)")
    return Target(device, proxy_base, proxy_base, ip=ip)


def describe(cell: Cell, target: Target) -> str:
    routing = ("CA Routing build" if cell.ca_routing
               else f"Proxy Base {target.shown_proxy_base}, separator {cell.separator}")
    return (f"cell: {cell.flavour} x {DEVICE_KINDS[cell.device_kind]} x {cell.traffic_class} "
            f"(device {target.device}, case {cell.case}, scenario {cell.scenario}, {routing})")


def fill(session: Session) -> Verdict:
    """The cell's verdict from its two launches: with its scenario first, then without, so
    the lab ends with no scenario active. An error in either fails the cell, not the batch;
    Ctrl-C (KeyboardInterrupt) still ends the batch."""
    try:
        manipulated = launch_once(session, session.cell.scenario)
        baseline = launch_once(session, "")
    except subprocess.CalledProcessError as error:
        return Verdict("fail", f"scripts/launch failed (exit {error.returncode}, see above)")
    except CommandFailed as error:
        return Verdict("fail", error.reason)
    except CellFailed as error:
        return Verdict("fail", str(error))
    except Exception as error:  # anything else that goes wrong in the cell: its row names it
        return Verdict("fail", f"{type(error).__name__}: {error}")
    return judge(session.cell, baseline, manipulated, session.proxy_base)


def fill_on(target: Target, cells: list[Cell], config: dict, max_runtime: int | None,
            batch: bool) -> list[tuple[Cell, Verdict]]:
    """Fill CELLS, in order, on TARGET: one console, one Run (a Cloud Device's, capped at
    MAX_RUNTIME s) and one deploy per flavour. In a batch each cell's lines start with its
    cell line; each cell's lines end with its row."""
    results = []
    with cloud_run(target.rce_name, max_runtime) if target.rce_name else nullcontext():
        console = cloud_console(target.rce_name) if target.rce_name else physical_console(target.device, target.ip)
        try:
            time.sleep(1)  # the console replays recent history on connect
            if "already in use" in console.text:
                sys.exit(f"error: {target.device}'s console is in use by another client (close it and retry)")
            if console.ended:
                sys.exit(f"error: {target.device}'s console closed before the cell began (see above)")
            for flavour, flavour_cells in groupby(cells, key=attrgetter("flavour")):
                ca_routing = ["--ca-routing"] if cells[0].ca_routing else []
                app = str(REPO / config["flavours"][flavour])
                deploy = subprocess.run([str(SCRIPTS / "deploy"), *ca_routing, target.device, app]).returncode
                for cell in flavour_cells:
                    if batch:
                        print(describe(cell, target))
                    verdict = (Verdict("fail", f"scripts/deploy failed (exit {deploy}, see above)") if deploy
                               else fill(Session(target.device, cell, target.proxy_base, console, config)))
                    print(row(cell, verdict))
                    results.append((cell, verdict))
        finally:
            console.close()
    return results


def main(argv: list[str]) -> int:
    config = tomllib.loads((GRID / "cells.toml").read_text())
    args = parse_args(argv, config)
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # a kill stops the Run as Ctrl-C does

    targets = {kind: target(kind, args.ca_routing, args.proxy_base, args.device) for kind in args.device_kind}
    for cell in args.cells:
        print(describe(cell, targets[cell.device_kind]))
    # Everything that can stop the batch is checked before a Target Device is touched.
    state = roxy("status", "--json")
    confirm_ours(state)
    if args.ca_routing:
        confirm_ca_routing(state)
    cloud_cells = [cell for cell in args.cells if cell.device_kind == "cloud"]
    max_runtime = None
    if cloud_cells:  # before the first RCE call: status, start, console, deploy
        max_runtime = confirm_rce_cost(config, cloud_cells) + config["rce_cap_margin_s"]

    batch = len(args.cells) > 1
    results = []
    for kind, cells in groupby(args.cells, key=attrgetter("device_kind")):  # physical first
        results += fill_on(targets[kind], list(cells), config, max_runtime, batch)
    if batch:
        print(table(results))
    return 1 if any(verdict.outcome == "fail" for _, verdict in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
