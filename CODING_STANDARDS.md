# Coding Standards

The judgement calls a reviewer checks. Mechanical rules (tests, shell syntax, Compose config, glossary terms, test imports) are enforced by `scripts/check`; read it there.

## Trust

- **Trust decisions read lab-owned state.** A guard, device label or rewrite decides from what the lab itself established: the listener a request arrived on, and `flow.metadata` set by an earlier addon (`proxy_base`, `lab_refusal`). A header the client or the Origin sets is data, not evidence. The one exception is a header whose sender the lab has proven: tunnel headers such as `CF-Connecting-IP`, trusted only on the tunnel listener, which only cloudflared reaches (`proxy/lab/clients.py`).
- **Runtime-specific trust lives in that runtime's config.** Shared config (`proxy/config/*.json`, addon option defaults) applies to every runtime: native, Compose and CA Routing alike. Trust that one runtime needs, such as Docker Desktop's `192.168.65.1`, goes in that runtime's own config (`LAB_LAN_SUBNETS` in `compose.yaml`), so no other runtime inherits it.
- **The secret check comes first on the tunnel.** An unauthenticated tunnel request learns nothing about the lab: it gets 403 `secret-segment` whatever it sends, with no refusal reason, header or behaviour that reveals another guard, the routing or the config.

## Boundaries

- **External tools consume the lab's outputs.** `grid/` and any other tool read what the lab publishes (device labels in flow comments, `X-Lab-Blocked` reasons, flows from mitmweb's API) and leave the lab's rules in `proxy/lab/`. A rule change in the lab needs no matching edit elsewhere.
- **One Prefixed URL builder and parser per codebase.** The proxy builds and parses through `proxy/lab/prefixed_url.py`; each Lab App flavour builds through its own (`PrefixedUrl.brs`, `prefixed-url.ts`), and each kit flavour through its own (`RoxyUrl` in `RoxyKit.brs`, `prefixedUrl` in `roxy-kit.ts`). A second regex or an inline concatenation is a finding.
- **A Run is billed until stopped.** Code that starts a Cloud Device Run starts it inside the `try` whose `finally` stops it. On Ctrl-C or a kill it waits for `rce` to exit, then confirms with `rce device status` that the Run ended. A Run it didn't start is someone else's: use it and leave it running. Reference: `cloud_run` in `grid/run_cell.py`; the rce CLI's skill, Money and permanence.
- **Personal settings live in the settings root.** Secrets, device names and addresses, and LAN subnets are read from the settings root (`scripts/lib.sh`, `proxy/lab/config.py`), never from the repo. The repo ships `settings.example/` with documentation IPs (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and made-up names, and tests run against a temp settings root seeded from it.

## Tests

- **Proxy tests run at Seam A, through the full chain.** A test builds a flow, runs it through `tests/chain.py`, and asserts on what reaches the Origin or the client, so addons can be split or merged with every test still green. The exceptions are modules the CLI uses too, tested at their own interface: App Profiles (`proxy/lab/app_profiles.py`), whose tests call `AppProfiles` against a temp settings root and temp git repos, and the Lab Session client (`proxy/lab/lab_session.py`), whose tests drive `LabSession` against mitmweb's API in memory.
