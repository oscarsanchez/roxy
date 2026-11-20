---
name: roxy
description: Use for a Roku app's network traffic through the roxy lab (mitmproxy) - seeing what the app requested, making an API or other Origin fail, slow down or answer from a mock (Scenarios), App Profiles, and routing an app through the lab (Proxy Base, Charles hook, the kit).
---

# roxy: see and change a Roku app's traffic

roxy is a mitmproxy lab on the user's Mac. A Roku app that sends its Outbound Traffic through it can be read request by request (`roxy flows --json`) and manipulated by Scenarios: an Origin fails, slows down or answers from a mock. Every flag: `roxy <subcommand> --help`. Full reference: [README.md](README.md). Wiring an app: [Prefix Routing guide](prefix-routing.md), [CA Routing guide](ca-routing.md).

`roxy` comes from the user's roxy checkout, whose `./install.sh` links it into `~/.local/bin`; without it, ask the user to run that. Paths the guides name (such as `kit/`) are in that checkout: `realpath "$(command -v roxy)"` prints `<checkout>/bin/roxy`.

Words: a **Target Device** is the Roku running the app, a Physical Device (on the LAN) or a Cloud Device (Roku Cloud Emulator, billed per Run: the `rce` skill). An **Origin** is the real server a request is for. The **Proxy Base** is the lab address the app puts in front of each Origin URL, making a **Prefixed URL**. An **App Profile** keeps one app's Scenarios and mocks in the user's roxy settings, outside every repo.

## Workflow

1. **Lab up for this app.** `roxy status`.
   - Up, with this app's profile on its `App Profile:` line: use that lab. Another profile: ask the user before going on, since a lab loads one App Profile per session and switching means stopping theirs.
   - Down: `roxy app list` (each profile and its repo). No profile whose repo is this repo: `roxy app new <name>` from inside it, once. Then `roxy start` from inside the repo, which loads that profile (`--app <name>` names it from elsewhere); add `--tunnel` for a Cloud Device. It runs in the foreground until Ctrl-C, so run it in the background, keep it for the session, and poll `roxy status` until it is up.
   - `roxy start` refusing over a missing setting (`secrets.env`, `devices.json`, `lan_subnets`) names the file; those are the user's to fill in, in the settings root (`~/.config/roxy/`, or `$ROXY_CONFIG_DIR`).

   Done when `roxy status` prints `lab: up` and `App Profile: <this app's profile>`.
2. **App routed.** Only requests sent to a Prefixed URL reach the lab. Find how this app does it: a Charles hook (a debug proxy setting in a sideloaded build, on port 8888; the user types the `Proxy IP` from `roxy status` into the app), the kit (`RoxyUrl` or `prefixedUrl` in the source, built with `bs_const=roxy_kit=true` or `ROXY_KIT=1`), or neither, and then the Prefix Routing guide wires one in. roxy never builds or sideloads an app: build and sideload it with the app's own tooling, as its repo does, then launch it with roxy.
3. **Launch.** `roxy launch [--scenario NAME]... "<device>" [key=value...]`, with a device name from `devices.json` in the settings root. It relaunches the sideloaded dev channel with the `proxyBase` launch param (the kit reads it; a Charles hook ignores it) and prints `run=<id>`: keep the id, for either kind of app.
4. **Read the flows.** `roxy flows --json --since <run id>`. Done when every request you expected is in the output, or its absence is explained (Reading flows).

## Scenarios: make an Origin fail, slow down or answer from a mock

A Scenario is a TOML file of rules, named by its file name without `.toml`. This app's live in its App Profile, `<settings root>/apps/<profile>/scenarios/<scenario>.toml` (`roxy app new` prints the folder). `roxy scenario list` shows them beside the lab's own; a name in both stops `roxy start`.

```toml
[[rule]]
name = "catalog fails"                          # shows in flows' scenario_rules
filter = "~d api.example.com & ~u /catalog"     # mitmproxy filter expression: ~d host, ~u URL regex, ~m method, ~q request, ~s response
status = 503
```

- `throttle = { kbps = N }` caps everything the rule matches for one Target Device at N kbps together (parallel range requests share N); `throttle = { kbps = N, per = "request" }` caps each response on its own. Downloads only, latency per request (a `latency` rule), no packet loss or fluctuation, unlike Charles's Throttle; HTTP/1 only.
- Filters see the Origin URL. `status` replaces the status of the Origin's response (the Origin is still contacted); `drop` closes the connection without contacting it.
- Each rule takes exactly one action: `status`, `latency`, `throttle`, `drop`, `header`, `body`, `map_local` (a mock: `map_local = "mocks/catalog.json"` answers from `scenarios/mocks/catalog.json`), `map_remote`, or a manifest edit. Syntax and behaviour of each: README, 5. Scenarios. Every matching rule applies, in file order.
- Activate: `roxy scenario set <scenario> [<scenario>...]` (replaces the active ones), `roxy scenario add <scenario>`, or `roxy launch --scenario <scenario> ...` (repeatable). Several can be active: their rules apply in that order, then file order. It applies from the next request on, with no lab restart. Editing an active file reloads it on the next request; a broken edit is logged and that Scenario's last good rules stay, so confirm in the flows.
- Done when the flows of a fresh launch list your rule in `scenario_rules`. Then `roxy scenario remove <scenario>` (or `clear` for all): active Scenarios apply to every Target Device on the lab.

## Reading flows

`roxy flows --json [--filter EXPR] [--since RUN|TIME] [--limit N]` prints one JSON array, oldest first (`--since` also takes an ISO 8601 time, such as `2026-11-20T10:00:00Z`); field by field: README, Flows for agents.

- `url` is the Origin URL, never the Prefixed URL.
- `status` null: no response (dropped, or the connection failed).
- `refusal` set: the lab refused it with a 403 or 400. `origin-host`: a Cloud Device request to a host off the allowlist; add it to `origin_allowlist` in the App Profile's `profile.json` and restart the lab. `origin-address`: the Origin resolves to a private address. `not-prefixed`: the request was not a Prefixed URL. `client-ip`, `secret-segment`: the client or the Public Endpoint secret was wrong.
- `scenario_rules`: the active Scenarios' rules that acted on it, each named `<scenario>/<rule>`.
- A request missing from the output went straight to its Origin: it was built outside the Charles hook or the kit (Prefix Routing guide, What the lab never sees).
- Lab down: it says so and exits non-zero.

## Known limits

- One lab per user: one App Profile per session and one set of active Scenarios, lab-wide. Deploys and launches take a per-user `devices` lock and refuse while someone else holds it, naming the holder; set `LAB_LOCK_OWNER` to your name, and `LAB_LOCK_WAIT=1` waits instead.
- A Charles hook builds `http://<ip>:8888/;` only, so such an app goes through the lab on Physical Devices only. Cloud Devices need the kit (or a hook that takes a whole Proxy Base) and `roxy start --tunnel`, whose hostname changes on every start: launch again after a restart.
- The lab never sees Roku OS traffic, SDKs with their own fixed endpoints, or DRM and ad requests the app does not route.
- CA Routing (no Prefixed URLs; DNS on the user's router) is for Physical Devices only, and needs router setup by the user: [CA Routing guide](ca-routing.md).
- `roxy flows` is read-only. Holding and editing a flow by hand is the user's, in mitmweb (`http://127.0.0.1:8081`, password-protected).
