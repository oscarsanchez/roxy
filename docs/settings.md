# Settings and App Profiles

Where your secrets, devices, LAN subnets and App Profiles live, and what each file holds. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

Your secrets, devices and LAN subnets live in the **settings root**, `~/.config/roxy/` (`$XDG_CONFIG_HOME/roxy` if you set that), never in the repo. The environment variable `ROXY_CONFIG_DIR` points the lab at another settings root, for tests or experiments. The repo ships examples only, in `settings.example/`; the install copies each one the settings root lacks, for you to fill in:

| File | Holds |
|---|---|
| `secrets.env` | `MITMWEB_PASSWORD` (mitmweb UI), `LAB_SECRET` (secret path segment of the public Proxy Base, Cloud Devices), `ROKU_DEV_USER` and `ROKU_DEV_PASSWORD` (sideloading to Physical Devices; a Cloud Device's dev password is kept by `rce`) |
| `devices.json` | Target Devices by name: `{"ip": ...}` for a Physical Device, `{"rce_device_name": ..., "slug": ...}` for a Cloud Device (its rce Device Name, see `rce device list`; the scripts check it with `rce device resolve`) |
| `settings.json` | `lan_subnets`: your LAN's subnets (CIDR), the clients allowed on the LAN listener. `grid_devices`: the Target Device the grid runner uses for each kind (`physical`, `cloud`, `ca-routing`) |
| `apps/<name>/` | App Profiles, made by `roxy app new` (see [App Profiles](#app-profiles)) |

- `roxy start` stops before mitmweb starts if a file, a secret it needs or `lan_subnets` is missing, and names it.
- The RCE token is `rce`'s (`rce token set`), not the lab's. Keep `RCE_TOKEN` out of `secrets.env`: the scripts export it, and `rce` takes `RCE_TOKEN` over its stored token.
- The lab's own defaults, the same for everyone, stay in the repo: `proxy/config/guards.json` (RCE egress IPs and the Origin allowlist, see [Guards](guards.md)). Restart the lab after editing a setting.

## App Profiles

An App Profile keeps what the lab knows about one Product App in your settings root, never in a repo: the repo it belongs to, its Scenarios with their mocks, and the Origins it may reach through the Public Endpoint. It is optional: without one, the LAN relays to any public Origin and the lab's own Scenarios are there.

```sh
cd ~/code/example-app/src && roxy app new example-app    # records the repo's git root, not the folder you are in
roxy app list                                            # each profile and its repo
```

`roxy app new` refuses a name that exists. A profile is the folder `~/.config/roxy/apps/<name>/`:

- `scenarios/<scenario>.toml`: its Scenarios, written like the lab's own, with their mocks next to them (`map_local = "mocks/catalog.json"` answers from `scenarios/mocks/catalog.json`).
- `profile.json`: `repo`, and `origin_allowlist`, the hosts the Public Endpoint may reach for this app on top of the lab's own (a leading dot allows any subdomain). Optional: `"rewrite_text": true` turns the text body format on for this app ([Header and body rewriting](rewriting.md)), and `fallback_origin`, below.

A **fallback Origin**, for LAN listeners only, catches requests that reach the lab with no Origin in them: a bare path on the LAN proxy port, such as `/live/…/hls/…/seg.ts`, which a Charles hook leaves behind when the app resolves a root-relative URL against the proxy instead of the CDN. In `profile.json`:

```json
"fallback_origin": {"path": "^/live/[^/]+/hls/", "origin": "https://cdn.example"}
```

A bare path the `path` regex matches (searched in the path, not the query) goes to `origin` with its path and query kept, as if it had arrived Prefixed with the client's Proxy Base in the `/;` form: URLs in its response come back as `<Proxy Base>/;<Origin URL>`, while relative ones stay relative and so arrive as bare paths again: write the regex to match those too. Every guard still judges it, so a private Origin is refused `origin-address`. Any other bare path is still refused `not-prefixed`. The Public Endpoint never takes a fallback: it needs a Prefixed URL behind the secret, and a bare path there gets `secret-segment` as before. With CA Routing on, every non-Prefixed request takes its Origin from Host/SNI, on the LAN proxy port too, so the fallback Origin never applies. `origin` is `http(s)://host[:port]`; a bad regex or Origin stops the start, naming the profile.

`roxy start` loads at most one: `--app <name>` (an unknown name fails), else the profile whose repo holds the current folder, else none. To switch apps, stop the lab and start it in the other app's folder. A profile Scenario named like one of the lab's own stops the start, naming both; `roxy scenario list` shows that name once, as `refused: in both (rename the profile's)`. Restart the lab after editing `profile.json`; a Scenario file reloads as usual.
