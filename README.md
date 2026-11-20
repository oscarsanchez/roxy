# roxy

A mitmproxy/mitmweb lab on your Mac for inspecting and manipulating the traffic of Roku apps, on Physical Devices and on Roku Cloud Emulator (Cloud Devices). The app calls Prefixed URLs (`<Proxy Base>/<Origin URL>`), so no device proxy setting or CA is needed.

Vocabulary: [GLOSSARY.md](GLOSSARY.md). Code conventions: [CODING_STANDARDS.md](CODING_STANDARDS.md).

## How it works

### Scope

- Every kind of Outbound Traffic: JSON APIs, images, HLS, DASH, Widevine licenses, RAF ads (VAST, VAST wrappers, VMAP) and their beacons.
- Inspection in mitmweb, and Manipulation: mocked or map-local responses, rewritten headers and bodies, injected faults (status, latency, drops), edited manifests, held-and-edited flows, and recorded sessions replayed.
- Two disposable Lab Apps (classic BrightScript/SceneGraph and RSG 2.0) exercise every traffic class and serve as the regression grid. Store apps and Roku OS's own traffic are out of scope.

### Routing

**Prefix Routing** works on every Target Device. The app puts the Proxy Base in front of every URL it builds, `<Proxy Base>/<Origin URL>`, or `<Proxy Base>/;<Origin URL>` as a Charles-enabled build does (port 8888). How to wire an app, with its Charles hook or with the kit for apps you own (`kit/`): [Prefix Routing guide](docs/prefix-routing.md). The Lab Apps take the Proxy Base from the `proxyBase` launch param, with a build-time default as the fallback, and build the `/` form unless launched with `separator=/;`. The Proxy Base differs by Target Device kind:

| Target Device | Proxy Base |
|---|---|
| Physical Device | `http://<mac-lan-ip>:8080`, or `:8888` (Charles's port). Give the Mac a DHCP reservation so it stays stable. |
| Cloud Device | `https://<tunnel-host>/<secret>/<device-slug>`: the Public Endpoint (a Cloudflare quick tunnel), the secret segment, and the slug that names the Cloud Device (`roxy launch` adds it). |

**CA Routing** (Physical Devices only): DNS on the router points Origins at the Mac, and a CA Routing build of the app calls Origin URLs directly while trusting the lab's CA on every agent. See [CA Routing](#ca-routing-physical-devices-only).

### What the lab does to a request

mitmweb runs in mitmproxy's `reverse` mode. Its UI listens on `127.0.0.1` only, needs a password, and is never tunnelled. The lab's addons, in order:

1. **Origin decoding**: recovers the Origin and the client's Proxy Base from the Prefixed URL path, or from Host/SNI in CA Routing.
2. **Device labels**: names the Target Device that sent the flow.
3. **Guards**: refuse anything but an allowed client and a public Origin address, and on the Public Endpoint an allowlisted Origin host (see [Guards](#guards)).
4. **Request header cleanup**: `Host` is the Origin's, `Referer` and `Origin` are decoded back, tunnel headers are stripped.
5. **Response header and body rewriting**: URLs in headers and in HLS, DASH, VAST/XML and JSON bodies become Prefixed URLs with the client's Proxy Base, so follow-up requests come back through the lab.
6. **Scenarios**: the active Scenario's Manipulation rules, last, so they see the response as the client gets it. The one exception, `map_remote`, swaps the Origin right after Origin decoding, before the guards.

While the lab runs, any device on your LAN subnets can relay through it to any public host, the same as with Charles.

## Quickstart

### 1. Prerequisites

- macOS with [uv](https://docs.astral.sh/uv/) (installs the pinned mitmproxy 12.3.1 into `proxy/.venv`) and `brew install jq`.
- A Roku in developer mode on the same LAN as the Mac.
- Cloud Devices only: `brew install cloudflared` and the `rce` CLI (install it as its README says), which does every RCE call for the lab. Give the Cloud Device an rce Device Name and a Dev Snapshot once: `rce device alias <id> player`, `rce device setup-dev player`.
- RSG 2.0 Lab App only: Node 24+ (`brew install node@24`; `scripts/deploy` puts it first on PATH), pnpm 11, `brew install squashfs`.
- Compose only: Docker. It replaces uv and cloudflared.

### 2. Install and settings

```sh
./install.sh                               # links roxy into ~/.local/bin (put that on your PATH); seeds missing settings
git config core.hooksPath .githooks        # pre-commit hook: runs scripts/check (see Tests)
```

`install.sh` links `bin/roxy` from this checkout, so `git pull` updates it, and `roxy` works from any terminal, Cursor's included. Run it again whenever you like: it refreshes the link and never overwrites a setting. It refuses, changing nothing, when `~/.local/bin/roxy` exists and is not a link. For an agent in an app's repo, add the plugin and a pointer too: [Agents](#agents).

Your secrets, devices and LAN subnets live in the **settings root**, `~/.config/roxy/` (`$XDG_CONFIG_HOME/roxy` if you set that), never in the repo. The environment variable `ROXY_CONFIG_DIR` points the lab at another settings root, for tests or experiments. The repo ships examples only, in `settings.example/`; the install copies each one the settings root lacks, for you to fill in:

| File | Holds |
|---|---|
| `secrets.env` | `MITMWEB_PASSWORD` (mitmweb UI), `LAB_SECRET` (secret path segment of the public Proxy Base, Cloud Devices), `ROKU_DEV_USER` and `ROKU_DEV_PASSWORD` (sideloading to Physical Devices; a Cloud Device's dev password is kept by `rce`) |
| `devices.json` | Target Devices by name: `{"ip": ...}` for a Physical Device, `{"rce_device_name": ..., "slug": ...}` for a Cloud Device (its rce Device Name, see `rce device list`; the scripts check it with `rce device resolve`) |
| `settings.json` | `lan_subnets`: your LAN's subnets (CIDR), the clients allowed on the LAN listener. `grid_devices`: the Target Device the grid runner uses for each kind (`physical`, `cloud`, `ca-routing`) |
| `apps/<name>/` | App Profiles, made by `roxy app new` (see [App Profiles](#app-profiles)) |

- `roxy start` stops before mitmweb starts if a file, a secret it needs or `lan_subnets` is missing, and names it.
- The RCE token is `rce`'s (`rce token set`), not the lab's. Keep `RCE_TOKEN` out of `secrets.env`: the scripts export it, and `rce` takes `RCE_TOKEN` over its stored token.
- The lab's own defaults, the same for everyone, stay in the repo: `proxy/config/guards.json` (RCE egress IPs and the Origin allowlist, see [Guards](#guards)). Restart the lab after editing a setting.

### 3. Start the lab

```sh
roxy start                           # mitmweb UI http://127.0.0.1:8081; prints the Proxy IP and both LAN Proxy Bases
roxy start --tunnel                  # plus the Public Endpoint for Cloud Devices: prints https://<random>.trycloudflare.com/<LAB_SECRET>
roxy start --replay <session>.mitm   # answer from a saved session (see Recording and replay)
roxy start --ca-routing              # also listens on 443/80 (see CA Routing)
roxy start --app <name>              # load that App Profile; without --app, the one whose repo you are in, if any
roxy status                          # from another terminal: up or down (exit 1); Proxy IP, Proxy Bases, App Profile, active Scenario
roxy flows --json --limit 20         # the last 20 flows as JSON, for agents (see Flows for agents)
```

`roxy` is a thin dispatcher over `scripts/` (`roxy start` runs `scripts/start-lab`), and `roxy <subcommand> --help` describes each subcommand. The lab runs in the foreground: there is no daemon and no `stop`. Ctrl-C stops mitmweb and the tunnel together. Every session is saved in your user data directory, `~/.local/share/roxy/captures/<App Profile>/<start time>.mitm`, or `captures/no-profile/` without one (`$XDG_DATA_HOME/roxy/...` if you set that). The tunnel hostname changes on every start; its log is `out/cloudflared.log`.

### 4. Deploy and launch

Device names come from your `devices.json`; these examples use the example names.

```sh
scripts/deploy "Living Room" apps/classic                # classic (BrightScript) Lab App
scripts/deploy "Living Room" apps/rsg                    # RSG 2.0 Lab App: pnpm install if needed, rk build --debug, sideload
roxy launch "Living Room" case=json_get                  # prints run=<id>; the result line is on the debug console
roxy console "Living Room" --launch json_get             # the console from connect to the run's result line, saved to out/console/
```

`roxy launch <device> [key=value...]` launches the dev channel with `proxyBase`, your launch params, and a fresh `run` id; it never builds or sideloads. `proxyBase` goes by kind of Target Device: the LAN Proxy Base for a Physical Device, the running tunnel's public Proxy Base plus the device slug for a Cloud Device. `--proxy-base URL` sends another. The Lab Apps read `case`; a Product App reads whatever params it takes.

Cloud Device (start the lab with `--tunnel`). Deploy and launch go through `rce`, and need a running Cloud Device:

```sh
rce device start player                                  # billed from here, $0.20 per hour
scripts/deploy "Cloud Device" apps/classic               # rce sideload, with the Cloud Device's own dev password
roxy launch "Cloud Device" case=json_get                 # proxyBase https://<random>.trycloudflare.com/<LAB_SECRET>/<slug>
rce console player --until 'LABRESULT json_get' --timeout 60   # roxy console "Cloud Device" streams it without --until
rce device stop player                                   # billing ends here
```

Cases (same ids, labels and Origins in both flavours, also in an on-screen menu): `json_get`, `redirect`, `json_post`, `image`, `hls`, `dash`, `widevine`, `raf`, `raf_vmap`; classic also has `uuid` (new data on each request, to prove replay). Launched without a Proxy Base, the app uses the LAN Proxy Base it was built with.

**Result lines** (one per run; the console replays recent history on connect, so match on `run=<id>`):

- Requests: `LABRESULT <case> run=<id> status=<code> bytes=<n> fp=<first 12 hex digits of the sha1>`. `json_post` adds `sentfp=` (equal to `fp` = the body arrived intact). `image` reports `status`, `prefixed=<yes|no>` (the catalog's image URL came back as a Prefixed URL) and `poster=<ready|failed>`.
- Playback (`hls`, `dash`, `widevine`): `state=<playing|error|finished|timeout_<state>> errorCode=<n> bitrate=<first video segment bps>`. `widevine` adds `license=`: `2` once the license is acquired (Roku OS 16), the license server's HTTP status when it fails, `none` if none was requested. A playback error also prints `LABERROR <case> run=<id> <errorStr>` (diagnostic only).
- `raf`: one RAF ad break from Google's sample VAST wrapper tag, as a Prefixed URL: `outcome=<completed|no_ads|exited> ads= impressions= completes= errors= media=<lab|direct|none>` (`media`: the first creative is a Prefixed URL). RAF's own `[RAF] fireBeacon(...)` log is on the console. In the RSG app, `impressions`, `completes` and `errors` are `na`: the SDK's `@roku-sdk/ads` task has no tracking callback, so count beacons in mitmweb.
- `raf_vmap`: the same, from Google's IMA VMAP pre-roll sample tag: RAF follows the VMAP's `AdTagURI` to the VAST ad and plays the pre-roll pod.
- RSG lines start with `[TS]: ` and carry colour codes; match on `LABRESULT`. A release `rk build` strips `console.*`, so always build with `--debug`. By hand: `cd apps/rsg && LAB_PROXY_BASE=http://<mac-ip>:8080 ./node_modules/.bin/rk build --debug --local`.

### 5. Scenarios

A Scenario is a file of named Manipulation rules, `proxy/scenarios/<name>.toml`. One is active at a time, lab-wide, for every Target Device:

```sh
roxy scenario list                                      # the App Profile's Scenarios and the lab's, each with its source
roxy scenario set json-503                              # make it active in the running lab
roxy scenario clear                                     # none active
roxy launch --scenario json-503 "Living Room" case=json_get   # set it, then launch ('' clears it)
```

Or edit `lab_scenario` in mitmweb's Options. Editing the active file reloads it on the next request; a broken edit is logged and the last good rules stay. Shipped: `json-503`, `image-404`, `hls-404`, `dash-404`, `dash-absolute` (absolute `<BaseURL>`), `hls-lowest-variant`, `widevine-license-fail` (`state=error errorCode=-6 license=403`), `raf-ad-tag-drop` (`outcome=no_ads` for `raf` and `raf_vmap`; a status override alone is not enough, RAF reads a 503's VAST body).

Each rule has a `name`, a mitmproxy `filter` expression and exactly one action. Every matching rule applies, in file order. Flows the lab refused itself are never touched.

```toml
[[rule]]
name = "json fails"
filter = "~d httpbin.org & ~u /json"
status = 503                                    # status override (the Origin's body is kept)
# latency = 2.5                                 # seconds, before the request reaches the Origin
# throttle = { kbps = 400 }                     # the response reaches the client at no more than 400 kbps
# drop = true                                   # close the connection, no answer, Origin not contacted
# header = { name = "Cache-Control", value = "no-store" }   # replace; "" removes (mitmproxy modify_headers)
# body = { pattern = "regex", replacement = "text" }        # regex replace (mitmproxy modify_body)
# map_local = "mocks/json.json"                 # answer from a file next to the Scenario (mitmproxy map_local)
# map_remote = "https://postman-echo.com:443"   # send to another Origin: scheme, host and optional port only
```

`header` and `body` act on the request and the response, like their mitmproxy built-ins: add `~q` or `~s` to the filter to pick one.

A `header` value or `body` replacement can hold placeholders, filled per flow from the client that made it, so one rule points a URL at the lab for every Target Device without an address in it:

| Placeholder | Filled with | LAN client | Public Endpoint client |
| --- | --- | --- | --- |
| `{proxy_base}` | the client's Proxy Base | `http://192.0.2.10:8080` | `https://<public-endpoint>/<secret>/<slug>` |
| `{proxy_base_no_scheme}` | the same without its scheme | `192.0.2.10:8080` | `<public-endpoint>/<secret>/<slug>` |
| `{separator}` | the separator the client used | `/` or `/;` | `/` or `/;` |

```toml
[[rule]]
name = "cdn through the lab"                    # the app reads mediaHost="cdn.example.com/media" and adds its own scheme
filter = "~s & ~d api.example.com"
body = { pattern = 'mediaHost="', replacement = 'mediaHost="{proxy_base_no_scheme}{separator}https://' }
```

A placeholder is `{name}`, lowercase letters and underscores: braces stay clear of regex replacement syntax (`\1`, `\g<1>`). Any other `{name}` in a replacement is refused when the Scenario loads (a broken edit keeps the last good rules), so a literal `{word}` cannot be written there. A flow that was not Prefixed (CA Routing) has no Proxy Base: a rule with placeholders leaves it alone.

`throttle` caps each matching flow on its own (no shared link), like Charles's Throttle without the presets: the response starts at once and arrives slowly, so a player sees a slow download, not a late one, and ABR can step down. It paces the response after every other rule and the lab's own rewriting, and takes a positive `kbps`. HTTP/1 only: a flow whose client speaks HTTP/2 shares its connection with other flows, so it is sent unthrottled and the mitmweb event log says so. Add a `latency` rule with the same filter for a slow, high-latency link. On a Cloud Device the paced bytes go through the quick tunnel: keep such runs short.

`map_remote` keeps the request's path and query, and Host follows the new Origin. It runs before the guards, so the new host is judged like any other: a private address is refused, and through the tunnel so is a host off the allowlist. Responses from it are rewritten with the client's Proxy Base, as usual. Later rules' filters see the new Origin.

Manifest edits change manifests only (`filter = "~all"` is fine) and run after Prefixed URL rewriting, so the manifest still routes through the lab:

```toml
drop_variants = { all_but = "lowest" }          # or "highest"; or bandwidth_above / bandwidth_below = bps; or resolution = "WxH"
drop_renditions = { type = "SUBTITLES" }        # HLS EXT-X-MEDIA matching every key given: type, group_id, language, name
drop_renditions = { content_type = "audio" }    # DASH AdaptationSets matching every key given: content_type, mime_type, lang
drop_segments = { from = 3, to = 5 }            # HLS media playlist, segment indexes from 0; no `to` = to the end
alter_segments = { from = 2, uri = "missing.ts", duration = 1.5 }   # HLS: new URI and/or EXTINF duration
```

`drop_variants` also drops DASH Representations (`all_but` per AdaptationSet), and `drop_renditions` with DASH keys drops whole AdaptationSets; the segment edits are HLS only. `--scenario hls-lowest-variant ... hls` drops `bitrate=` to the lowest variant.

### 6. Grid runner

```sh
scripts/grid <classic|rsg> <physical|cloud> <json|json_post|image|hls|dash|widevine|raf|raf_vmap> [--proxy-base URL] [--ca-routing] [--separator /|/;]
scripts/grid classic physical json
scripts/grid rsg cloud hls --proxy-base "https://<random>.trycloudflare.com/<LAB_SECRET>"
scripts/grid classic physical json --ca-routing   # CA Routing (see CA Routing)
scripts/grid classic physical hls --separator '/;'   # the Charles-style form
```

`--separator '/;'` runs the cell in the Charles-style form: the Lab App gets the `separator=/;` launch param and builds every Prefixed URL as `<Proxy Base>/;<Origin URL>`, and the row says `(/; form)`. The default `/` is the lab's own form. Quote `/;`: in a shell, `;` ends the command. CA Routing has no Prefixed URLs, so it takes no `--separator`. Outside the grid, `roxy launch "Living Room" case=hls 'separator=/;'` does the same.

It fills one grid cell through the running native lab (`scripts/start-lab`, not Compose), on the Target Device that `grid_devices` in your `settings.json` names for that kind: it deploys the flavour, launches the case with the cell's Manipulation Scenario and then with none (so the lab ends with no Scenario), and prints one row: pass, fail or known-limit, with a reason. Each launch's console and flows are kept in `out/grid/` as evidence for the verdict. Cells live in `grid/cells.toml`: per traffic class, the case, the Scenario, the expected Origin hosts and the result fields that mean success. A Cloud Device cell prints the projected RCE time and cost (about 5.3 min, $0.018, start-up included) and asks before it touches RCE. It then starts the Cloud Device if it has no Run, reads its console with `rce console`, and stops it after the cell, also when the cell fails or on Ctrl-C or a kill (during the start too), then confirms with `rce device status` that the Run ended; a Run that was already going is left running.

- **Pass:** the run without a Scenario succeeded, every expected Origin host showed up in that run's flows from the Target Device, the lab refused nothing, and the Scenario changed the result line.
- **Leaks** can only be inferred, since traffic that bypasses the lab never reaches mitmweb: an expected host is missing although the Lab App reports success, or the console prints an absolute URL that is not a Prefixed URL. A bypassing request to a host outside the expected hosts, one the result does not depend on (a beacon, a prefetch), and Roku OS traffic go unseen.
- No result line before the timeout: rerun the cell (an RSG launch crash is possible). A `raf` or `raf_vmap` baseline of `no_ads` is a known flake of Google's sample ad server: rerun. If a run errors part-way, its Scenario stays active: clear it with `--scenario ''`.

### 7. Docker Compose

The same addons, config, Scenarios and mitmweb flags (`scripts/run-mitmweb`), mounted from the repo; no Python or cloudflared to install. Settings and secrets come from the same settings root (mounted read-only; `ROXY_CONFIG_DIR` works here too), and sessions are saved in the same user data directory.

```sh
docker compose up                       # LAN listeners on :8080 and :8888, mitmweb UI on http://127.0.0.1:8081
docker compose --profile tunnel up      # plus the quick tunnel, for Cloud Devices
curl -s 127.0.0.1:20241/quicktunnel     # the tunnel's hostname: public Proxy Base https://<hostname>/<LAB_SECRET>
docker compose --profile tunnel down    # stops both, closing the Public Endpoint
LAB_REPLAY=<session>.mitm docker compose up    # replay (path relative to the saved-session folder)
```

- `scripts/deploy` and `roxy launch` work as above with the LAN Proxy Base `http://<this machine's LAN IP>:8080`. The grid runner does not run under Compose.
- Docker Desktop (macOS) hides the client IP: every LAN client shows as `192.168.65.1`. `compose.yaml` therefore sets `LAB_LAN_SUBNETS` (read by `scripts/run-mitmweb`, replacing `lan_subnets`) to `192.168.65.1/32`; the native lab's `lan_subnets` does not include it. The tradeoff: under Compose on macOS the LAN subnet guard lets in whatever can reach port 8080, and Physical Devices get no device label. On Linux the real client IP shows: run `LAB_LAN_SUBNETS="<your LAN subnets>" docker compose up` instead.
- Linux: the container runs as uid 1000, so the saved-session folder must be writable by it.
- cloudflared dials the unpublished tunnel listener (`mitmweb:8082`) over the Compose network, so a LAN client cannot pass for the tunnel. CA Routing is not wired into Compose.

## Reference

### App Profiles

An App Profile keeps what the lab knows about one Product App in your settings root, never in a repo: the repo it belongs to, its Scenarios with their mocks, and the Origins it may reach through the Public Endpoint. It is optional: without one, the LAN relays to any public Origin and the lab's own Scenarios are there.

```sh
cd ~/code/example-app/src && roxy app new example-app    # records the repo's git root, not the folder you are in
roxy app list                                            # each profile and its repo
```

`roxy app new` refuses a name that exists. A profile is the folder `~/.config/roxy/apps/<name>/`:

- `scenarios/<scenario>.toml`: its Scenarios, written like the lab's own, with their mocks next to them (`map_local = "mocks/catalog.json"` answers from `scenarios/mocks/catalog.json`).
- `profile.json`: `repo`, and `origin_allowlist`, the hosts the Public Endpoint may reach for this app on top of the lab's own (a leading dot allows any subdomain). Optional: `"rewrite_text": true` turns the text body format on for this app (Header and body rewriting), and `fallback_origin`, below.

A **fallback Origin**, for LAN listeners only, catches requests that reach the lab with no Origin in them: a bare path on the LAN proxy port, such as `/live/…/hls/…/seg.ts`, which a Charles hook leaves behind when the app resolves a root-relative URL against the proxy instead of the CDN. In `profile.json`:

```json
"fallback_origin": {"path": "^/live/[^/]+/hls/", "origin": "https://cdn.example"}
```

A bare path the `path` regex matches (searched in the path, not the query) goes to `origin` with its path and query kept, as if it had arrived Prefixed with the client's Proxy Base in the `/;` form: URLs in its response come back as `<Proxy Base>/;<Origin URL>`, while relative ones stay relative and so arrive as bare paths again: write the regex to match those too. Every guard still judges it, so a private Origin is refused `origin-address`. Any other bare path is still refused `not-prefixed`. The Public Endpoint never takes a fallback: it needs a Prefixed URL behind the secret, and a bare path there gets `secret-segment` as before. With CA Routing on, every non-Prefixed request takes its Origin from Host/SNI, on the LAN proxy port too, so the fallback Origin never applies. `origin` is `http(s)://host[:port]`; a bad regex or Origin stops the start, naming the profile.

`roxy start` loads at most one: `--app <name>` (an unknown name fails), else the profile whose repo holds the current folder, else none. To switch apps, stop the lab and start it in the other app's folder. A profile Scenario named like one of the lab's own stops the start, naming both; `roxy scenario list` shows that name once, as `refused: in both (rename the profile's)`. Restart the lab after editing `profile.json`; a Scenario file reloads as usual.

### Guards

The lab forwards a request only if the client is allowed, the Origin resolves to public addresses only, and, through the tunnel, the Origin host is on the allowlist. Anything else gets a 403 from the lab with an `X-Lab-Blocked` reason (`secret-segment`, `client-ip`, `origin-host`, `origin-address`) and is marked in mitmweb (filter `~marked`). A non-Prefixed request gets 400 `not-prefixed` (unless the App Profile's [fallback Origin](#app-profiles) takes it); through the tunnel it gets 403 `secret-segment`, so a scanner learns nothing.

- A LAN client must be on one of your `lan_subnets`, and may reach any public Origin: the allowlist guards the Public Endpoint only.
- Relay exposure: while the lab runs, any device on your LAN subnets can use it as an HTTP relay to any public host, the same as with Charles. Only private, loopback, link-local and unique-local Origins stay out of reach.
- A request through the tunnel (it arrives on the tunnel listener, port 8082, which only cloudflared can reach) needs the secret path segment, its `CF-Connecting-IP` must be one of the RCE egress IPs, and its Origin host must be on the allowlist. Tunnel headers are trusted only there: a LAN client sending them is judged by its real IP.
- The address guard resolves the Origin, and mitmproxy then dials one of the addresses it checked (IPv4 first), never a later DNS answer: a name that turns private between the check and the connect (DNS rebinding) is not dialled. The cost: no server connection reuse across requests.
- Tunnel and forwarding headers (`CF-*`, `X-Forwarded-*`, `CDN-Loop`, `Forwarded`, `Via`...) never reach the Origin.
- Secrets on the command line: `scripts/run-mitmweb` passes `MITMWEB_PASSWORD` and `LAB_SECRET` to mitmweb as `--set` flags, so any local user can read them with `ps`. Accepted for a single-user lab Mac; do not run the lab on a shared machine.
- Defaults: `lan_subnets` in your `settings.json`; `rce_egress_ips` and `origin_allowlist` in `proxy/config/guards.json` (a leading dot such as `.mux.com` allows any subdomain), plus the loaded App Profile's `origin_allowlist`. Live changes: mitmweb Options `lab_lan_subnets`, `lab_rce_egress_ips`, `lab_origin_allowlist`.

### Header and body rewriting

URLs in response headers (Location, Content-Location, Link, Refresh) and bodies become Prefixed URLs with the client's Proxy Base and the separator (`/` or `/;`) the request used, so follow-up requests (segments, images, ads) come back through the lab. A URL already carrying the client's Proxy Base, in either form, is never prefixed twice: it comes back with the separator the request used. Set-Cookie is scoped to the Prefixed path (to the Proxy Base for `/;`: a cookie path cannot hold `;`), and its `Domain` is dropped. The body rewriter is chosen by content type, falling back to the URL extension; anything else passes byte for byte.

- Each format has an option `lab_rewrite_<format>` (`hls`, `dash`, `json`, `xml`, `text`) listing its content types and `.ext` extensions; a `+suffix` entry (`+json`, `+xml`) covers every type with that structured-syntax suffix (`application/vnd.example+json`), and a type ending in `/*` (`text/*`) covers its whole family, each after every exact type and extension, suffixes before families. Change it in mitmweb's Options or with `--set`; an empty list turns the format off.
- HLS: URI lines and `URI=` attributes (`EXT-X-KEY`, `EXT-X-MAP`, `EXT-X-MEDIA`, `EXT-X-I-FRAME-STREAM-INF`).
- JSON (`application/json`, `+json`, `.json`): string values that are absolute http(s) URLs; everything else is left exactly as the Origin sent it.
- DASH: `<BaseURL>`, `<Location>`, and `media`/`initialization`/`index`/`sourceURL` attributes.
- VAST / generic XML (`application/xml`, `text/xml`, `+xml`, `.xml`): every absolute http(s) URL in text, CDATA or attributes. Namespace names and schema locations are kept. A generic XML type yields to a format the URL extension names (a `.mpd` served as `text/xml` gets the DASH rewriter).
- Text (`text/*`, `application/javascript`): every absolute http(s) URL in HTML, JS, plain text or any other text type no format above claims; root-relative and relative URLs are left alone. Off unless the loaded App Profile's `profile.json` has `"rewrite_text": true` (restart the lab after changing it), for an app whose pages or scripts name the URLs it fetches next. Binary bodies are never touched.

### Device labels

Each flow's comment names its Target Device (mitmweb comment column; filter `~comment "Living Room"`). A Physical Device is named by its `ip` in your `devices.json`. A Cloud Device is named by the device slug in its Proxy Base, `https://<tunnel-host>/<secret>/<slug>`: `roxy launch` appends the device's `slug` from `devices.json` to the public Proxy Base. A tunnel request without a known slug whose `CF-Connecting-IP` is an RCE egress IP is labelled `Cloud Device`. Other clients get no label.

### Agents

The `roxy` skill teaches an agent in any app's repo when and how to use the lab: start it for the app, launch, write and set Scenarios, read the flows, and the known limits. It links to the guides rather than repeating them. Claude Code gets it from this checkout's plugin (after `./install.sh`, from the checkout):

```sh
claude plugin marketplace add "$PWD"
claude plugin install roxy@roxy
```

The plugin is a copy of the checkout: after a `git pull`, run `claude plugin update roxy@roxy`. It also puts its copy's `roxy` on the PATH of Claude's Bash tool; the terminal and Cursor use the one `install.sh` links.

Signed in to Cursor, its agent loads skills from installed Claude Code plugins, so it has the skill already. Without the plugin, link it: `mkdir -p ~/.cursor/skills && ln -sfn "$PWD/skills/roxy" ~/.cursor/skills/roxy`.

In each app's repo, add this pointer to its `AGENTS.md` (or `CLAUDE.md`), with the app's App Profile and how it routes; Claude Code and Cursor both read it:

```markdown
## roxy
To see what this app requests, or to make an Origin fail, slow down or answer from a mock, use the roxy lab: the `roxy` skill, or `skills/roxy/SKILL.md` in the roxy checkout (`realpath "$(command -v roxy)"` is its `bin/roxy`).
App Profile: `<profile>`. Routing: <its Charles hook, port 8888 | the kit, built with ROXY_KIT=1 or bs_const=roxy_kit=true>.
```

### Flows for agents

`roxy flows --json` prints the running lab's flows, so an agent can see what the app requested without opening mitmweb. It reads mitmweb's API with `MITMWEB_PASSWORD` and is read-only: it never holds, resumes or edits a flow. With the lab down it says so and exits non-zero; a filter expression mitmweb rejects and a wrong `MITMWEB_PASSWORD` each get their own error.

```sh
roxy flows --json                                       # every flow in mitmweb, oldest first
roxy flows --json --since 176363286012345               # since a roxy launch (its run=<id>)
roxy flows --json --since 2025-11-20T10:00:00Z          # since a time (ISO 8601; local time without an offset)
roxy flows --json --filter '~comment "Living Room" & ~d httpbin.org' --limit 20   # a mitmproxy filter expression; the last 20
```

`--filter` is applied by mitmweb, then `--since` and `--limit` (the last N flows). The output is one JSON array, one flow per line:

```json
[{"id": "35f7b2d8-754f-43c6-9044-607c1660affb", "time": "2025-11-20T10:02:00.000Z", "device": "Living Room", "method": "GET", "url": "https://httpbin.org/json", "status": 503, "request_bytes": 0, "response_bytes": 17, "duration_ms": 250, "refusal": null, "scenario_rules": ["httpbin json fails"]}]
```

| Field | Value |
| --- | --- |
| `id` | mitmweb's flow id |
| `time` | when the flow started, ISO 8601 UTC with milliseconds |
| `device` | its device label (Device labels), `null` for none |
| `method` | the request method |
| `url` | the Origin URL; for a request the lab could not decode (`not-prefixed`), the dummy reverse target |
| `status` | the status the client got, `null` without a response (dropped, failed) |
| `request_bytes`, `response_bytes` | body sizes as sent, `null` without that message |
| `duration_ms` | from the request's start to the response's end at the client (a `throttle` rule's pacing included), `null` without a complete response |
| `refusal` | the reason the lab refused it (its `X-Lab-Blocked` value, such as `origin-address`), `null` if it did not; an `X-Lab-Blocked` header from an Origin or a Scenario is not a refusal |
| `scenario_rules` | the names of the active Scenario's rules that acted on it, in the order they first did; `[]` for none |

### Recording and replay

Every session is saved in the saved-session folder, `~/.local/share/roxy/captures/<App Profile or no-profile>/<start time>.mitm`; open one with `mitmweb -r <file>`. With `--replay` (or `LAB_REPLAY` under Compose):

- A recorded request gets its recorded response every time; the Origin is not contacted. Replay is offline: an unrecorded request gets an empty 404 from the lab (`server_replay_extra=404`) and never reaches its Origin.
- Matching uses the Origin URL, so a session recorded from one Target Device replays to another; replayed URLs get the replaying client's Proxy Base.
- Guards still apply: a refused request stays refused.
- Record and replay in the same routing mode. A session recorded with Prefix Routing and replayed to a CA-routed client returns Prefixed URLs (Location, Set-Cookie paths, body URLs) of the recording client's Proxy Base: the lab adds no Proxy Base to CA-routed flows, so it does not undo them.

### CA Routing (Physical Devices only)

DNS on the router (a per-client DNS server such as AdGuard Home, answering every client's DNS) points lab Origins at the Mac, and a CA Routing build of the Lab App (classic or RSG 2.0) calls Origin URLs directly while trusting the lab's CA. mitmweb adds `reverse` listeners on 443 and 80, terminates TLS for the SNI it is given, and takes the Origin from Host/SNI. That holds for every non-Prefixed request while CA Routing is on, so an App Profile's [fallback Origin](#app-profiles) never applies.

```sh
scripts/start-lab --ca-routing                          # also listens on 443/80; Origin from Host/SNI
scripts/deploy --ca-routing "<device>" apps/classic     # Roku's CA bundle + the lab's CA on every agent
scripts/deploy --ca-routing "<device>" apps/rsg         # certifi's roots + the lab's CA, pkg:/ bundle, HttpsAgent per fetch
```

Known limits: the RSG 2.0 SDK cannot set certificates on Poster or on its Ads task, so those do not trust the lab's CA (`grid/cells.toml`, `known_limits`). Step by step, for any router and for apps with the kit: [CA Routing guide](docs/ca-routing.md).

### Cloud Device notes

- Cloudflare's terms require paid services to serve video through its network, and quick tunnels are for testing only (200 in-flight requests). Keep video over the Public Endpoint small and runs short.
- RCE costs about $0.20 per device-hour, Widevine is L3 only, and devices cannot be deleted.

### Locks

One person or agent at a time drives the Target Devices. `scripts/deploy`, `scripts/launch` and `scripts/grid` hold the `devices` lock while they run; `scripts/start-lab` holds the `lab` lock for its session. Both are per user (`~/.cache/roxy/locks/`), shared by every checkout and worktree. One lock covers every Target Device because the active Scenario is lab-wide.

- Held: the script stops at once, naming the holder (pid, command, and `LAB_LOCK_OWNER` if the holder set it). `LAB_LOCK_WAIT=1` waits for it instead.
- Agents: set `LAB_LOCK_OWNER` to your name, so a refusal tells the other side who to wait for.
- A grid cell's deploy and launches run inside the grid's lock. To hold it across your own commands, run them in one shell that takes it: `bash -c '. scripts/lib.sh && lab_lock devices && scripts/deploy "Living Room" apps/classic && scripts/launch "Living Room" case=json_get'`.
- A holder that died without releasing (crash, `kill -9`) is detected by its pid; the next script reclaims the lock.

### Tests

```sh
scripts/check                 # every check below, plus shell syntax, the lab lock, deploy and launch against a fake rce, settings and saved sessions against a fake mitmweb, the roxy CLI and install.sh against fake curl and rce in a temp HOME, the kit's example builds with and without its constant, compose config, the glossary lint and the test-import rule
cd proxy && uv run pytest     # Seam A: the full addon chain, no network
cd grid && uv run pytest      # grid verdict logic, its settings, and its Cloud Device side against a fake rce; no devices
```

No check reads your own settings: `scripts/check` points `ROXY_CONFIG_DIR` at a temp folder seeded from `settings.example/` (and the user data directory at another), and the pytest suites seed their own.

Live checks need the internet or a Target Device, so `scripts/check` leaves them out:

```sh
scripts/grid ...              # one grid cell on a Target Device (see Grid runner)
scripts/console <device> --launch <case>  # a Physical Device's console from connect to the run's result line, saved to out/console/ (instead of nc: no replay, no missed lines)
scripts/check-tunnel-reuse    # requests to one Origin over a reused connection to the tunnel listener, as cloudflared sends them; fails if one hangs. Uses the running lab or starts one; no Cloud Device, cloudflared or RCE
```

The pre-commit hook (`git config core.hooksPath .githooks`, once per clone) runs `scripts/check`. The glossary lint fails on any `_Avoid_` term of [GLOSSARY.md](GLOSSARY.md); a legitimate use goes in `scripts/glossary-allow.txt` with its reason, or carries `glossary-ok` on its line.
