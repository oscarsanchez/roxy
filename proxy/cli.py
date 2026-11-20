"""App Profiles and their Scenarios for bin/roxy and scripts/start-lab, which run it through
proxy_cli (scripts/lib.sh) in the caller's folder. Needs ROXY_CONFIG_DIR, as lib.sh exports it.

  cli.py app new NAME                    create App Profile NAME for the git repo of this folder
  cli.py app list                        each App Profile and its repo
  cli.py scenario list [--app NAME]      the Scenarios of NAME (else the profile resolve
                                         finds) and the lab's own, each once with its source
  cli.py resolve [--app NAME]            two lines, the App Profile to load and its repo (both
                                         empty for none); fails on a Scenario in both
  cli.py source [--app NAME] SCENARIO    where SCENARIO comes from: 'App Profile NAME' or 'lab'

A refusal prints `error: ...` and exits 1.
"""

import argparse
import sys
from pathlib import Path

from lab.app_profiles import AppProfileError, AppProfiles, ScenarioInBoth
from lab.config import settings_root
from lab.scenarios import DEFAULT_SCENARIOS_DIR

REFUSED = "refused: in both (rename the profile's)"


def app_new(profiles, args):
    profile = profiles.new(args.name, cwd=Path.cwd())
    print(f"App Profile '{args.name}' for {profile.repo}")
    print(f"  Scenarios, with their mocks next to them: {profile.scenarios_dir}/")
    print(f"  Public Endpoint Origins: origin_allowlist in {profile.file}")


def app_list(profiles, args):
    names = profiles.profiles()
    if not names:
        print("no App Profiles (roxy app new NAME, in an app's repo)")
    for name in names:
        print(f"{name:<20} {profiles.profile(name).repo}")


def scenario_list(profiles, args):
    app = profiles.resolve(args.app, cwd=Path.cwd())
    print(f"App Profile: {app or 'none'}")
    for name, source in profiles.scenarios(app):
        print(f"{name:<28} {REFUSED if isinstance(source, ScenarioInBoth) else source}")


def resolve(profiles, args):
    app = profiles.resolve(args.app, cwd=Path.cwd())
    refusals = [str(source) for _, source in profiles.scenarios(app) if isinstance(source, ScenarioInBoth)]
    if refusals:
        raise ScenarioInBoth("\n".join(refusals))
    print(app or "")
    print(profiles.profile(app).repo if app else "")


def source(profiles, args):
    print(profiles.source(args.app, args.scenario))


def main():
    parser = argparse.ArgumentParser(prog="cli.py")
    commands = parser.add_subparsers(required=True)
    app = commands.add_parser("app").add_subparsers(required=True)
    app_new_parser = app.add_parser("new")
    app_new_parser.add_argument("name")
    app_new_parser.set_defaults(run=app_new)
    app.add_parser("list").set_defaults(run=app_list)
    scenario_list_parser = commands.add_parser("scenario").add_subparsers(required=True).add_parser("list")
    scenario_list_parser.add_argument("--app")
    scenario_list_parser.set_defaults(run=scenario_list)
    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--app")
    resolve_parser.set_defaults(run=resolve)
    source_parser = commands.add_parser("source")
    source_parser.add_argument("--app")
    source_parser.add_argument("scenario")
    source_parser.set_defaults(run=source)
    args = parser.parse_args()
    try:
        args.run(AppProfiles(settings_root(), DEFAULT_SCENARIOS_DIR), args)
    except AppProfileError as e:
        sys.exit("\n".join(f"error: {line}" for line in str(e).splitlines()))


if __name__ == "__main__":
    main()
