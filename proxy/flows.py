"""roxy flows --json: a mitmweb flow dump (stdin) as the JSON shape the README documents
(Flows for agents), one object per flow, oldest first.
Usage (from proxy/): uv run python flows.py [--since RUN|TIME] < DUMP
"""

import argparse
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


def since(value):
    """A roxy launch run id (the launch time in Unix seconds, then random digits), or an
    ISO 8601 time (local time without an offset). Returns Unix seconds."""
    if value.isdigit():
        return int(value[:10])
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a run id or a time like 2026-11-20T10:00:00Z: {value!r}")


def main():
    parser = argparse.ArgumentParser(prog="roxy flows")
    parser.add_argument("--since", type=since, default=0)
    args = parser.parse_args()
    flows = [
        f for f in io.FlowReader(sys.stdin.buffer).stream()
        if isinstance(f, http.HTTPFlow) and f.timestamp_created >= args.since
    ]
    print("[" + ",\n".join(json.dumps(summary(f)) for f in flows) + "]")


if __name__ == "__main__":
    main()
