# roxy

A mitmproxy/mitmweb lab for inspecting and manipulating the traffic of Roku Lab Apps and Product Apps on Physical Devices and Cloud Devices (RCE). Design and usage: `README.md`, then `docs/README.md`. Vocabulary: `GLOSSARY.md`.

Personal settings (secrets, devices, LAN subnets) live in the settings root, never in the repo: `docs/settings.md`.

Writing or reviewing code: `CODING_STANDARDS.md`.

Ask the user before anything that reaches a Target Device, starts a Cloud Device Run (billed until stopped), opens a tunnel or runs `roxy start` on their own settings root. `scripts/check` needs none of them.

## Agent skills

### Issue tracker

Issues and specs live as local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Implementing a ticket

In a worktree, on a feature's integration branch: `docs/agents/implementing.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix), recorded as a `Status:` line. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
