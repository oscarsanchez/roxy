"""Scenarios: named files of Manipulation rules, any number of them active lab-wide.

A scenario is `<lab_scenarios_dir>/<name>.toml`, a list of rules:

    [[rule]]
    name = "httpbin json fails"
    filter = "~d httpbin.org & ~u /json"   # mitmproxy filter expression
    status = 503                           # exactly one action (see scenario_actions)

Set `lab_scenario` (mitmweb options, `--set`, or the options API) to switch
scenarios without a restart: the active ones in order, comma-separated (`a,b`);
empty means none. Their rules apply in that order, then file order. Each active
file is reloaded when it changes. The loaded App Profile's Scenarios (lab.app_profile) join the
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
    """The Scenario rules that acted on this flow, as `<scenario>/<rule>`, in the order they first did."""
    return flow.metadata.get("lab_scenario_rules", [])


def show_applied_rules(flow):
    """Show in mitmweb the Scenario rules that acted on this flow: after its comment (the
    device label), as `<device> | <scenario>/<rule>, ...`, and a marker unless it has one
    (a refusal keeps its own)."""
    applied = applied_rules(flow)
    if not applied:
        return
    flow.metadata.setdefault("lab_comment_before_rules", flow.comment)
    flow.comment = " | ".join(filter(None, [comment_before_rules(flow), ", ".join(applied)]))
    flow.marked = flow.marked or ":test_tube:"


def comment_before_rules(flow):
    """The flow's comment without the rules show_applied_rules added: its device label."""
    return flow.metadata.get("lab_comment_before_rules", flow.comment)


def scenario_names(value):
    """The active Scenarios' names, in order, from a `lab_scenario` value."""
    return [name.strip() for name in value.split(",") if name.strip()]


def scenario_value(names):
    """The `lab_scenario` value that makes NAMES the active Scenarios, in order."""
    return ",".join(names)


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


class ActiveScenario:
    """One active Scenario: its file and its last good rules, reloaded when the file changes."""

    def __init__(self, name, path):
        self.name, self.path = name, path
        self.mtime, self.rules = path.stat().st_mtime_ns, load_scenario(path)

    def reload_if_changed(self):
        """Pick up edits to the file. A broken edit keeps the last good rules."""
        try:
            mtime = self.path.stat().st_mtime_ns
            if mtime == self.mtime:
                return
            self.mtime = mtime  # report a broken edit once, not on every flow
            self.rules = load_scenario(self.path)
            logging.info(f"lab scenario {self.name!r} reloaded: {len(self.rules)} rule(s)")
        except (ValueError, OSError) as e:
            logging.error(f"lab scenario {self.name!r} not reloaded, keeping its last good rules: {e}")


class Scenarios:
    def __init__(self, app_profile):
        self.app_profile = app_profile
        self.active = []  # ActiveScenario, in set order

    def load(self, loader):
        loader.add_option(
            "lab_scenario", str, "",
            "Active lab scenarios, in order: file names without .toml, comma-separated; empty for none.",
        )
        loader.add_option("lab_scenarios_dir", str, str(DEFAULT_SCENARIOS_DIR), "Directory of lab scenario files.")

    def configure(self, updated):
        if not {"lab_scenario", "lab_scenarios_dir", "lab_app"} & updated:
            return
        # A Scenario that stays active keeps its rules, even after a broken edit, unless
        # where Scenarios are found changed.
        kept = {} if {"lab_scenarios_dir", "lab_app"} & updated else {s.name: s for s in self.active}
        profile = self.app_profile.profile
        names = scenario_names(ctx.options.lab_scenario)
        active = []
        for name in names:
            try:
                if names.count(name) > 1:
                    raise ValueError("listed more than once")
                active.append(kept.get(name) or ActiveScenario(
                    name, find_scenario(name, profile and profile.scenarios_dir, Path(ctx.options.lab_scenarios_dir))
                ))
            except (ValueError, OSError) as e:
                raise exceptions.OptionsError(f"scenario {name!r}: {e}") from e
        self.active = active
        for scenario in active:
            logging.info(f"lab scenario {scenario.name!r} active: {len(scenario.rules)} rule(s)")

    async def before_guards(self, flow):
        """Called by ScenariosBeforeGuards, the first of this addon's hooks per flow."""
        for scenario in self.active:
            scenario.reload_if_changed()  # once per flow, so a flow sees one version
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
        if not refused(flow):  # a guard's answer must stay visible
            await self._apply(hook, flow)
        if hook != "before_guards":  # by now the device labels have named the flow
            show_applied_rules(flow)

    async def _apply(self, hook, flow):
        for scenario in self.active:
            for rule in scenario.rules:
                handler = getattr(rule.action, hook, None)
                if handler and rule.matches(flow):
                    applied, named = flow.metadata.setdefault("lab_scenario_rules", []), f"{scenario.name}/{rule.name}"
                    if named not in applied:
                        applied.append(named)
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
