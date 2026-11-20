"""The App Profile loaded for this session, if any: one Product App's Public Endpoint
allowlist, Scenarios and mocks, kept in the user's settings root and never in a repo.

    <settings root>/apps/<name>/profile.json   {"repo": "<git root>", "origin_allowlist": [...]}
    <settings root>/apps/<name>/scenarios/     its Scenarios, with their mocks next to them

`roxy start` sets `lab_app` to the profile's name (empty for none). Its allowlist and
Scenarios join the lab's own; a change to profile.json takes a restart.
"""

import json

from mitmproxy import ctx
from mitmproxy.exceptions import OptionsError

from lab.config import settings_root


class AppProfile:
    def __init__(self):
        self.origin_allowlist = []
        self.scenarios_dir = None  # None: no profile loaded

    def load(self, loader):
        loader.add_option(
            "lab_app", str, "",
            "The loaded App Profile (a folder name in the settings root's apps/); empty for none.",
        )

    def configure(self, updated):
        if "lab_app" not in updated:
            return
        name = ctx.options.lab_app
        if not name:
            self.origin_allowlist, self.scenarios_dir = [], None
            return
        folder = settings_root() / "apps" / name
        try:
            allowlist = json.loads((folder / "profile.json").read_text())["origin_allowlist"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise OptionsError(f"App Profile {name!r} in {folder}: {e!r}") from e
        if not isinstance(allowlist, list) or not all(isinstance(host, str) for host in allowlist):
            raise OptionsError(f"App Profile {name!r}: origin_allowlist must be a list of hosts")
        self.origin_allowlist, self.scenarios_dir = allowlist, folder / "scenarios"
