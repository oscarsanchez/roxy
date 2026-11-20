"""roxy: the lab's mitmproxy addon chain."""

from lab.body_rewriting import BodyRewriter
from lab.device_labels import DeviceLabels
from lab.guards import Guards
from lab.origin_decoder import OriginDecoder
from lab.refusal import KeepRefusals
from lab.request_headers import RequestHeaderCleanup
from lab.response_headers import ResponseHeaderRewriter
from lab.scenarios import Scenarios


def addon_chain():
    """Fresh lab addon instances, in hook order."""
    guards = Guards()
    return [
        OriginDecoder(),
        DeviceLabels(guards),  # before the guards: refused flows are labelled too
        guards,
        KeepRefusals(),  # before the response rewriters
        RequestHeaderCleanup(),
        ResponseHeaderRewriter(),
        BodyRewriter(),
        Scenarios(),  # keep last: its actions see the response as the client gets it
    ]
