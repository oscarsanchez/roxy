"""A grid cell's verdict from its two runs. Pure: no devices, no network.

Oracles (spec, Testing Decisions, Seam B): the lab's recorded flows and the Lab App's
result line `LABRESULT <case> run=<id> <key>=<value>...` from the debug console.
"""

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from urllib.parse import urlsplit


@dataclass
class Cell:
    """One grid cell: Lab App flavour x Target Device kind x traffic class, as in cells.toml."""

    flavour: str
    device_kind: str
    traffic_class: str
    case: str
    scenario: str
    expect_hosts: list[str]
    ok: dict[str, str]
    known_limit: str = ""
    ca_routing: bool = False  # a Physical Device in CA Routing: the Lab App calls Origin URLs directly
    separator: str = "/"  # the Lab App's Prefixed URL form: "/" (the lab's own) or "/;" (Charles-style)


@dataclass
class Run:
    """One launch of the Lab App: its result line (None if none came), the flows the lab
    recorded from the Target Device meanwhile, and the console output meanwhile."""

    result: str | None
    flows: list[dict] = field(default_factory=list)
    console: str = ""


@dataclass
class Verdict:
    outcome: str  # pass | fail | known-limit
    reason: str


DEVICE_KINDS = {"physical": "Physical Device", "cloud": "Cloud Device"}


def setup(device_kind: str, ca_routing: bool) -> str:
    """The key cells.toml uses for a cell's Target Device and known limits: the device kind,
    or `ca-routing` for a Physical Device in CA Routing."""
    return "ca-routing" if ca_routing else device_kind


def cell_from_config(config: dict, flavour: str, device_kind: str, traffic_class: str, ca_routing: bool) -> Cell:
    """A cell as cells.toml defines it. A CA Routing cell leaves out the Prefix Routing
    oracles from ok and takes the flavour's `ca-routing` known limit."""
    spec = config["classes"][traffic_class]
    ok = spec["ok"]
    if ca_routing:
        ok = {k: v for k, v in ok.items() if k not in config["prefix_routing_fields"]}
    return Cell(
        flavour=flavour, device_kind=device_kind, traffic_class=traffic_class,
        case=spec["case"], scenario=spec["scenario"], expect_hosts=spec["expect_hosts"], ok=ok,
        known_limit=spec.get("known_limits", {}).get(f"{flavour}.{setup(device_kind, ca_routing)}", ""), ca_routing=ca_routing,
    )


def row(cell: Cell, verdict: Verdict) -> str:
    """The cell as a row of the evaluation grid (Markdown)."""
    device = DEVICE_KINDS[cell.device_kind] + (" (CA Routing)" if cell.ca_routing else "")
    device += f" ({cell.separator} form)" if cell.separator != "/" else ""
    cols = [cell.flavour, device, cell.traffic_class, verdict.outcome, verdict.reason]
    return "| " + " | ".join(c.replace("|", "\\|") for c in cols) + " |"


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def plain(console: str) -> str:
    """Console text without colour codes (the RSG 2.0 console colours every line)."""
    return ANSI.sub("", console)


def result_line(console: str, case: str, run_id: str) -> str | None:
    """This launch's result line. The console replays earlier output on connect, so only
    the run id tells this launch's line apart. A line counts once its \\n has arrived.
    Text may precede it: RSG 2.0 prints `[timestamp]: LABRESULT ...`."""
    head = f"LABRESULT {case} run={run_id}"
    for line in plain(console).split("\n")[:-1]:
        line = line.strip()
        at = line.find(head)
        if at >= 0 and line[at + len(head):at + len(head) + 1] in ("", " "):
            return line[at:]
    return None


def device_flows(flows: list[dict], device: str, start: float, end: float) -> list[dict]:
    """The flows (mitmweb /flows.json entries) the Target Device named `device` started
    in [start, end): the lab's device label (the flow comment) names it, natively and
    under Compose alike."""
    return [f for f in flows if start <= f["request"]["timestamp_start"] < end and f.get("comment") == device]


def fields(result: str) -> dict[str, str]:
    """The key=value fields of a result line, without the per-launch run id."""
    pairs = (token.partition("=") for token in result.split()[2:])
    return {k: v for k, _, v in pairs if k != "run"}


def describe(f: dict[str, str]) -> str:
    return " ".join(f"{k}={v}" for k, v in f.items())


CRASH_MARKERS = ("BrightScript Debugger>", "runtime error")


def missing_result(r: Run) -> str:
    if any(marker in r.console for marker in CRASH_MARKERS):
        return "the Lab App crashed (BrightScript Debugger on the console)"
    return "no result line before the timeout"


def judge(cell: Cell, baseline: Run, manipulated: Run, proxy_base: str) -> Verdict:
    """pass, fail or known-limit for a cell, from its run without a scenario (baseline)
    and its run with the cell's Manipulation scenario."""
    verdict = check(cell, baseline, manipulated, proxy_base)
    if verdict.outcome == "fail" and cell.known_limit:
        return Verdict("known-limit", f"{cell.known_limit} (observed: {verdict.reason})")
    return verdict


# An absolute URL on the console. Lines end in \r\n; URLs stop at whitespace or quotes.
URL = re.compile(r"https?://[^\s\"'<>]+")
# An XML namespace declaration (xmlns="..." / xmlns:x="...", quotes maybe escaped, as in
# RAF's VAST log): its URL is a name, never fetched.
XMLNS = re.compile(r"""xmlns(?::[\w.-]+)?=\\?["'][^"'\\]*""")
# The fetches RAF's debug output names: `getStringFromUrl("<url>") = "<body>"`, `fireBeacon("<url>")`.
RAF_FETCH = re.compile(r'(?:getStringFromUrl|fireBeacon)\("([^"]*)"')


def console_leaks(cell: Cell, r: Run, proxy_base: str) -> list[str]:
    """URLs the Lab App (or Roku OS) printed that went to an Origin directly. The console
    only shows what something chose to print. In Prefix Routing that is every URL that is
    not a Prefixed URL. In CA Routing every URL is an Origin URL, so it is one whose host
    the lab never saw in that run: DNS did not send it to the lab."""
    text = XMLNS.sub("", plain(r.console))
    if cell.ca_routing:
        # Bodies stay Origin URLs in CA Routing, so of RAF's lines only the fetches it
        # names count: the rest print response bodies and ad structures (a VAST icon,
        # a companion banner) that a TV never loads. In Prefix Routing such a URL would
        # show one the body rewriter missed, so there every URL counts.
        urls = [u for line in text.split("\n")
                for u in (RAF_FETCH.findall(line) if "[RAF" in line else URL.findall(line))]
        seen = hosts(r.flows)
        return [u for u in urls if urlsplit(u).hostname not in seen]
    return [u for u in URL.findall(text) if not u.startswith(proxy_base + "/")]


def check(cell: Cell, baseline: Run, manipulated: Run, proxy_base: str) -> Verdict:
    runs = {"without a scenario": baseline, f"with {cell.scenario}": manipulated}
    problems = [
        f"leak: the console {name} names {url}"
        for name, r in runs.items()
        for url in console_leaks(cell, r, proxy_base)
    ]
    silent = [f"{name}: {missing_result(r)}" for name, r in runs.items() if r.result is None]
    if silent:
        return Verdict("fail", "; ".join(silent + problems))
    before, after = fields(baseline.result), fields(manipulated.result)

    succeeded = all(before.get(k) == v for k, v in cell.ok.items())
    if not succeeded:
        problems.append(f"without a scenario the Lab App did not succeed (wants {describe(cell.ok)}): {describe(before)}")

    for f in refused(baseline.flows):
        problems.append(f"the lab refused {f['request']['host']}{f['request']['path']} ({blocked_reason(f)})")

    seen = hosts(baseline.flows)
    for pattern in cell.expect_hosts:
        if not any(fnmatch(host, pattern) for host in seen):
            # The Lab App got its content, so it came from somewhere other than the lab.
            problems.append(f"{'leak: ' if succeeded else ''}{pattern} never reached the lab")

    changed = {k: v for k, v in after.items() if before.get(k) != v}
    if not changed:
        problems.append(f"{cell.scenario} did not change the result: {describe(after)}")

    if problems:
        return Verdict("fail", "; ".join(problems))
    was = {k: before.get(k, "") for k in changed}
    return Verdict("pass", f"{cell.scenario} changed the result: {describe(was)} -> {describe(changed)}")


def blocked_reason(flow: dict) -> str | None:
    """The lab's own refusal reason (X-Lab-Blocked), None for a flow it forwarded."""
    headers = (flow.get("response") or {}).get("headers") or []
    return next((v for k, v in headers if k.lower() == "x-lab-blocked"), None)


def refused(flows: list[dict]) -> list[dict]:
    return [f for f in flows if blocked_reason(f)]


def hosts(flows: list[dict]) -> set[str]:
    """Origin hosts of the flows the lab forwarded (the decoder sets request.host to the Origin)."""
    return {f["request"]["host"] for f in flows if not blocked_reason(f)}
