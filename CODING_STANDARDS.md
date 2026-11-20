# Coding Standards

The judgement calls a reviewer checks. Mechanical rules (tests, shell syntax, Compose config, glossary terms, test imports) are enforced by `scripts/check`; read it there.

## Trust

- **Trust decisions read lab-owned state.** A guard, device label or rewrite decides from what the lab itself established: the listener a request arrived on, and `flow.metadata` set by an earlier addon (`proxy_base`, `lab_refusal`). A header the client or the Origin sets is data, not evidence. The one exception is a header whose sender the lab has proven: tunnel headers such as `CF-Connecting-IP`, trusted only on the tunnel listener, which only cloudflared reaches (`proxy/lab/clients.py`).
- **Runtime-specific trust lives in that runtime's config.** Shared config (`proxy/config/*.json`, addon option defaults) applies to every runtime: native, Compose and CA Routing alike. Trust that one runtime needs, such as Docker Desktop's `192.168.65.1`, goes in that runtime's own config (`LAB_LAN_SUBNETS` in `compose.yaml`), so no other runtime inherits it.
- **The secret check comes first on the tunnel.** An unauthenticated tunnel request learns nothing about the lab: it gets 403 `secret-segment` whatever it sends, with no refusal reason, header or behaviour that reveals another guard, the routing or the config.

## Boundaries

- **External tools consume the lab's outputs.** `grid/` and any other tool read what the lab publishes (device labels in flow comments, `X-Lab-Blocked` reasons, flows from mitmweb's API) and leave the lab's rules in `proxy/lab/`. A rule change in the lab needs no matching edit elsewhere.
- **One Prefixed URL builder and parser per codebase.** The proxy builds and parses through `proxy/lab/prefixed_url.py`; each Lab App flavour builds through its own (`PrefixedUrl.brs`, `prefixed-url.ts`). A second regex or an inline concatenation is a finding.
- **A Run is billed until stopped.** Code that starts a Cloud Device Run starts it inside the `try` whose `finally` stops it. On Ctrl-C or a kill it waits for `rce` to exit, then confirms with `rce device status` that the Run ended. A Run it didn't start is someone else's: use it and leave it running. Reference: `cloud_run` in `grid/run_cell.py`; roku-rce's `skill/SKILL.md`, Money and permanence.

## Tests

- **Proxy tests run at Seam A, through the full chain.** A test builds a flow, runs it through `tests/chain.py`, and asserts on what reaches the Origin or the client, so addons can be split or merged with every test still green (`.scratch/roku-mitm-lab/spec.md`, Testing Decisions).
