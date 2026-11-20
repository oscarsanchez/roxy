"""Record a Physical Device's BrightScript console to a file (scripts/console).

Usage: scripts/console <device-name> [--launch CASE [--scenario NAME]] [--seconds N]

Connects first, so nothing the run prints is missed. The device replays recent
history on connect; that replay is left out. With --launch it runs scripts/launch
after connecting and stops at that run's result line (or a crash). The console goes
to out/console/; this prints only the file, the result line and any crash marker.
"""

import argparse
import re
import shlex
import subprocess
import sys
import time

from run_cell import SCRIPTS, lab, physical_console, save_log
from verdict import CRASH_MARKERS, result_line

REPLAY_S = 1  # the replay of recent history arrives within this after connecting
GRACE_S = 2   # after the result line, for the lines printed right after it


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scripts/console", description="Record a Physical Device's console.")
    parser.add_argument("device", help="a device name from proxy/config/devices.json")
    parser.add_argument("--launch", metavar="CASE", help="launch this case and stop at its result line")
    parser.add_argument("--scenario", help="with --launch: the lab scenario to set first ('' clears it)")
    parser.add_argument("--seconds", type=float, default=60, help="stop after this long (default 60)")
    args = parser.parse_args(argv)
    if args.scenario is not None and not args.launch:
        parser.error("--scenario needs --launch")

    ip = lab(f"device_field {shlex.quote(args.device)} ip")
    if not ip:
        sys.exit(f"error: {args.device} has no ip: Physical Devices only (a Cloud Device: rce console)")
    console = physical_console(ip)
    try:
        time.sleep(REPLAY_S)
        if "already in use" in console.text:
            sys.exit(f"error: {args.device}'s console is in use by another client")
        mark = len(console.text)
        deadline = time.time() + args.seconds
        run_id = result = None
        if args.launch:
            scenario = ["--scenario", args.scenario] if args.scenario is not None else []
            out = subprocess.run([str(SCRIPTS / "launch"), *scenario, args.device, args.launch],
                                 check=True, stdout=subprocess.PIPE, text=True).stdout
            run_id = next(line[4:] for line in out.splitlines() if line.startswith("run="))
        try:
            while time.time() < deadline and not console.ended:
                text = console.text[mark:]
                if run_id and (result := result_line(text, args.launch, run_id)):
                    deadline = min(deadline, time.time() + GRACE_S)
                if run_id and any(m in text for m in CRASH_MARKERS):
                    deadline = min(deadline, time.time() + GRACE_S)
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        text = console.text[mark:]
    finally:
        console.close()

    name = "-".join(filter(None, [re.sub(r"[^A-Za-z0-9.]+", "_", args.device).strip("_"), time.strftime("%Y%m%d-%H%M%S"), args.launch, run_id]))
    print(f"console: {save_log(text, 'console', name + '.log')}")
    if args.launch:
        print(result or f"no result line for {args.launch} run={run_id}")
    crashes = [m for m in CRASH_MARKERS if m in text]
    if crashes:
        print(f"crash: {', '.join(crashes)}")
    return 0 if not args.launch or (result and not crashes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
