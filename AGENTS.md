# roxy

A mitmproxy/mitmweb lab for inspecting and manipulating the traffic of Roku Lab Apps and Product Apps on Physical Devices and Cloud Devices (RCE). Design and usage: `README.md`. Vocabulary: `GLOSSARY.md`.

Personal settings (secrets, devices, LAN subnets) live in the settings root, never in the repo: `README.md`, Settings.

Writing or reviewing code: `CODING_STANDARDS.md`.

## Agent skills

### Issue tracker

Issues and specs live as local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix), recorded as a `Status:` line. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
