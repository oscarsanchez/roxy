"""The running Lab Session, through mitmweb's API: its state, its active Scenarios, its
flows and the flows each active Scenario rule acted on, for bin/roxy and scripts/launch (through proxy/cli.py).

LabSession talks to mitmweb through a transport: get(path) and put(path, json), each
returning (HTTP status, body bytes) and raising LabDown when nothing answers, or
LabSessionError when the lab's refusal answers in mitmweb's stead.
HttpTransport is the running lab's; tests use one in memory.
"""

import json
import random
import time
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import NamedTuple
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from mitmproxy import http, io

from lab.prefixed_url import double_prefixed
from lab.refusal import refusal_reason
from lab.scenarios import applied_rules, find_scenario, load_scenario, scenario_names, scenario_value
from lab.target_devices import target_device
from lab.throttle import paced_seconds

RUN_ID_TIME_DIGITS = 10  # a run id starts with the launch time in Unix seconds


class LabSessionError(Exception):
    """A request the running lab could not answer; the message says why, for the user."""


class LabDown(LabSessionError):
    """Nothing answers on mitmweb's API."""


class WrongPassword(LabSessionError):
    """mitmweb refused the password LabSession signs in with."""


class ScenarioRefused(LabSessionError):
    """The active Scenarios could not change as asked (mitmweb refused, or the Scenario to
    remove is not active); the message has the reason."""


class BadFilter(LabSessionError):
    """mitmweb refused a filter expression for the flows."""


class LabState(NamedTuple):
    app: str | None  # the loaded App Profile
    scenarios: list  # the active Scenarios' names, in order
    ca_routing: bool  # whether the lab is in CA Routing
    proxy_routing_port: int  # the Proxy Routing listener's port, 0 for none
    scenarios_dir: str  # the folder of the lab's own Scenarios


class RuleFlows(NamedTuple):
    scenario: str
    rule: str
    flows: int  # how many of the lab's flows the rule acted on


class ScenarioRules(NamedTuple):
    scenario: str  # an active Scenario's name
    rules: list  # RuleFlows, in file order; empty when its file does not load
    error: str | None  # why its file does not load, else None


class HttpTransport:
    """The running lab's mitmweb API, on this Mac's 127.0.0.1:PORT, signed in with PASSWORD.
    It never goes through a proxy: with the Mac's web proxies (or http_proxy) pointed at
    the lab's Proxy Routing listener, the lab would refuse the call (origin-address)."""

    def __init__(self, port, password):
        self.url = f"http://127.0.0.1:{port}"
        self.password = password
        self.opener = build_opener(ProxyHandler({}))

    def get(self, path):
        return self._call(Request(f"{self.url}/{path}"))

    def put(self, path, json_body):
        # A non-GET mitmweb API call needs a matching XSRF cookie and header (any value).
        headers = {"Content-Type": "application/json", "Cookie": "_mitmproxy_xsrf=lab", "X-XSRFToken": "lab"}
        return self._call(Request(f"{self.url}/{path}", json.dumps(json_body).encode(), headers, method="PUT"))

    def _call(self, request):
        request.add_header("Authorization", f"Bearer {self.password}")
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, response.read()
        except HTTPError as e:
            if reason := e.headers.get("X-Lab-Blocked"):  # not mitmweb: the lab's proxy refused the call
                raise LabSessionError(f"the lab refused the call to {self.url} ({reason}), not mitmweb") from e
            return e.code, e.read()
        except OSError as e:  # URLError included: nothing answers
            raise LabDown(f"nothing answers on {self.url}: {e}") from e


class LabSession:
    def __init__(self, transport):
        self.transport = transport

    def state(self):
        status, body = self.transport.get("options.json")
        _check_password(status)
        options = json.loads(body)
        return LabState(
            app=options["lab_app"]["value"] or None,
            scenarios=scenario_names(options["lab_scenario"]["value"]),
            ca_routing=options["lab_ca_routing"]["value"],
            # 0 (no listener) from a lab started before Proxy Routing existed
            proxy_routing_port=options.get("lab_proxy_routing_port", {"value": 0})["value"],
            scenarios_dir=options["lab_scenarios_dir"]["value"],
        )

    def set_scenarios(self, names):
        """Make NAMES the active Scenarios, lab-wide, in that order; none (or '') clears them.
        Returns the active Scenarios."""
        value = scenario_value(names)
        status, body = self.transport.put("options", {"lab_scenario": value})
        _check_password(status)
        if status != 200:
            raise ScenarioRefused(f"mitmweb refused the Scenarios {value!r}: {body.decode(errors='replace')}")
        return scenario_names(value)

    def add_scenario(self, name):
        """Make NAME active too, after the active ones; an active NAME stays where it is.
        Returns the active Scenarios."""
        active = self.state().scenarios
        return active if name in active else self.set_scenarios([*active, name])

    def remove_scenario(self, name):
        """Stop NAME's rules, leaving the other active Scenarios in their order. Returns the
        active Scenarios."""
        active = self.state().scenarios
        if name not in active:
            raise ScenarioRefused(f"{name!r} is not active (active: {', '.join(active) or 'none'})")
        return self.set_scenarios([other for other in active if other != name])

    def flows(self, filter=None, since=None, limit=None):
        """The lab's flows, oldest first, each summed up in the shape docs/agent-setup.md documents
        (Flows for agents). FILTER: a mitmproxy filter expression, which mitmweb applies;
        then SINCE (Unix seconds, parse_since) drops older flows, and LIMIT keeps the last
        LIMIT. Read-only: it never holds or edits a flow."""
        status, body = self.transport.get("flows/dump" + (f"?filter={quote(filter, safe='')}" if filter else ""))
        _check_password(status)
        if status == 400:
            raise BadFilter(f"mitmweb refused the filter expression {filter!r}: {body.decode(errors='replace')}")
        flows = [
            f for f in io.FlowReader(BytesIO(body)).stream()
            if isinstance(f, http.HTTPFlow) and f.timestamp_created >= (since or 0)
        ]
        return [_summary(f) for f in flows[-limit if limit else None:]]

    def scenario_rules(self, state, app_scenarios_dir, since=None):
        """Each Scenario active in STATE (the lab's state()), in order, with its rules and how
        many flows each acted on (the flows' scenario_rules, SINCE as for flows), so a rule
        that acted on none shows. The counts come from the marked flows: a flow someone
        unmarks by hand in mitmweb drops out, which shows as a false "acted on nothing yet",
        never as a silent pass. Its file is found as the lab finds it (find_scenario):
        APP_SCENARIOS_DIR, the loaded App Profile's Scenarios (None without one), else the
        lab's own."""
        if not state.scenarios:  # no flows to fetch: a long session's dump, bodies and all, is large
            return []
        # Only the marked flows: every flow a rule acted on is marked (target_devices.annotate),
        # and the rest of a long session never comes back with its bodies.
        acted = Counter(rule for flow in self.flows(filter="~marked", since=since) for rule in flow["scenario_rules"])
        found = []
        for scenario in state.scenarios:
            try:
                rules = load_scenario(find_scenario(scenario, app_scenarios_dir, Path(state.scenarios_dir)))
            except (ValueError, OSError) as e:
                found.append(ScenarioRules(scenario, [], str(e)))
                continue
            found.append(ScenarioRules(scenario, [
                RuleFlows(scenario, rule.name, acted[f"{scenario}/{rule.name}"]) for rule in rules
            ], None))
        return found


def new_run_id():
    """A fresh roxy launch run id: the launch time in Unix seconds, then random digits."""
    return f"{int(time.time())}{random.randrange(32768)}"


def parse_since(value):
    """A roxy launch run id (new_run_id), or an ISO 8601 time (local time without an
    offset), as Unix seconds. Raises ValueError for anything else."""
    if value.isdigit():
        return int(value[:RUN_ID_TIME_DIGITS])
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        raise ValueError(f"not a run id or a time like 2026-11-20T10:00:00Z: {value!r}") from None


def _summary(flow):
    response = flow.response
    return {
        "id": flow.id,
        "time": datetime.fromtimestamp(flow.timestamp_created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "device": _device_name(flow),
        "method": flow.request.method,
        "url": flow.request.url,  # the Origin URL: the Origin decoder points the request at it
        "status": response and response.status_code,
        "request_bytes": _size(flow.request),
        "response_bytes": _size(response),
        "duration_ms": response and response.timestamp_end and _duration_ms(flow),
        "refusal": refusal_reason(flow),
        "scenario_rules": applied_rules(flow),
        "double_prefixed": double_prefixed(flow),
    }


def _device_name(flow):
    """The name of the flow's Target Device, None when nothing names it."""
    device = target_device(flow)
    return device and device.name


def _size(message):
    return None if message is None or message.raw_content is None else len(message.raw_content)


def _duration_ms(flow):
    """From the request to the response's last byte at the client, which a throttled
    response reaches after mitmproxy has it whole."""
    end = flow.response.timestamp_end + paced_seconds(flow)
    return round((end - flow.request.timestamp_start) * 1000)


def _check_password(status):
    if status in (401, 403):
        raise WrongPassword("mitmweb refused the password: check MITMWEB_PASSWORD in secrets.env")
