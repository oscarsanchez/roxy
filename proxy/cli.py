"""App Profiles, their Scenarios, Target Devices, the running Lab Session and Recordings, for bin/roxy and
the scripts, which run it through proxy_cli (scripts/lib.sh) in the caller's folder. Needs
ROXY_CONFIG_DIR and LAB_WEB_PORT, MITMWEB_PASSWORD for the Lab Session, and RECORDINGS_ROOT
and LAB_SECRET for export, as proxy_cli passes them.

  cli.py app new NAME                    create App Profile NAME for the git repo of this folder
  cli.py app list                        each App Profile and its repo
  cli.py device add NAME (--ip IP [--proxied] | --rce DEVICE_NAME [--slug SLUG])
                                         register a Target Device (roxy device --help)
  cli.py device list                     each Target Device, its address and its kind
  cli.py device remove NAME              unregister the Target Device NAME
  cli.py scenario list [--app NAME]      the Scenarios of NAME (else the profile resolve
                                         finds) and the lab's own, each once with its source
  cli.py scenario set NAME...            make NAMEs the running lab's active Scenarios, in that
                                         order ('' clears them)
  cli.py scenario add NAME               make NAME active too, after the active ones
  cli.py scenario remove NAME            stop NAME, leaving the other active Scenarios
  cli.py scenario clear                  leave the running lab with no active Scenario
  cli.py resolve [--app NAME]            two lines, the App Profile to load and its repo (both
                                         empty for none); fails on a Scenario in both
  cli.py status [--since RUN|TIME]       the lab line, then the App Profile and Scenarios lines
                                         of roxy status; the lab down: its line, and exit 1
  cli.py status --json [--since RUN|TIME]
                                         the running lab's state (roxy status --help)
  cli.py flows --json [--filter EXPR] [--since RUN|TIME] [--limit N]
                                         the running lab's flows (roxy flows --help)
  cli.py export --har [RECORDING] [--filter EXPR] [-o FILE]
                                         a Recording as a HAR file (roxy export --help)
  cli.py run-id                          a fresh roxy launch run id

The device add and remove commands print what they changed, warnings on stderr, then a
restart hint. The scenario commands print the active Scenarios after the change, as
`scenario=A,B` (`scenario=none` for none). A refusal prints `error: ...` and exits 1; with the lab down, a Lab Session command prints
the `lab: down (...)` line instead.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from mitmproxy import flowfilter, io
from mitmproxy.addons.savehar import SaveHar
from mitmproxy.exceptions import FlowReadException

from lab.app_profiles import AppProfileError, AppProfiles, ScenarioInBoth
from lab.config import settings_root
from lab.lab_session import HttpTransport, LabDown, LabSession, LabSessionError, new_run_id, parse_since
from lab.scenarios import DEFAULT_SCENARIOS_DIR, scenario_value
from lab.settings_root import CLOUD_DEVICE, SettingsRoot, SettingsRootError, ecp_device_info, rce_knows

REFUSED = "refused: in both (rename the profile's)"
REDACTED_SECRET = "<secret>"


def app_profiles():
    return AppProfiles(settings_root(), DEFAULT_SCENARIOS_DIR)


def mitmweb():
    """The running lab's mitmweb API, on lib.sh's LAB_WEB_PORT."""
    return HttpTransport(os.environ["LAB_WEB_PORT"], os.environ.get("MITMWEB_PASSWORD", ""))


def lab_down():
    return f"lab: down (no mitmweb answers on {mitmweb().url}; roxy start)"


def app_new(args):
    profile = app_profiles().new(args.name, cwd=Path.cwd())
    print(f"App Profile '{args.name}' for {profile.repo}")
    print(f"  Scenarios, with their mocks next to them: {profile.scenarios_dir}/")
    print(f"  Public Endpoint Origins: origin_allowlist in {profile.file}")


def app_list(args):
    profiles = app_profiles()
    names = profiles.profiles()
    if not names:
        print("no App Profiles (roxy app new NAME, in an app's repo)")
    for name in names:
        print(f"{name:<20} {profiles.profile(name).repo}")


def settings():
    return SettingsRoot(settings_root(), ecp_device_info=ecp_device_info, rce_knows=rce_knows)


def device_add(args):
    root = settings()
    if args.ip:
        change = root.add_device(args.name, args.ip, proxied=args.proxied)
    else:
        change = root.add_cloud_device(args.name, args.rce_device_name, slug=args.slug)
    device = next(device for device in root.devices() if device.name == args.name)
    print(f"registered '{device.name}' ({device_address(device)}) as a {device.kind}")
    print_change(change)


def device_list(args):
    devices = settings().devices()
    if not devices:
        print("no Target Devices (roxy device add NAME --ip IP)")
    for device in devices:
        print(f"{device.name:<20} {device_address(device):<36} {device.kind}")


def device_remove(args):
    change = settings().remove_device(args.name)
    print(f"removed '{args.name}'")
    print_change(change)


def device_address(device):
    """Where the lab finds DEVICE: its IP, or a Cloud Device's rce Device Name and slug."""
    return f"rce {device.rce_device_name}, slug {device.slug}" if device.kind == CLOUD_DEVICE else device.ip


def print_change(change):
    """A Settings Root Change's notes, its warnings on stderr, then the restart hint: the
    lab reads its settings when it starts."""
    for note in change.notes:
        print(note)
    for warning in change.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print("restart the lab if it is running (roxy start), to use the change")


def scenario_list(args):
    profiles = app_profiles()
    app = profiles.resolve(args.app, cwd=Path.cwd())
    print(f"App Profile: {app or 'none'}")
    for name, source in profiles.scenarios(app):
        print(f"{name:<28} {REFUSED if isinstance(source, ScenarioInBoth) else source}")


def scenario_set(args):
    print_active(LabSession(mitmweb()).set_scenarios(args.names))


def scenario_add(args):
    print_active(LabSession(mitmweb()).add_scenario(args.name))


def scenario_remove(args):
    print_active(LabSession(mitmweb()).remove_scenario(args.name))


def print_active(scenarios):
    print(f"scenario={scenario_value(scenarios) or 'none'}")


def resolve(args):
    profiles = app_profiles()
    app = profiles.resolve(args.app, cwd=Path.cwd())
    refusals = [str(source) for _, source in profiles.scenarios(app) if isinstance(source, ScenarioInBoth)]
    if refusals:
        raise ScenarioInBoth("\n".join(refusals))
    print(app or "")
    print(profiles.profile(app).repo if app else "")


def status(args):
    session, profiles = LabSession(mitmweb()), app_profiles()
    try:
        state = session.state()
        app_dir, app_error = app_scenarios_dir(profiles, state.app)
        rules = session.scenario_rules(state, app_dir, since=args.since)
    except LabDown:
        if args.json:
            raise  # main says so on stderr
        print(lab_down())
        sys.exit(1)
    if args.json:
        print(json.dumps({**state._asdict(), "rules": [rule._asdict() for found in rules for rule in found.rules]}))
        return
    listed = []
    readable_app = state.app if app_dir else None
    for found in rules:
        listed.append(f"{found.scenario}  ({profiles.source(readable_app, found.scenario)})")
        if found.error:
            listed.append(f"  cannot read its rules: {found.error}")
        listed += [f"  {rule.rule}  {acted_on(rule.flows)}" for rule in found.rules]
    print(f"lab: up (mitmweb UI {mitmweb().url})")
    print(f"App Profile:       {state.app or 'none'}" + (f"  (cannot read it: {app_error})" if app_error else ""))
    print("Scenarios:         " + ("\n                   ".join(listed) or "none"))


def app_scenarios_dir(profiles, app):
    """The Scenarios folder of the loaded App Profile APP (None without one), and why APP
    cannot be read, renamed or deleted since the lab loaded it (None if it can). Without
    its folder, the active Scenarios are found as without a profile."""
    if not app:
        return None, None
    try:
        return profiles.profile(app).scenarios_dir, None
    except AppProfileError as e:
        return None, str(e)


def acted_on(flows):
    """A rule's count of flows, flagged when it acted on none."""
    if not flows:
        return "0 flows  (acted on nothing yet)"
    return f"{flows} flow{'' if flows == 1 else 's'}"


def flows(args):
    found = LabSession(mitmweb()).flows(filter=args.filter, since=args.since, limit=args.limit)
    print("[" + ",\n".join(json.dumps(flow) for flow in found) + "]")


def export(args):
    """A Recording's flows (those --filter matches, as save_stream_filter would) as a HAR,
    through mitmproxy's own HAR writer (hardump's), with the lab secret redacted."""
    recording = Path(args.recording) if args.recording else newest_recording()
    flows = [flow for flow in recorded_flows(recording) if not args.filter or args.filter(flow)]
    har = SaveHar().make_har(flows)
    if secret := os.environ.get("LAB_SECRET"):
        har = redacted(har, secret)
    output = os.path.abspath(args.output or f"{recording.stem}.har")
    try:
        with open(output, "x") as f:
            json.dump(har, f, indent=4)
    except FileExistsError:
        raise ExportRefused(f"{output} already exists (-o FILE picks another)") from None
    entries = len(har["log"]["entries"])
    print(f"wrote {output} ({entries} entr{'y' if entries == 1 else 'ies'})")


class ExportRefused(Exception):
    pass


def recorded_flows(recording):
    """The complete flows of RECORDING. A running lab's Recording can end in a flow cut
    short, which is left out; a file whose first flow does not read is not a Recording."""
    if not recording.is_file():
        raise ExportRefused(f"no Recording at {recording}")
    flows = []
    with open(recording, "rb") as f:
        try:
            for flow in io.FlowReader(f).stream():
                flows.append(flow)
        except FlowReadException:
            if not flows:
                raise ExportRefused(f"{recording} is not a mitmproxy Recording (.mitm)") from None
    return flows


def redacted(value, secret):
    """VALUE, a HAR or a part of one, with SECRET replaced by <secret> in every string,
    base64-encoded bodies included."""
    if isinstance(value, str):
        return value.replace(secret, REDACTED_SECRET)
    if isinstance(value, list):
        return [redacted(item, secret) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("encoding") == "base64":
        body = base64.b64decode(value["text"]).replace(secret.encode(), REDACTED_SECRET.encode())
        value = {**value, "text": base64.b64encode(body).decode()}
    return {key: redacted(item, secret) for key, item in value.items()}


def newest_recording():
    """The newest Recording in the Recordings root (lib.sh's RECORDINGS_ROOT), in any profile's folder."""
    root = Path(os.environ["RECORDINGS_ROOT"])
    recordings = list(root.glob("*/*.mitm"))
    if not recordings:
        raise ExportRefused(f"no Recordings in {root} (roxy start records one)")
    return max(recordings, key=lambda path: path.stat().st_mtime)


def run_id(args):
    print(new_run_id())


def since(value):
    try:
        return parse_since(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def flow_filter(value):
    """A mitmproxy filter expression, as save_stream_filter (which hardump honours) parses it."""
    try:
        return flowfilter.parse(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def limit(value):
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"not a number of flows (1 or more): {value!r}")
    return int(value)


def main():
    parser = argparse.ArgumentParser(prog="cli.py")
    commands = parser.add_subparsers(required=True)
    app = commands.add_parser("app").add_subparsers(required=True)
    app_new_parser = app.add_parser("new")
    app_new_parser.add_argument("name")
    app_new_parser.set_defaults(run=app_new)
    app.add_parser("list").set_defaults(run=app_list)
    device = commands.add_parser("device").add_subparsers(required=True)
    device_add_parser = device.add_parser("add", prog="roxy device add")
    device_add_parser.add_argument("name")
    where = device_add_parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--ip")
    where.add_argument("--rce", dest="rce_device_name", metavar="DEVICE_NAME")
    device_add_parser.add_argument("--proxied", action="store_true")
    device_add_parser.add_argument("--slug")
    device_add_parser.set_defaults(run=device_add)
    device.add_parser("list").set_defaults(run=device_list)
    device_remove_parser = device.add_parser("remove")
    device_remove_parser.add_argument("name")
    device_remove_parser.set_defaults(run=device_remove)
    scenario = commands.add_parser("scenario").add_subparsers(required=True)
    scenario_list_parser = scenario.add_parser("list")
    scenario_list_parser.add_argument("--app")
    scenario_list_parser.set_defaults(run=scenario_list)
    scenario_set_parser = scenario.add_parser("set")
    scenario_set_parser.add_argument("names", nargs="+")
    scenario_set_parser.set_defaults(run=scenario_set)
    for command, run in (("add", scenario_add), ("remove", scenario_remove)):
        scenario_change_parser = scenario.add_parser(command)
        scenario_change_parser.add_argument("name")
        scenario_change_parser.set_defaults(run=run)
    scenario.add_parser("clear").set_defaults(run=scenario_set, names=[])
    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--app")
    resolve_parser.set_defaults(run=resolve)
    status_parser = commands.add_parser("status", prog="roxy status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.add_argument("--since", type=since)
    status_parser.set_defaults(run=status)
    flows_parser = commands.add_parser("flows", prog="roxy flows")
    flows_parser.add_argument("--json", action="store_true", required=True)
    flows_parser.add_argument("--filter")
    flows_parser.add_argument("--since", type=since)
    flows_parser.add_argument("--limit", type=limit)
    flows_parser.set_defaults(run=flows)
    export_parser = commands.add_parser("export", prog="roxy export")
    export_parser.add_argument("--har", action="store_true", required=True)
    export_parser.add_argument("recording", nargs="?")
    export_parser.add_argument("--filter", type=flow_filter)
    export_parser.add_argument("-o", dest="output")
    export_parser.set_defaults(run=export)
    commands.add_parser("run-id").set_defaults(run=run_id)
    args = parser.parse_args()
    if args.run == device_add and args.proxied and not args.ip:
        device_add_parser.error("--proxied goes with --ip")
    if args.run == device_add and args.slug and args.ip:
        device_add_parser.error("--slug goes with --rce")
    try:
        args.run(args)
    except LabDown:
        sys.exit(lab_down())
    except (AppProfileError, SettingsRootError, LabSessionError, ExportRefused) as e:
        sys.exit("\n".join(f"error: {line}" for line in str(e).splitlines()))


if __name__ == "__main__":
    main()
