# Guards

Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

The lab forwards a request only if the client is allowed, the Origin resolves to public addresses only, and, through the tunnel, the Origin host is on the allowlist. Anything else gets a 403 from the lab with an `X-Lab-Blocked` reason (`secret-segment`, `client-ip`, `origin-host`, `origin-address`) and is marked ⛔ in mitmweb. A non-Prefixed request gets 400 `not-prefixed` (unless the App Profile's [fallback Origin](settings.md#app-profiles) takes it); through the tunnel it gets 403 `secret-segment`, so a scanner learns nothing.

- A LAN client must be on one of your `lan_subnets`, and may reach any public Origin: the allowlist guards the Public Endpoint only.
- Relay exposure: while the lab runs, any device on your LAN subnets can use it as an HTTP relay to any public host, the same as with Charles. Only private, loopback, link-local and unique-local Origins stay out of reach.
- A request through the tunnel (it arrives on the tunnel listener, port 8082, which only cloudflared can reach) needs the secret path segment, its `CF-Connecting-IP` must be one of the RCE egress IPs, and its Origin host must be on the allowlist. Tunnel headers are trusted only there: a LAN client sending them is judged by its real IP.
- The address guard resolves the Origin, and mitmproxy then dials one of the addresses it checked (IPv4 first), never a later DNS answer: a name that turns private between the check and the connect (DNS rebinding) is not dialled. The cost: no server connection reuse across requests.
- Tunnel and forwarding headers (`CF-*`, `X-Forwarded-*`, `CDN-Loop`, `Forwarded`, `Via`...) never reach the Origin.
- Secrets on the command line: `scripts/run-mitmweb` passes `MITMWEB_PASSWORD` and `LAB_SECRET` to mitmweb as `--set` flags, so any local user can read them with `ps`. Accepted for a single-user lab Mac; do not run the lab on a shared machine.
- Secrets in output: `roxy status`, the `roxy start` banner and the grid show the public Proxy Base as `https://<tunnel-host>/<secret>`, since terminals and agent transcripts get copied around; `roxy launch` and the grid read the real one from the lab and your settings and send it to the Cloud Device. `roxy status --show-secret` prints it whole, for pasting into a Cloud Device by hand.
- Defaults: `lan_subnets` in your `settings.json`; `rce_egress_ips` and `origin_allowlist` in `proxy/config/guards.json` (the RCE egress IPs are Roku's, observed from RCE Runs, and may change; a leading dot such as `.mux.com` allows any subdomain), plus the loaded App Profile's `origin_allowlist`. Live changes: mitmweb Options `lab_lan_subnets`, `lab_rce_egress_ips`, `lab_origin_allowlist`.
