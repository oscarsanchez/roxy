"""roxy flows --json: a mitmweb flow dump (stdin) as the JSON shape the README documents
(Flows for agents), one object per flow, oldest first.
Usage (from proxy/): uv run python flows.py < DUMP
"""

import json
import sys
from datetime import UTC, datetime

from mitmproxy import http, io

from lab.refusal import refusal_reason
from lab.scenarios import applied_rules


def size(message):
    return None if message is None or message.raw_content is None else len(message.raw_content)


def summary(flow):
    response = flow.response
    return {
        "id": flow.id,
        "time": datetime.fromtimestamp(flow.timestamp_created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "device": flow.comment or None,  # the lab's device label
        "method": flow.request.method,
        "url": flow.request.url,  # the Origin URL: the Origin decoder points the request at it
        "status": response and response.status_code,
        "request_bytes": size(flow.request),
        "response_bytes": size(response),
        "duration_ms": response and response.timestamp_end and round((response.timestamp_end - flow.request.timestamp_start) * 1000),
        "refusal": refusal_reason(flow),
        "scenario_rules": applied_rules(flow),
    }


def main():
    flows = [f for f in io.FlowReader(sys.stdin.buffer).stream() if isinstance(f, http.HTTPFlow)]
    print("[" + ",\n".join(json.dumps(summary(f)) for f in flows) + "]")


if __name__ == "__main__":
    main()
