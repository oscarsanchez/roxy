"""roxy: the lab's mitmproxy addon chain."""

from lab.app_profile import AppProfile
from lab.body_rewriting import BodyRewriter
from lab.device_labels import DeviceLabels
from lab.guards import Guards
from lab.origin_decoder import OriginDecoder
from lab.refusal import KeepRefusals
from lab.request_headers import RequestHeaderCleanup
from lab.response_headers import ResponseHeaderRewriter
from lab.scenarios import Scenarios, ScenariosBeforeGuards


def addon_chain():
    """Fresh lab addon instances, in hook order."""
    app_profile = AppProfile()
    guards = Guards(app_profile)
    scenarios = Scenarios(app_profile)
    return [
        app_profile,  # first: the others read the loaded profile when they configure
        OriginDecoder(app_profile),
        ScenariosBeforeGuards(scenarios),  # Origin swaps (map_remote), judged by the guards
        DeviceLabels(guards),  # before the guards: refused flows are labelled too
        guards,
        KeepRefusals(),  # before the response rewriters
        RequestHeaderCleanup(),
        ResponseHeaderRewriter(),
        BodyRewriter(app_profile),
        scenarios,  # keep last: its actions see the response as the client gets it
    ]
