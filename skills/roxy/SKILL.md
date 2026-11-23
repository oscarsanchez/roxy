---
name: roxy
description: Use for a Roku app's network traffic through the roxy lab (mitmproxy) - seeing what the app requested, making an API or other Origin fail, slow down or answer from a mock (Scenarios), App Profiles, registering Target Devices and setting roxy up (roxy device, roxy setup), and routing an app through the lab (Proxy Base, Charles hook, the kit). Also the same app's debug build on a phone, tablet, TV box, iOS Simulator or Android Emulator (Proxied Devices, Proxy Routing).
---

# roxy: see and change a Roku app's traffic

roxy is a mitmproxy lab on the user's Mac. A Roku app that sends its Outbound Traffic through it can be read request by request (`roxy flows --json`) and manipulated by Scenarios: an Origin fails, slows down or answers from a mock. Every flag: `roxy <subcommand> --help`. Every doc, by kind: [docs/README.md](docs/README.md). Wiring an app: [Prefix Routing guide](docs/prefix-routing.md), [CA Routing guide](docs/ca-routing.md).

`roxy` comes from the user's roxy checkout, whose `./install.sh` links it into `~/.local/bin`; without it, ask the user to run that. Paths the guides name (such as `kit/`) are in that checkout: `realpath "$(command -v roxy)"` prints `<checkout>/bin/roxy`.

Words: a **Target Device** is the device running the app: a Roku, either a Physical Device (on the LAN) or a Cloud Device (Roku Cloud Emulator, billed per Run: the `rce` skill), or a **Proxied Device** (any device that is not a Roku: an iPhone, iPad, Android device, Android TV or Fire TV box, Apple TV, iOS Simulator or Android Emulator running the app's debug build for it). An **Origin** is the real server a request is for. The **Proxy Base** is the lab address the app puts in front of each Origin URL, making a **Prefixed URL**. An **App Profile** keeps one app's Scenarios and mocks in the user's roxy settings, outside every repo.

## Workflow

1. **Lab up for this app.** `roxy status`.
   - Up, with this app's profile on its `App Profile:` line: use that lab. Another profile: ask the user before going on, since a lab loads one App Profile per session and switching means stopping theirs.
   - Down: `roxy app list` (each profile and its repo). No profile whose repo is this repo: `roxy app new <name>` from inside it, once. Then `roxy start` from inside the repo, which loads that profile (`--app <name>` names it from elsewhere); add `--tunnel` for a Cloud Device. It runs in the foreground until Ctrl-C, so run it in the background, keep it for the session, and poll `roxy status` until it is up.
   - `roxy start` refusing over a missing setting (a secret, empty `lan_subnets`) names each with the command that fills it in: `roxy setup` or `roxy device` (Settings, below). No Target Devices is only a warning: the lab still serves This Mac's own clients.

   Done when `roxy status` prints `lab: up` and `App Profile: <this app's profile>`.
2. **App routed.** A Roku app's requests reach the lab only as Prefixed URLs (a Proxied Device: Proxied Devices, below). Find how this app does it: a Charles hook (a debug proxy setting in a sideloaded build, on port 8888; the user types the `Proxy IP` from `roxy status` into the app), the kit (`RoxyUrl` or `prefixedUrl` in the source, built with `bs_const=roxy_kit=true` or `ROXY_KIT=1`), or neither, and then the Prefix Routing guide wires one in. roxy never builds or sideloads an app: build and sideload it with the app's own tooling, as its repo does, then launch it with roxy.
3. **Launch.** `roxy launch [--scenario NAME]... "<device>" [key=value...]`, with a device name from `devices.json` in the settings root. It relaunches the sideloaded dev channel with the `proxyBase` launch param (the kit reads it; a Charles hook ignores it) and prints `run=<id>`: keep the id, for either kind of app.
4. **Read the flows.** `roxy flows --json --since <run id>`. Done when every request you expected is in the output, or its absence is explained (Reading flows).

## Settings: Target Devices and setup

The user's settings live in the settings root (`~/.config/roxy/`, or `$ROXY_CONFIG_DIR`). Change them through `roxy device` and `roxy setup`, never by editing its files, and never read `secrets.env`. Every flag: [Settings](docs/settings.md#setup).

- `roxy device list`: each Target Device, its IP or rce Device Name, and its kind. `roxy device discover`: the Rokus on this network, with a ready `roxy device add` line for each one not registered (none found: the Roku may be off or elsewhere, or a VPN or the network keeps the search from it; a Roku shows its IP in Settings → Network → About).
- `roxy device add "<name>" --ip <ip>` registers a Roku; `--proxied` any other device (phone, tablet, TV box); `roxy device add "<name>" --rce <rce Device Name> [--slug <slug>]` a Cloud Device. It allows the IP in `lan_subnets` when needed, and warns, still registering it, when the device does not answer. `roxy device remove "<name>"` unregisters one; a Roku whose IP changed is removed, then added again.
- `roxy setup` without a terminal never prompts and never reads stdin: it generates the mitmweb password, allows this Mac in `lan_subnets` and removes the examples' devices; `--cloud` adds the lab secret and checks `rce` and `cloudflared`. It never prints a secret. `--trusted-network` allows the whole subnet: only when the user says the network is theirs, such as home.
- The Roku developer password is the user's to enter. When setup warns `no Roku developer password`, ask the user to run `roxy setup` in their own terminal (a hidden prompt); never ask for it in the chat or put it on a command line. The same goes for the RCE token (`rce token set`).
- A change that changed something ends `restart the lab if it is running (roxy start), to use the change`: a running lab reads devices and `lan_subnets` when it starts. Ask the user before restarting their lab.

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
- Each rule takes exactly one action: `status`, `latency`, `throttle`, `drop`, `header`, `body`, `map_local` (a mock: `map_local = "mocks/catalog.json"` answers from `scenarios/mocks/catalog.json`), `map_remote`, or a manifest edit. Syntax and behaviour of each: [Scenarios](docs/scenarios.md). Every matching rule applies, in file order.
- Activate: `roxy scenario set <scenario> [<scenario>...]` (replaces the active ones), `roxy scenario add <scenario>`, or `roxy launch --scenario <scenario> ...` (repeatable). Several can be active: their rules apply in that order, then file order. It applies from the next request on, with no lab restart. Editing an active file reloads it on the next request; a broken edit is logged and that Scenario's last good rules stay, so confirm in the flows.
- Done when `roxy status --since <run id>` after a fresh launch shows a count of flows for every rule you meant to act, none flagged `(acted on nothing yet)` (a filter that matches nothing fails silently), and those flows list it in `scenario_rules`. Then `roxy scenario remove <scenario>` (or `clear` for all): active Scenarios apply to every Target Device on the lab.

## Reading flows

`roxy flows --json [--filter EXPR] [--since RUN|TIME] [--limit N]` prints one JSON array, oldest first (`--since` also takes an ISO 8601 time, such as `2026-11-20T10:00:00Z`); field by field: [Flows for agents](docs/agent-setup.md#flows-for-agents).

- `url` is the Origin URL, never the Prefixed URL.
- `status` null: no response (dropped, or the connection failed).
- `refusal` set: the lab refused it with a 403 or 400. `origin-host`: a Cloud Device request to a host off the allowlist; add it to `origin_allowlist` in the App Profile's `profile.json` and restart the lab. `origin-address`: the Origin resolves to a private address. `not-prefixed`: the request was not a Prefixed URL. `client-ip`, `secret-segment`: the client or the Public Endpoint secret was wrong.
- `scenario_rules`: the active Scenarios' rules that acted on it, each named `<scenario>/<rule>`.
- `double_prefixed` true: the app put the Proxy Base in front of a URL twice; the lab unwrapped it and served the real Origin, so the flow worked. Tell the user to report it to the app's developer: the app's "already prefixed?" check misses URLs that already carry the Proxy Base ([Troubleshooting](docs/troubleshooting.md#a-flow-is-marked-double-prefixed)).
- A request missing from the output went straight to its Origin: it was built outside the Charles hook or the kit (Prefix Routing guide, What the lab never sees).
- Lab down: it says so and exits non-zero.

## Proxied Devices: the app's debug build on a phone, tablet or TV box

A Proxied Device reaches the lab by **Proxy Routing**: it sets the lab as its HTTP proxy (the `Proxy Routing:` address in `roxy status`) and trusts the lab's CA from `http://mitm.it`. That setup is the user's, on the device: [Proxied Devices](docs/proxied-devices.md).

- Its flows keep their Origin URLs, never rewritten. `device` in `roxy flows --json` is its registered name (`roxy device add "<name>" --ip <ip> --proxied`, which also allows its IP in `lan_subnets`), or `This Mac` for an iOS Simulator or Android Emulator on the Mac; `null` for an unregistered Proxied Device.
- Read one device's flows: `roxy flows --json --filter '~comment "<name>"' --since <ISO time>`. There is no run id: roxy never launches an app on a Proxied Device, so note the time before the user opens it.
- Target it in a Scenario with `~comment "<name>"` in the filter (`~comment "Phone" & ~d api.example.com`); a filter on the Origin alone (`~d api.example.com`) acts on the Roku's and the Proxied Device's requests alike. Rules with `{proxy_base}` placeholders leave its flows alone.
- `scripts/deploy`, `roxy launch` and `roxy console` are Roku-only: they refuse a Proxied Device with "not a Roku". The user runs the app with its own tooling.
- No HTTPS flows, or TLS errors: the device does not trust the CA, an Android build ignores user CAs, or the app pins its certificates (out of scope). A `throttle` leaves its HTTP/2 flows unpaced. Fixes: [Troubleshooting](docs/troubleshooting.md).

## Checking the lab itself: the grid

Only when the user asks whether the lab still works with its own Lab Apps. In the roxy checkout, with the lab started there, `scripts/grid <flavours> <device-kinds> <traffic-classes>` fills grid cells and prints a pass, fail or known-limit row for each. Each of the three takes one value, a comma list or `all` (`scripts/grid classic,rsg physical all`), and `--separator '/,/;'` runs each cell in both Prefixed URL forms. A batch ends with a table and a count, and exits 1 if any cell failed. Cloud Device cells bill: the grid prints their projected cost and asks once, so confirm with the user first. Full reference: [Grid runner](docs/grid.md).

## A HAR file for a person or another tool

Every Lab Session is saved as a Recording (a `.mitm` file). `roxy export --har [RECORDING] [--filter EXPR] [-o FILE]` writes one as a HAR file, for browser devtools, HAR viewers or a bug report: without RECORDING, the newest of all; without `-o`, `./<recording name>.har`. It reads the file only (the lab up or down) and never writes over an existing file. For your own reading, `roxy flows --json` stays the tool.

- Request URLs are Origin URLs; response bodies are as the Target Device received them, so URLs inside them are Prefixed URLs.
- The lab secret becomes `<secret>`, but the app's own headers, cookies and tokens stay in the file: check it, and tell the user so, before it is shared.

## When something fails

A refusal (`X-Lab-Blocked`), a Scenario that acted on nothing, a missing result line, a held lock: find the symptom in [Troubleshooting](docs/troubleshooting.md) and suggest its fix.

## Known limits

- One lab per user: one App Profile per session and one set of active Scenarios, lab-wide. Deploys and launches take a per-user `devices` lock and refuse while someone else holds it, naming the holder; set `LAB_LOCK_OWNER` to your name, and `LAB_LOCK_WAIT=1` waits instead.
- A Charles hook builds `http://<ip>:8888/;` only, so such an app goes through the lab on Physical Devices only. Cloud Devices need the kit (or a hook that takes a whole Proxy Base) and `roxy start --tunnel`, whose hostname changes on every start: launch again after a restart.
- `roxy status` and `roxy start` show the public Proxy Base as `https://<tunnel-host>/<secret>`, keeping the lab's secret out of your transcript; `roxy launch` and the grid send the real one. `roxy status --show-secret` prints it whole: only for a user pasting it into a Cloud Device by hand, never to read it yourself.
- The lab never sees Roku OS traffic, SDKs with their own fixed endpoints, or DRM and ad requests the app does not route.
- CA Routing (no Prefixed URLs; DNS on the user's router) is for Physical Devices only, and needs router setup by the user: [CA Routing guide](docs/ca-routing.md).
- `roxy flows` is read-only. Holding and editing a flow by hand is the user's, in mitmweb (`http://127.0.0.1:8081`, password-protected).
