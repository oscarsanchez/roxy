"""App Profiles: what the lab keeps for each Product App, in the user's settings root and
never in a repo. The one place that knows their layout:

    <settings root>/apps/<name>/profile.json   {"repo": "<git root>", "origin_allowlist": [...]}
        optional key: "rewrite_text": true turns the text body format on for the app
        optional key: "fallback_origin": {"path": "<regex>", "origin": "https://host"}
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


class FallbackOrigin(NamedTuple):
    """The Origin for a request that names none (a bare path on a LAN listener), when its
    path matches `path`."""

    path: re.Pattern
    origin: str  # scheme://host[:port]

    def origin_url(self, path):
        """The Origin URL for the bare request PATH (path and query, as received), or None
        if the regex finds no match in its path."""
        return f"{self.origin}{path}" if self.path.search(path.split("?", 1)[0]) else None


class Profile(NamedTuple):
    repo: Path
    origin_allowlist: list
    scenarios_dir: Path
    file: Path  # its profile.json, where the user edits origin_allowlist
    rewrite_text: bool  # the text body format is on for this app
    fallback_origin: FallbackOrigin | None  # None: profile.json names none


NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
ORIGIN = re.compile(r"https?://[A-Za-z0-9.-]+(?::[0-9]+)?")


def _fallback_origin(value):
    """profile.json's fallback_origin as a FallbackOrigin (None if absent). Raises
    ValueError saying what is wrong with it."""
    if value is None:
        return None
    if not (isinstance(value, dict) and isinstance(value.get("path"), str) and isinstance(value.get("origin"), str)):
        raise ValueError('fallback_origin must be {"path": "<regex>", "origin": "https://host"}')
    try:
        path = re.compile(value["path"])
    except re.error as e:
        raise ValueError(f"fallback_origin path is not a regex ({e})") from e
    if not ORIGIN.fullmatch(value["origin"]):
        raise ValueError(f"fallback_origin origin must be http(s)://host[:port], not {value['origin']!r}")
    return FallbackOrigin(path, value["origin"])


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
            rewrite_text = doc.get("rewrite_text", False)
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise BadProfile(f"App Profile {name!r} in {file}: {e!r}") from e
        if not isinstance(allowlist, list) or not all(isinstance(host, str) for host in allowlist):
            raise BadProfile(f"App Profile {name!r}: origin_allowlist must be a list of hosts, in {file}")
        if not isinstance(rewrite_text, bool):
            raise BadProfile(f"App Profile {name!r}: rewrite_text must be true or false, in {file}")
        try:
            fallback = _fallback_origin(doc.get("fallback_origin"))
        except ValueError as e:
            raise BadProfile(f"App Profile {name!r}: {e}, in {file}") from e
        return Profile(repo, allowlist, self._folder(name) / "scenarios", file, rewrite_text, fallback)

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
