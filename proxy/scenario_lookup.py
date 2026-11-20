"""The Scenario lookup rule for the shell scripts: roxy start refuses a clash, roxy status
names an active Scenario's source. The rule itself is find_scenario (lab/scenarios.py).
Usage (from proxy/; needs ROXY_CONFIG_DIR, as scripts/lib.sh exports it):
  uv run python scenario_lookup.py [--app NAME] check            fail naming every Scenario of
                                                                 App Profile NAME the rule refuses
  uv run python scenario_lookup.py [--app NAME] source SCENARIO  print 'App Profile NAME' or 'lab'
"""

import argparse
import sys

from lab.app_profiles import AppProfiles
from lab.config import settings_root
from lab.scenarios import DEFAULT_SCENARIOS_DIR, find_scenario


def main():
    parser = argparse.ArgumentParser(prog="scenario_lookup.py")
    parser.add_argument("--app", default="")
    parser.add_argument("command", choices=["check", "source"])
    parser.add_argument("scenario", nargs="?")
    args = parser.parse_args()
    app_dir = AppProfiles(settings_root(), DEFAULT_SCENARIOS_DIR).profile(args.app).scenarios_dir if args.app else None
    if args.command == "source":
        if not args.scenario:
            parser.error("source needs a Scenario name")
        names = [args.scenario]
    else:
        names = sorted(path.stem for path in app_dir.glob("*.toml")) if app_dir else []
    refused = []
    for name in names:
        try:
            found = find_scenario(name, app_dir, DEFAULT_SCENARIOS_DIR)
        except ValueError as e:
            refused.append(f"error: {e}")
    if refused:
        sys.exit("\n".join(refused))
    if args.command == "source":
        print(f"App Profile {args.app}" if found.parent == app_dir else "lab")


if __name__ == "__main__":
    main()
