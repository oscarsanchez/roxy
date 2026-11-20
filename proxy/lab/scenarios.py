"""Scenarios: named files of Manipulation rules, one of them active lab-wide.

A scenario is `<lab_scenarios_dir>/<name>.toml`, a list of rules:

    [[rule]]
    name = "httpbin json fails"
    filter = "~d httpbin.org & ~u /json"   # mitmproxy filter expression
    status = 503                           # exactly one action (see scenario_actions)

Set `lab_scenario` (mitmweb options, `--set`, or the options API) to switch
scenarios without a restart; empty means none. The active file is reloaded
when it changes. The loaded App Profile's Scenarios (lab.app_profile) join the
lab's own: find_scenario holds the lookup rule, for this addon and for lab.app_profiles
(the CLI's Scenario listing and sources).
"""

import logging
import tomllib
from pathlib import Path

from mitmproxy import ctx, exceptions, flowfilter

from lab.refusal import refused
from lab.scenario_actions import ACTIONS

DEFAULT_SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class Rule:
    def __init__(self, name, filter_expr, action):
        self.name = name
        self.matches = flowfilter.parse(filter_expr)  # ValueError on bad syntax
        self.action = action


def applied_rules(flow):
    """The names of the Scenario rules that acted on this flow, in the order they first did."""
    return flow.metadata.get("lab_scenario_rules", [])


def find_scenario(name, app_scenarios_dir, lab_scenarios_dir):
    """The file of the Scenario NAME: the loaded App Profile's (in app_scenarios_dir, None
    without a profile), else the lab's own. A name in both is refused (ValueError) rather
    than one picked silently; a name in neither gives the lab's path, which fails to load."""
    lab_file = lab_scenarios_dir / f"{name}.toml"
    app_file = app_scenarios_dir and app_scenarios_dir / f"{name}.toml"
    if not (app_file and app_file.is_file()):
        return lab_file
    if lab_file.is_file():
        raise ValueError(
            f"the Scenario {name!r} is in both the lab's Scenarios ({lab_file}) "
            f"and the App Profile's ({app_file}); rename the profile's"
        )
    return app_file


def load_scenario(path):
    """Parse a scenario file into its rules. Raises ValueError or OSError."""
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    rules = []
    for i, spec in enumerate(doc.get("rule", []), 1):
        name = spec.pop("name", None)
        if not isinstance(name, str):
            raise ValueError(f"rule #{i}: needs a name")
        filter_expr = spec.pop("filter", None)
        if not isinstance(filter_expr, str):
            raise ValueError(f"rule {name!r}: needs a filter expression")
        if len(spec) != 1 or next(iter(spec)) not in ACTIONS:
            raise ValueError(f"rule {name!r}: needs exactly one action of {', '.join(ACTIONS)}")
        [(key, value)] = spec.items()
        try:
            rules.append(Rule(name, filter_expr, ACTIONS[key](value, path.parent)))
        except ValueError as e:
            raise ValueError(f"rule {name!r}: {e}") from e
    return rules


class Scenarios:
    def __init__(self, app_profile):
        self.app_profile = app_profile
        self.path = None  # active scenario file, None for no scenario
        self.mtime = None
        self.rules = []

    def load(self, loader):
        loader.add_option("lab_scenario", str, "", "Active lab scenario (a file name without .toml); empty for none.")
        loader.add_option("lab_scenarios_dir", str, str(DEFAULT_SCENARIOS_DIR), "Directory of lab scenario files.")

    def configure(self, updated):
        if not {"lab_scenario", "lab_scenarios_dir", "lab_app"} & updated:
            return
        name = ctx.options.lab_scenario
        if not name:
            self.path, self.mtime, self.rules = None, None, []
            return
        try:
            path = find_scenario(name, self.app_profile.scenarios_dir, Path(ctx.options.lab_scenarios_dir))
            mtime, rules = path.stat().st_mtime_ns, load_scenario(path)
        except (ValueError, OSError) as e:
            raise exceptions.OptionsError(f"scenario {name!r}: {e}") from e
        self.path, self.mtime, self.rules = path, mtime, rules
        logging.info(f"lab scenario {name!r} active: {len(rules)} rule(s)")

    def reload_if_changed(self):
        """Pick up edits to the active file. A broken edit keeps the last good rules."""
        try:
            mtime = self.path.stat().st_mtime_ns
            if mtime == self.mtime:
                return
            self.mtime = mtime  # report a broken edit once, not on every flow
            self.rules = load_scenario(self.path)
            logging.info(f"lab scenario {self.path.stem!r} reloaded: {len(self.rules)} rule(s)")
        except (ValueError, OSError) as e:
            logging.error(f"lab scenario {self.path.stem!r} not reloaded, keeping its last good rules: {e}")

    async def before_guards(self, flow):
        """Called by ScenariosBeforeGuards, the first of this addon's hooks per flow."""
        if self.path:
            self.reload_if_changed()  # once per flow, so a flow sees one version
        await self._dispatch("before_guards", flow)

    async def requestheaders(self, flow):
        await self._dispatch("requestheaders", flow)

    async def request(self, flow):
        await self._dispatch("request", flow)

    async def responseheaders(self, flow):
        await self._dispatch("responseheaders", flow)

    async def response(self, flow):
        await self._dispatch("response", flow)

    async def _dispatch(self, hook, flow):
        if refused(flow):  # a guard's answer must stay visible
            return
        for rule in self.rules:
            handler = getattr(rule.action, hook, None)
            if handler and rule.matches(flow):
                applied = flow.metadata.setdefault("lab_scenario_rules", [])
                if rule.name not in applied:
                    applied.append(rule.name)
                result = handler(flow)
                if result is not None:
                    await result


class ScenariosBeforeGuards:
    """Runs the Scenarios' `before_guards` actions (Origin swaps) right after the
    Origin decoder, so the guards judge a swapped Origin like any other."""

    def __init__(self, scenarios):
        self.scenarios = scenarios

    async def requestheaders(self, flow):
        await self.scenarios.before_guards(flow)
