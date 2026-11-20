"""App Profiles, their Scenarios and the running Lab Session, for bin/roxy and the scripts,
which run it through proxy_cli (scripts/lib.sh) in the caller's folder. Needs
ROXY_CONFIG_DIR and LAB_WEB_PORT, and MITMWEB_PASSWORD for the Lab Session, as proxy_cli
passes them.

  cli.py app new NAME                    create App Profile NAME for the git repo of this folder
  cli.py app list                        each App Profile and its repo
  cli.py scenario list [--app NAME]      the Scenarios of NAME (else the profile resolve
                                         finds) and the lab's own, each once with its source
  cli.py scenario set NAME               make NAME the running lab's active Scenario ('' clears it)
  cli.py scenario clear                  leave the running lab with no active Scenario
  cli.py resolve [--app NAME]            two lines, the App Profile to load and its repo (both
                                         empty for none); fails on a Scenario in both
  cli.py status                          the lab line, then the App Profile and Scenario lines
                                         of roxy status; the lab down: its line, and exit 1
  cli.py flows --json [--filter EXPR] [--since RUN|TIME] [--limit N]
                                         the running lab's flows (roxy flows --help)
  cli.py run-id                          a fresh roxy launch run id

A refusal prints `error: ...` and exits 1; with the lab down, a Lab Session command prints
the `lab: down (...)` line instead.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from lab.app_profiles import AppProfileError, AppProfiles, ScenarioInBoth
from lab.config import settings_root
from lab.lab_session import HttpTransport, LabDown, LabSession, LabSessionError, new_run_id, parse_since
from lab.scenarios import DEFAULT_SCENARIOS_DIR

REFUSED = "refused: in both (rename the profile's)"


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


def scenario_list(args):
    profiles = app_profiles()
    app = profiles.resolve(args.app, cwd=Path.cwd())
    print(f"App Profile: {app or 'none'}")
    for name, source in profiles.scenarios(app):
        print(f"{name:<28} {REFUSED if isinstance(source, ScenarioInBoth) else source}")


def scenario_set(args):
    LabSession(mitmweb()).set_scenario(args.name)
    print(f"scenario={args.name or 'none'}")


def resolve(args):
    profiles = app_profiles()
    app = profiles.resolve(args.app, cwd=Path.cwd())
    refusals = [str(source) for _, source in profiles.scenarios(app) if isinstance(source, ScenarioInBoth)]
    if refusals:
        raise ScenarioInBoth("\n".join(refusals))
    print(app or "")
    print(profiles.profile(app).repo if app else "")


def status(args):
    try:
        app, scenario = LabSession(mitmweb()).state()
    except LabDown:
        print(lab_down())
        sys.exit(1)
    source = scenario and app_profiles().source(app, scenario)
    print(f"lab: up (mitmweb UI {mitmweb().url})")
    print(f"App Profile:       {app or 'none'}")
    print(f"Scenario:          {f'{scenario}  ({source})' if scenario else 'none'}")


def flows(args):
    found = LabSession(mitmweb()).flows(filter=args.filter, since=args.since, limit=args.limit)
    print("[" + ",\n".join(json.dumps(flow) for flow in found) + "]")


def run_id(args):
    print(new_run_id())


def since(value):
    try:
        return parse_since(value)
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
    scenario = commands.add_parser("scenario").add_subparsers(required=True)
    scenario_list_parser = scenario.add_parser("list")
    scenario_list_parser.add_argument("--app")
    scenario_list_parser.set_defaults(run=scenario_list)
    scenario_set_parser = scenario.add_parser("set")
    scenario_set_parser.add_argument("name")
    scenario_set_parser.set_defaults(run=scenario_set)
    scenario.add_parser("clear").set_defaults(run=scenario_set, name="")
    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--app")
    resolve_parser.set_defaults(run=resolve)
    commands.add_parser("status").set_defaults(run=status)
    flows_parser = commands.add_parser("flows", prog="roxy flows")
    flows_parser.add_argument("--json", action="store_true", required=True)
    flows_parser.add_argument("--filter")
    flows_parser.add_argument("--since", type=since)
    flows_parser.add_argument("--limit", type=limit)
    flows_parser.set_defaults(run=flows)
    commands.add_parser("run-id").set_defaults(run=run_id)
    args = parser.parse_args()
    try:
        args.run(args)
    except LabDown:
        sys.exit(lab_down())
    except (AppProfileError, LabSessionError) as e:
        sys.exit("\n".join(f"error: {line}" for line in str(e).splitlines()))


if __name__ == "__main__":
    main()
