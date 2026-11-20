"""The running Lab Session, through mitmweb's API: its state, its active Scenario and its
flows, for bin/roxy and scripts/launch (through proxy/cli.py).

LabSession talks to mitmweb through a transport: get(path) and put(path, json), each
returning (HTTP status, body bytes) and raising only LabDown when nothing answers.
HttpTransport is the running lab's; tests use one in memory.
"""

import json
import random
import time
from datetime import UTC, datetime
from io import BytesIO
from typing import NamedTuple
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mitmproxy import http, io

from lab.refusal import refusal_reason
from lab.scenarios import applied_rules
from lab.throttle import paced_seconds

RUN_ID_TIME_DIGITS = 10  # a run id starts with the launch time in Unix seconds


class LabSessionError(Exception):
    """A request the running lab could not answer; the message says why, for the user."""


class LabDown(LabSessionError):
    """Nothing answers on mitmweb's API."""


class WrongPassword(LabSessionError):
    """mitmweb refused the password LabSession signs in with."""


class ScenarioRefused(LabSessionError):
    """mitmweb refused to make a Scenario the active one; the message has its reason."""


class BadFilter(LabSessionError):
    """mitmweb refused a filter expression for the flows."""


class LabState(NamedTuple):
    app: str | None  # the loaded App Profile
    scenario: str | None  # the active Scenario


class HttpTransport:
    """The running lab's mitmweb API, on this Mac's 127.0.0.1:PORT, signed in with PASSWORD."""

    def __init__(self, port, password):
        self.url = f"http://127.0.0.1:{port}"
        self.password = password

    def get(self, path):
        return self._call(Request(f"{self.url}/{path}"))

    def put(self, path, json_body):
        # A non-GET mitmweb API call needs a matching XSRF cookie and header (any value).
        headers = {"Content-Type": "application/json", "Cookie": "_mitmproxy_xsrf=lab", "X-XSRFToken": "lab"}
        return self._call(Request(f"{self.url}/{path}", json.dumps(json_body).encode(), headers, method="PUT"))

    def _call(self, request):
        request.add_header("Authorization", f"Bearer {self.password}")
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except HTTPError as e:
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
        return LabState(options["lab_app"]["value"] or None, options["lab_scenario"]["value"] or None)

    def set_scenario(self, name):
        """Make NAME the active Scenario, lab-wide; '' clears it."""
        status, body = self.transport.put("options", {"lab_scenario": name})
        _check_password(status)
        if status != 200:
            raise ScenarioRefused(f"mitmweb refused scenario {name!r}: {body.decode(errors='replace')}")

    def flows(self, filter=None, since=None, limit=None):
        """The lab's flows, oldest first, each summed up in the shape the README documents
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
        "device": flow.comment or None,  # the lab's device label
        "method": flow.request.method,
        "url": flow.request.url,  # the Origin URL: the Origin decoder points the request at it
        "status": response and response.status_code,
        "request_bytes": _size(flow.request),
        "response_bytes": _size(response),
        "duration_ms": response and response.timestamp_end and _duration_ms(flow),
        "refusal": refusal_reason(flow),
        "scenario_rules": applied_rules(flow),
    }


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
