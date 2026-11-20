"""Scenario actions: what a matching scenario rule does to a flow.

ACTIONS maps a rule's action key to a factory `(value, scenario_dir) -> action`.
An action has any of the mitmproxy hook methods `requestheaders`, `request`,
`responseheaders`, `response` (sync or async); the Scenarios addon calls them
only for flows that match the rule's filter. Factories raise ValueError for a
bad value. To add an action, add a factory here.

The Scenarios addon is last in the lab's addon chain, so response actions see
the body after the lab's body rewriting (Prefixed URLs), as the client gets it.
"""

import asyncio
import re
from pathlib import Path

from mitmproxy import flowfilter, http
from mitmproxy.addons.maplocal import MapLocal, MapLocalSpec
from mitmproxy.addons.modifybody import ModifyBody
from mitmproxy.addons.modifyheaders import ModifyHeaders, ModifySpec

from lab.manifest_edits import ACTIONS as MANIFEST_EDITS


ALL = flowfilter.match_all  # the rule's own filter has already matched


def builtin(addon_class, spec):
    """A mitmproxy built-in addon (map_local, modify_*) running one spec."""
    addon = addon_class()
    addon.replacements = [spec]
    return addon


def table(value, action, keys):
    if not isinstance(value, dict) or set(value) != set(keys) or not all(isinstance(v, str) for v in value.values()):
        raise ValueError(f"{action} must be {{ {' = ..., '.join(keys)} = ... }} of strings")
    return [value[k] for k in keys]


def header_replace(value, scenario_dir):
    """Built-in modify_headers: replace a header (an empty value removes it).
    Applies to the request or the response, whichever the filter matches."""
    name, header_value = table(value, "header", ("name", "value"))
    return builtin(ModifyHeaders, ModifySpec(ALL, name.encode(), header_value))


def body_replace(value, scenario_dir):
    """Built-in modify_body: regex replace in the request or response body."""
    pattern, replacement = table(value, "body", ("pattern", "replacement"))
    subject = pattern.encode()  # TOML already has escapes; regex backslashes stay single
    try:
        re.compile(subject)
    except re.error as e:
        raise ValueError(f"body pattern {pattern!r}: {e}") from e
    return builtin(ModifyBody, ModifySpec(ALL, subject, replacement))


def map_local(value, scenario_dir):
    """Built-in map_local: answer from a file (path relative to the scenario
    file) without reaching the Origin. A directory maps by URL path."""
    if not isinstance(value, str):
        raise ValueError(f"map_local must be a path, got {value!r}")
    path = (Path(scenario_dir) / value).resolve()
    if not path.exists():
        raise ValueError(f"map_local file not found: {path}")
    return builtin(MapLocal, MapLocalSpec(ALL, r"^\w+://[^/]+", path))


class Latency:
    """Delay the request before it reaches the Origin (other flows carry on)."""

    def __init__(self, seconds, scenario_dir):
        if type(seconds) not in (int, float) or seconds < 0:
            raise ValueError(f"latency must be seconds >= 0, got {seconds!r}")
        self.seconds = seconds

    async def request(self, flow):
        await asyncio.sleep(self.seconds)


class Drop:
    """Close the client connection without an answer and without reaching the Origin."""

    def __init__(self, value, scenario_dir):
        if value is not True:
            raise ValueError(f"drop must be true, got {value!r}")

    def request(self, flow):
        if flow.killable:
            flow.kill()


class StatusOverride:
    def __init__(self, status, scenario_dir):
        if type(status) is not int or not 100 <= status <= 599:
            raise ValueError(f"status must be an HTTP status code, got {status!r}")
        self.status = status

    def response(self, flow):
        flow.response.status_code = self.status
        flow.response.reason = http.status_codes.RESPONSES.get(self.status, "")


ACTIONS = {
    "status": StatusOverride,
    "latency": Latency,
    "drop": Drop,
    "header": header_replace,
    "body": body_replace,
    "map_local": map_local,
    **MANIFEST_EDITS,
}
