# Docker Compose

Needs Docker, which replaces uv and cloudflared. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

The same addons, config, Scenarios and mitmweb flags (`scripts/run-mitmweb`), mounted from the repo; no Python or cloudflared to install. Settings and secrets come from the same settings root (mounted read-only; `ROXY_CONFIG_DIR` works here too), and Recordings are saved in the same user data directory.

```sh
docker compose up                       # LAN listeners on :8080 and :8888, mitmweb UI on http://127.0.0.1:8081
docker compose --profile tunnel up      # plus the quick tunnel, for Cloud Devices
curl -s 127.0.0.1:20241/quicktunnel     # the tunnel's hostname: public Proxy Base https://<hostname>/<LAB_SECRET>
docker compose --profile tunnel down    # stops both, closing the Public Endpoint
LAB_REPLAY=<recording>.mitm docker compose up    # replay (path relative to the Recordings folder)
```

- `scripts/deploy` and `roxy launch` work as above with the LAN Proxy Base `http://<this machine's LAN IP>:8080`. The grid runner does not run under Compose.
- Docker Desktop (macOS) hides the client IP: every LAN client shows as `192.168.65.1`. `compose.yaml` therefore sets `LAB_LAN_SUBNETS` (read by `scripts/run-mitmweb`, replacing `lan_subnets`) to `192.168.65.1/32`; the native lab's `lan_subnets` does not include it. The tradeoff: under Compose on macOS the LAN subnet guard lets in whatever can reach port 8080, and Physical Devices get no name. On Linux the real client IP shows: run `LAB_LAN_SUBNETS="<your LAN subnets>" docker compose up` instead.
- Linux: the container runs as uid 1000, so the Recordings folder must be writable by it.
- cloudflared dials the unpublished tunnel listener (`mitmweb:8082`) over the Compose network, so a LAN client cannot pass for the tunnel. CA Routing is not wired into Compose.
