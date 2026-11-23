# Changelog

Notable changes to roxy, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/); the version is the plugin's, in `.claude-plugin/plugin.json`, and each release is tagged `v<version>`.

## [Unreleased]

### Added

- `roxy setup` fills the settings root for this Mac and can run again any time, keeping what is there: it generates the mitmweb password (and with `--cloud` the lab secret, checking `rce`, its token and `cloudflared`), never printing a secret; allows this Mac in `lan_subnets` (`--trusted-network`: its whole subnet); takes the Roku developer login, the password from a hidden prompt or stdin, never a flag; and, in a terminal, offers the Rokus it finds to register. Without a terminal it never prompts, so an agent can run it. Values the examples seeded are replaced.
- `roxy device add | list | remove | discover` register Target Devices without editing JSON: `add NAME --ip IP` a Roku, `--proxied` a Proxied Device, `--rce DEVICE_NAME [--slug SLUG]` a Cloud Device. `add` allows the IP in `lan_subnets` as a `/32` when needed and `remove` drops it, never a wider subnet; `discover` lists the Rokus on the network with a ready `add` line for each new one.
- The `roxy` skill registers devices with `roxy device` and hands the Roku password to the user.

### Changed

- `./install.sh` seeds no made-up devices or `lan_subnets`: `devices.json` is empty, `lan_subnets` too, and it points at `roxy setup`. `settings.example/` stays as documentation.
- `roxy start` also refuses an empty device list, and names each missing setting with the command that fills it in. The README quickstart's settings step is `roxy setup`, then `roxy device add` or `discover`.
- `roxy start` stops before mitmweb starts when a port it listens on is in use, naming each busy port, its role and the process holding it (Troubleshooting).

- Mobile Devices are now Proxied Devices: any device that is not a Roku (phone, tablet, Android TV, Google TV, Fire TV, Apple TV, console, computer) goes through Proxy Routing. `devices.json` registers one with `"kind": "proxied"`; `"kind": "mobile"` from 0.2.0 still counts. The how-to moved to `docs/proxied-devices.md`, with a section for TV boxes (Apple TV unverified), and the glossary lint now flags the old name. <!-- glossary-ok: names the old term -->

## [0.2.0] - 2026-11-23

Mobile Devices through Proxy Routing, and the docs reorganised around a one-path quickstart. <!-- glossary-ok: released text keeps its words -->

### Added

- Proxy Routing, for Mobile Devices: a Product App's iOS and Android debug builds set the lab's new Proxy Routing listener (port 8090, always on) as their HTTP proxy and trust the lab's CA from `http://mitm.it`. Their flows keep their Origin URLs, unrewritten, and the active Scenarios act on them; the LAN guards apply. `roxy start` and `roxy status` print `Proxy Routing: <mac-ip>:8090`, and `roxy status --json` gains `proxy_routing_port`. How-to: `docs/mobile-devices.md`. <!-- glossary-ok: released text keeps its words -->
- A Mobile Device is registered in `devices.json` with `"kind": "mobile"`, which names its flows; `scripts/deploy`, `roxy launch` and `roxy console` refuse it as not a Roku. <!-- glossary-ok: released text keeps its words -->
- An iOS Simulator or Android Emulator on the lab's Mac goes through Proxy Routing from loopback, allowed on that listener only, and its flows are named `This Mac`.
- `scripts/check docs`: every relative link and `#anchor` in the Markdown resolves, and this changelog has a section for the plugin's version.
- `docs/troubleshooting.md`: symptom, cause and fix for every known failure, the `X-Lab-Blocked` refusals first.
- `scripts/deploy --help`; `scripts/grid --help` lists every flavour, Target Device kind and traffic class.
- GitHub issue forms: a bug report that asks for `roxy status --json` and warns against pasting secrets, Recordings or HAR files; security reports go to private reporting.

### Changed

- The README is a landing page with a one-path quickstart, starting with a Prefixed URL sent from the Mac; every other section moved to a page in `docs/`, indexed by kind in `docs/README.md`.
- The `roxy` skill reaches `docs/` through one link, points to the new pages, and knows Mobile Devices and Proxy Routing. <!-- glossary-ok: released text keeps its words -->

### Fixed

- `roxy` reaches the lab past any proxy set for the Mac (its web proxies, `http_proxy`): its calls to mitmweb and to cloudflared's metrics on `127.0.0.1` never go through one.

## [0.1.0] - 2026-11-22

The first release: a mitmproxy/mitmweb lab on the Mac for the Outbound Traffic of Roku Lab Apps and Product Apps, on Physical Devices and Cloud Devices.

### Added

- Prefix Routing on every Target Device, in the lab's `/` form and the Charles-style `/;` form (port 8888), and CA Routing on Physical Devices.
- A Public Endpoint for Cloud Devices through a Cloudflare quick tunnel, behind a secret path segment, the RCE egress IPs and an Origin allowlist.
- Guards: allowed clients, public Origin addresses only (DNS rebinding safe), refusals marked in mitmweb with an `X-Lab-Blocked` reason.
- Header and body rewriting (HLS, DASH, JSON, VAST/XML, optional text) so follow-up requests come back through the lab.
- Scenarios: named Manipulation rules (status, latency, shared or per-request throttle, drop, header, body, `map_local`, `map_remote`, manifest edits), several active at once, with `{proxy_base}` placeholders and per-rule flow counts in `roxy status --since`.
- App Profiles in the settings root: per Product App Scenarios, Origin allowlist, text rewriting and a fallback Origin.
- The `roxy` CLI: `start`, `status`, `scenario`, `launch`, `console`, `flows --json`, `export --har`, `app`.
- Recordings of every Lab Session, offline replay, and HAR export with the lab secret redacted.
- Two Lab Apps (classic BrightScript/SceneGraph and RSG 2.0) and the grid runner, single cells or batches, on Physical and Cloud Devices.
- The kit for wiring your own apps, Docker Compose, per-user locks, and the `roxy` skill as a Claude Code plugin.

[Unreleased]: https://github.com/oscarsanchez/roxy/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/oscarsanchez/roxy/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/oscarsanchez/roxy/releases/tag/v0.1.0
