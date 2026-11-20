"""App Profiles: what the lab keeps for each Product App, in the user's settings root and
never in a repo. The one place that knows their layout:

    <settings root>/apps/<name>/profile.json   {"repo": "<git root>", "origin_allowlist": [...]}
    <settings root>/apps/<name>/scenarios/     its Scenarios, with their mocks next to them
"""

import json
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

from lab.scenarios import find_scenario


class AppProfileError(Exception):
    """A request about App Profiles the lab refuses; the message says why, for the user."""


class AppProfileExists(AppProfileError):
    pass


class NotInGitRepo(AppProfileError):
    pass


class UnknownAppProfile(AppProfileError):
    pass


class BadProfile(AppProfileError):
    pass


class BadAppProfileName(AppProfileError):
    pass


class ScenarioInBoth(AppProfileError):
    """A Scenario name in both the App Profile's Scenarios and the lab's: refused, never
    one picked silently."""


class Profile(NamedTuple):
    repo: Path
    origin_allowlist: list
    scenarios_dir: Path


NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class AppProfiles:
    def __init__(self, settings_root, lab_scenarios_dir):
        self.apps_dir = Path(settings_root) / "apps"
        self.lab_scenarios_dir = Path(lab_scenarios_dir)

    def new(self, name, cwd):
        """Create the App Profile NAME for the git repo holding CWD."""
        if not NAME.fullmatch(name):
            raise BadAppProfileName(f"an App Profile name is letters, digits, '.', '_' and '-': {name!r}")
        folder = self._folder(name)
        if folder.exists():
            raise AppProfileExists(f"the App Profile {name!r} already exists, in {folder}")
        found = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
        if found.returncode:
            raise NotInGitRepo("run roxy app new inside the app's git repo")
        repo = Path(found.stdout.strip()).resolve()
        (folder / "scenarios").mkdir(parents=True)
        self._file(name).write_text(
            json.dumps({"repo": str(repo), "origin_allowlist": []}, indent=2) + "\n"
        )
        return self.profile(name)

    def resolve(self, name=None, *, cwd):
        """The App Profile to load: NAME, else the one whose repo holds CWD (the deepest,
        for nested repos), else None."""
        if name:
            if not self._file(name).is_file():
                raise UnknownAppProfile(f"unknown App Profile {name!r} (roxy app list shows them)")
            return name
        here = Path(cwd).resolve()
        repos = {app: self.profile(app).repo for app in self.profiles()}
        holding = [app for app, repo in repos.items() if here.is_relative_to(repo)]
        return max(holding, key=lambda app: len(repos[app].parts), default=None)

    def profiles(self):
        """The names of the App Profiles, sorted."""
        return sorted(path.parent.name for path in self.apps_dir.glob("*/profile.json"))

    def profile(self, name):
        file = self._file(name)
        try:
            doc = json.loads(file.read_text())
            repo, allowlist = Path(doc["repo"]), doc["origin_allowlist"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise BadProfile(f"App Profile {name!r} in {file}: {e!r}") from e
        if not isinstance(allowlist, list) or not all(isinstance(host, str) for host in allowlist):
            raise BadProfile(f"App Profile {name!r}: origin_allowlist must be a list of hosts, in {file}")
        return Profile(repo, allowlist, self._folder(name) / "scenarios")

    def scenarios(self, app):
        """Every Scenario App Profile APP (None: no profile) sees, as (name, source): the
        profile's, then the lab's own, each name once. A name in both has, as its source,
        the ScenarioInBoth that refuses it."""
        found = {}
        for folder in (app and self.profile(app).scenarios_dir, self.lab_scenarios_dir):
            for path in sorted(folder.glob("*.toml")) if folder else []:
                if path.stem not in found:
                    try:
                        found[path.stem] = self.source(app, path.stem)
                    except ScenarioInBoth as e:
                        found[path.stem] = e
        return list(found.items())

    def source(self, app, scenario):
        """Where SCENARIO comes from for App Profile APP (None: no profile): 'App Profile
        APP' or 'lab'. Raises ScenarioInBoth for a name in both."""
        app_dir = app and self.profile(app).scenarios_dir
        try:
            found = find_scenario(scenario, app_dir, self.lab_scenarios_dir)
        except ValueError as e:
            raise ScenarioInBoth(str(e)) from e
        return f"App Profile {app}" if found.parent == app_dir else "lab"

    def _folder(self, name):
        return self.apps_dir / name

    def _file(self, name):
        return self._folder(name) / "profile.json"
