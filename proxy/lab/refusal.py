"""How the lab answers a request itself instead of forwarding it to an Origin."""

from mitmproxy import http


def refuse(flow, status, reason):
    """Answer the client with `status` and a reason header; mark the flow in mitmweb."""
    flow.response = http.Response.make(
        status, f"lab refused: {reason}\n", {"X-Lab-Blocked": reason, "Content-Type": "text/plain"}
    )
    flow.marked = ":no_entry:"
    flow.metadata["lab_refusal"] = [status, reason]


def refused(flow):
    """True if the lab answered this flow with refuse(). The X-Lab-Blocked header is
    for the client and the grid; an Origin or a scenario rule can send it too."""
    return "lab_refusal" in flow.metadata


class KeepRefusals:
    """A refused request stays refused. mitmproxy's server replay runs after the
    lab chain and answers in the request hook, over a refusal; put it back
    before any response hook runs."""

    def responseheaders(self, flow):
        if refused(flow) and flow.is_replay == "response":
            refuse(flow, *flow.metadata["lab_refusal"])
            flow.is_replay = None
