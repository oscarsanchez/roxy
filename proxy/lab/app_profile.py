"""The App Profile loaded for this session, if any (lab.app_profiles keeps them): one
Product App's Public Endpoint allowlist, fallback Origin, Scenarios and mocks.

`roxy start` sets `lab_app` to the profile's name (empty for none). Its allowlist and
Scenarios join the lab's own; a change to profile.json takes a restart.
"""

from mitmproxy import ctx
from mitmproxy.exceptions import OptionsError

from lab.app_profiles import AppProfileError, AppProfiles
from lab.config import settings_root
from lab.scenarios import DEFAULT_SCENARIOS_DIR


class AppProfile:
    def __init__(self):
        self.origin_allowlist = []
        self.fallback_origin = None  # a FallbackOrigin, or None
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
            self.origin_allowlist, self.fallback_origin, self.scenarios_dir = [], None, None
            return
        try:
            profile = AppProfiles(settings_root(), DEFAULT_SCENARIOS_DIR).profile(name)
        except AppProfileError as e:
            raise OptionsError(str(e)) from e
        self.origin_allowlist, self.fallback_origin, self.scenarios_dir = (
            profile.origin_allowlist, profile.fallback_origin, profile.scenarios_dir
        )
