# Agents

Giving an agent (Claude Code, Cursor) the lab, and the flows it reads. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

The `roxy` skill teaches an agent in any app's repo when and how to use the lab: start it for the app, launch, write and set Scenarios, read the flows, and the known limits. It links to the guides rather than repeating them. Claude Code gets it from the plugin, from GitHub:

```sh
claude plugin marketplace add oscarsanchez/roxy
claude plugin install roxy@roxy
```

or from a local checkout (after `./install.sh`, from the checkout): `claude plugin marketplace add "$PWD"`, then the same install.

The plugin is a copy of the checkout: after a `git pull`, run `claude plugin update roxy@roxy`. It also puts its copy's `roxy` on the PATH of Claude's Bash tool; the terminal and Cursor use the one `install.sh` links.

Signed in to Cursor, its agent loads skills from installed Claude Code plugins, so it has the skill already. Without the plugin, link it: `mkdir -p ~/.cursor/skills && ln -sfn "$PWD/skills/roxy" ~/.cursor/skills/roxy`.

In each app's repo, add this pointer to its `AGENTS.md` (or `CLAUDE.md`), with the app's App Profile and how it routes; Claude Code and Cursor both read it:

```markdown
## roxy
To see what this app requests, or to make an Origin fail, slow down or answer from a mock, use the roxy lab: the `roxy` skill, or `skills/roxy/SKILL.md` in the roxy checkout (`realpath "$(command -v roxy)"` is its `bin/roxy`).
App Profile: `<profile>`. Routing: <its Charles hook, port 8888 | the kit, built with ROXY_KIT=1 or bs_const=roxy_kit=true>.
```

## Flows for agents

`roxy flows --json` prints the running lab's flows, so an agent can see what the app requested without opening mitmweb. It reads mitmweb's API with `MITMWEB_PASSWORD` and is read-only: it never holds, resumes or edits a flow. With the lab down it says so and exits non-zero; a filter expression mitmweb rejects and a wrong `MITMWEB_PASSWORD` each get their own error.

```sh
roxy flows --json                                       # every flow in mitmweb, oldest first
roxy flows --json --since 176363286012345               # since a roxy launch (its run=<id>)
roxy flows --json --since 2025-11-20T10:00:00Z          # since a time (ISO 8601; local time without an offset)
roxy flows --json --filter '~comment "Living Room" & ~d httpbin.org' --limit 20   # a mitmproxy filter expression; the last 20
```

`--filter` is applied by mitmweb, then `--since` and `--limit` (the last N flows). The output is one JSON array, one flow per line:

```json
[{"id": "35f7b2d8-754f-43c6-9044-607c1660affb", "time": "2025-11-20T10:02:00.000Z", "device": "Living Room", "method": "GET", "url": "https://httpbin.org/json", "status": 503, "request_bytes": 0, "response_bytes": 17, "duration_ms": 250, "refusal": null, "scenario_rules": ["json-503/httpbin json fails"], "double_prefixed": false}]
```

| Field | Value |
| --- | --- |
| `id` | mitmweb's flow id |
| `time` | when the flow started, ISO 8601 UTC with milliseconds |
| `device` | its Target Device's name ([Target Device names](rewriting.md#target-device-names)), `null` for none |
| `method` | the request method |
| `url` | the Origin URL; for a request the lab could not decode (`not-prefixed`), the dummy reverse target |
| `status` | the status the client got, `null` without a response (dropped, failed) |
| `request_bytes`, `response_bytes` | body sizes as sent, `null` without that message |
| `duration_ms` | from the request's start to the response's end at the client (a `throttle` rule's pacing included), `null` without a complete response |
| `refusal` | the reason the lab refused it (its `X-Lab-Blocked` value, such as `origin-address`), `null` if it did not; an `X-Lab-Blocked` header from an Origin or a Scenario is not a refusal |
| `scenario_rules` | the active Scenarios' rules that acted on it, each named `<scenario>/<rule>`, in the order they first did; `[]` for none |
| `double_prefixed` | `true` if the request arrived as a Nested Prefixed URL (the app prefixed a URL twice, [Prefix Routing guide](prefix-routing.md#nested-prefixed-urls)), which the lab stripped back to the Origin; `false` otherwise |
