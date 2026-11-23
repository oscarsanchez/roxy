# roxy docs

New to roxy? Start with the [Quickstart](../README.md#quickstart). Vocabulary: [GLOSSARY.md](../GLOSSARY.md). Every command's options: `roxy <subcommand> --help`, `scripts/grid --help`.

## How-to

- [Troubleshooting](troubleshooting.md): symptom, cause and fix, refusal by refusal.
- [Prefix Routing guide](prefix-routing.md): wire an app, with its Charles hook or with the kit.
- [CA Routing guide](ca-routing.md): route by DNS and the lab's CA instead, Physical Devices only.
- [Cloud Devices](cloud-devices.md): run an app on Roku Cloud Emulator through the Public Endpoint.
- [Mobile Devices](mobile-devices.md): see an iOS or Android debug build's traffic through Proxy Routing.
- [Scenarios](scenarios.md): make an Origin fail, slow down, answer from a mock, or edit a manifest.
- [Recordings](recordings.md): replay a Lab Session offline, or export it as a HAR file.
- [Agents](agent-setup.md): give Claude Code or Cursor the lab, and read its flows as JSON.
- [Grid runner](grid.md): check the lab against its Lab Apps on Target Devices.
- [Docker Compose](compose.md): run the lab without installing Python or cloudflared.

## Reference

- [Settings and App Profiles](settings.md): the settings root, its files, and per-app profiles.
- [Lab Apps](lab-apps.md): cases and result lines of the two Lab Apps.
- [Guards](guards.md): what the lab refuses, and why.
- [Header and body rewriting](rewriting.md): which URLs become Prefixed URLs, and Target Device names.
- [Locks](locks.md): one driver of the Target Devices at a time.
- [Tests](tests.md): `scripts/check`, the pytest suites, and the live checks.

## Explanation

- [How it works](how-it-works.md): routing modes and what the lab does to a request.
