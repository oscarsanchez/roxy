"""Scenario actions: what a matching scenario rule does to a flow.

ACTIONS maps a rule's action key to a factory `(value, scenario_dir) -> action`.
Every factory takes `scenario_dir`, used or not, so the registry keeps one call
shape (map_local resolves its file against it).
An action has any of the mitmproxy hook methods `requestheaders`, `request`,
`responseheaders`, `response` (sync or async), or the lab's own
`before_guards`; the Scenarios addon calls them only for flows that match the
rule's filter. Factories raise ValueError for a bad value. To add an action,
add a factory here.

The Scenarios addon is last in the lab's addon chain, so response actions see
the body after the lab's body rewriting (Prefixed URLs), as the client gets it.
`before_guards` runs right after the Origin decoder instead, so the guards
judge the request the Origin will actually get.
"""

import re
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

from mitmproxy import flowfilter, http
from mitmproxy.addons.maplocal import MapLocal, MapLocalSpec
from mitmproxy.addons.modifybody import ModifyBody
from mitmproxy.addons.modifyheaders import ModifyHeaders, ModifySpec

from lab import clock
from lab.manifest_edits import ACTIONS as MANIFEST_EDITS
from lab.prefixed_url import client_proxy_base
from lab.throttle import Throttle


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


# Placeholders in a `body` or `header` replacement, filled from the client that made
# the flow: `{name}`, a name of lowercase letters and underscores. Braces keep them
# clear of regex replacement syntax (`\1`, `\g<1>`) and of the backslash escapes
# modify_body and modify_headers read in a replacement. A `{name}` not listed here is refused.
CLIENT_PLACEHOLDERS = {
    "proxy_base": lambda proxy_base, separator: proxy_base,
    "proxy_base_no_scheme": lambda proxy_base, separator: proxy_base.partition("://")[2],
    "separator": lambda proxy_base, separator: separator,
}
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _braced(names):
    return ", ".join(f"{{{name}}}" for name in names)


class ForClient:
    """A built-in modify_* addon (modify_body, modify_headers) with its replacement's
    placeholders filled per flow: a built-in's spec is fixed, with no per-flow context.

    A flow that was not Prefixed (CA Routing) has no Proxy Base to fill in: a
    replacement with placeholders leaves it alone."""

    def __init__(self, addon_class, subject, replacement):
        unknown = sorted(set(_PLACEHOLDER.findall(replacement)) - set(CLIENT_PLACEHOLDERS))
        if unknown:
            raise ValueError(f"unknown placeholder {_braced(unknown)} (known: {_braced(CLIENT_PLACEHOLDERS)})")
        self.addon_class, self.subject, self.replacement = addon_class, subject, replacement
        for hook in ("requestheaders", "request", "responseheaders", "response"):
            if hasattr(addon_class, hook):  # only the built-in's own hooks, so Scenarios calls only those
                setattr(self, hook, partial(self.run, hook))

    def run(self, hook, flow):
        replacement = self.replacement
        if _PLACEHOLDER.search(replacement):
            client = client_proxy_base(flow)
            if client is None:
                return
            replacement = _PLACEHOLDER.sub(lambda m: CLIENT_PLACEHOLDERS[m[1]](*client), replacement)
        getattr(builtin(self.addon_class, ModifySpec(ALL, self.subject, replacement)), hook)(flow)


def header_replace(value, scenario_dir):
    """Built-in modify_headers: replace a header (an empty value removes it), with
    client placeholders in the value. Applies to the request or the response,
    whichever the filter matches."""
    name, header_value = table(value, "header", ("name", "value"))
    return ForClient(ModifyHeaders, name.encode(), header_value)


def body_replace(value, scenario_dir):
    """Built-in modify_body: regex replace in the request or response body,
    with client placeholders in the replacement."""
    pattern, replacement = table(value, "body", ("pattern", "replacement"))
    subject = pattern.encode()  # TOML already has escapes; regex backslashes stay single
    try:
        re.compile(subject)
    except re.error as e:
        raise ValueError(f"body pattern {pattern!r}: {e}") from e
    return ForClient(ModifyBody, subject, replacement)


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
        await clock.sleep(self.seconds)


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


class MapRemote:
    """Send the request to another Origin, `<scheme>://<host>[:port]`. Path and
    query are kept, and Host follows."""

    def __init__(self, target, scenario_dir):
        if not isinstance(target, str):
            raise ValueError(f"map_remote must be <scheme>://<host>[:port], got {target!r}")
        parts = urlsplit(target)
        try:
            parts.port  # ValueError when out of range
        except ValueError as e:
            raise ValueError(f"map_remote {target!r}: {e}") from e
        if (
            parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc
            or target != f"{parts.scheme}://{parts.netloc}"  # no path, query or fragment
        ):
            raise ValueError(f"map_remote must be <scheme>://<host>[:port], got {target!r}")
        self.target = target

    def before_guards(self, flow):
        flow.request.url = f"{self.target}{flow.request.path}"


ACTIONS = {
    "status": StatusOverride,
    "latency": Latency,
    "throttle": Throttle,
    "drop": Drop,
    "header": header_replace,
    "body": body_replace,
    "map_local": map_local,
    "map_remote": MapRemote,
    **MANIFEST_EDITS,
}
