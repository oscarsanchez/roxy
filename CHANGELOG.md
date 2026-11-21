# Changelog

Notable changes to roxy, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/); the version is the plugin's, in `.claude-plugin/plugin.json`, and each release is tagged `v<version>`.

## [Unreleased]

### Added

- `scripts/check docs`: every relative link and `#anchor` in the Markdown resolves, and this changelog has a section for the plugin's version.

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

[Unreleased]: https://github.com/oscarsanchez/roxy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/oscarsanchez/roxy/releases/tag/v0.1.0
