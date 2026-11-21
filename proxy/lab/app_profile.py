"""The App Profile loaded for this session, if any (lab.app_profiles keeps them): one
Product App's Public Endpoint allowlist, fallback Origin, Scenarios and mocks, and
whether its text bodies are rewritten.

`roxy start` sets `lab_app` to the profile's name (empty for none). The other addons ask
this one what the loaded profile says, and get the no-profile answer when none is loaded;
they join its allowlist and Scenarios with the lab's own. A change to profile.json takes a
restart.
"""

from mitmproxy import ctx
from mitmproxy.exceptions import OptionsError

from lab.app_profiles import AppProfileError, AppProfiles
from lab.config import settings_root
from lab.scenarios import DEFAULT_SCENARIOS_DIR


class AppProfile:
    def __init__(self):
        self._profile = None  # the loaded Profile; None: no profile loaded

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
            self._profile = None
            return
        try:
            self._profile = AppProfiles(settings_root(), DEFAULT_SCENARIOS_DIR).profile(name)
        except AppProfileError as e:
            raise OptionsError(str(e)) from e

    @property
    def origin_allowlist(self):
        """The profile's Public Endpoint allowlist, without the lab's own ([] with no profile)."""
        return self._profile.origin_allowlist if self._profile else []

    def fallback_origin_url(self, path):
        """The Origin URL the profile's fallback Origin gives the bare request PATH, or None:
        no profile, no fallback Origin, or a path its regex does not match."""
        fallback = self._profile and self._profile.fallback_origin
        return fallback.origin_url(path) if fallback else None

    @property
    def rewrites_text(self):
        """Whether the profile turns the opt-in text body format on (False with no profile)."""
        return bool(self._profile and self._profile.rewrite_text)

    @property
    def scenarios_dir(self):
        """The folder of the profile's Scenarios, or None with no profile."""
        return self._profile.scenarios_dir if self._profile else None
