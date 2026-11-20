# Roku MITM Lab

mitmproxy/mitmweb lab for inspecting and manipulating the traffic of Roku Lab Apps, on Physical Devices and on Roku Cloud Emulator (Cloud Devices). The Lab App calls Prefixed URLs (`<Proxy Base>/<original URL>`), so no device proxy setting or CA is needed.

- Design: [docs/design.md](docs/design.md). Vocabulary: [GLOSSARY.md](GLOSSARY.md). Decisions: [docs/adr/](docs/adr/).
- What works, what doesn't, and why: [docs/evaluation.md](docs/evaluation.md).
- CA Routing (phase 2, GL.iNet router): [docs/ca-routing.md](docs/ca-routing.md).

## Quickstart

### 1. Prerequisites

- macOS with [uv](https://docs.astral.sh/uv/) (installs the pinned mitmproxy 12.3.1 into `proxy/.venv`) and `brew install jq`.
- A Roku in developer mode on the same LAN as the Mac. Give the Mac a DHCP reservation so the LAN Proxy Base (`http://<mac-ip>:8080`) stays stable.
- Cloud Devices only: `brew install cloudflared` and the `rce` CLI (`~/projects/roku-rce`: `./install.sh`, docs in its README), which does every RCE call for the lab. Give the Cloud Device an rce Device Name and a Dev Snapshot once: `rce device alias <id> player`, `rce device setup-dev player`.
- RSG 2.0 Lab App only: Node 24+ (`brew install node@24`; `scripts/deploy` puts it first on PATH), pnpm 11, `brew install squashfs`.
- Compose only: Docker. It replaces uv and cloudflared.

### 2. Env setup

```sh
cp .env.example .env                     # never commit it
git config core.hooksPath .githooks      # pre-commit hook: runs scripts/check (see Tests)
```

| Key | Used for |
|---|---|
| `MITMWEB_PASSWORD` | mitmweb UI (listens on 127.0.0.1 only) |
| `ROKU_DEV_USER`, `ROKU_DEV_PASSWORD` | sideloading to Physical Devices (shared by all of them; a Cloud Device has its own dev password, kept by `rce`) |
| `LAB_SECRET` | secret path segment of the public Proxy Base (Cloud Devices) |

- Target Devices: `proxy/config/devices.json`, name to `{"ip": ...}` for a Physical Device or `{"rce_device_name": ..., "slug": ...}` for a Cloud Device (its rce Device Name, see `rce device list`; the scripts check it with `rce device resolve`).
- The RCE token is `rce`'s (`rce token set`), not the lab's. Delete an old `RCE_TOKEN` from `.env`: the scripts export `.env`, and `rce` takes `RCE_TOKEN` over its stored token.
- Guard defaults: `proxy/config/guards.json` (see [Guards](#guards)). Restart the lab after editing.

### 3. Start the lab

```sh
scripts/start-lab                    # mitmweb UI http://127.0.0.1:8081; prints the LAN Proxy Base
scripts/start-lab --tunnel           # plus the Public Endpoint for Cloud Devices: prints https://<random>.trycloudflare.com/<LAB_SECRET>
scripts/start-lab --replay captures/<session>.mitm   # answer from a saved session (see Recording and replay)
scripts/start-lab --ca-routing       # also listens on 443/80 (docs/ca-routing.md)
```

Ctrl-C stops mitmweb and the tunnel together. Every session is saved to `captures/<start time>.mitm`. The tunnel hostname changes on every start; its log is `out/cloudflared.log`.

### 4. Deploy and launch

```sh
scripts/deploy "Living Room" apps/classic                  # classic (BrightScript) Lab App
scripts/deploy "Living Room" apps/rsg                      # RSG 2.0 Lab App: pnpm install if needed, rk build --debug, sideload
scripts/launch "Living Room" json_get                      # prints run=<id>; the result line is on the debug console
nc -d 192.0.2.54 8085                                 # the console (-d, or nc sees only the replayed history)
```

Cloud Device (start the lab with `--tunnel`; launch needs the public Proxy Base). Deploy and launch go through `rce`, and need a running Cloud Device:

```sh
rce device start player                                  # billed from here, $0.20 per hour
scripts/deploy "Cloud Device" apps/classic               # rce sideload, with the Cloud Device's own dev password
scripts/launch "Cloud Device" json_get "https://<random>.trycloudflare.com/<LAB_SECRET>"
rce console player --until 'LABRESULT json_get' --timeout 60
rce device stop player                                   # billing ends here
```

Cases (same ids, labels and Origins in both flavours, also in an on-screen menu): `json_get`, `redirect`, `json_post`, `image`, `hls`, `dash`, `widevine`, `raf`; classic also has `uuid` (new data on each request, to prove replay). Launched without a Proxy Base, the app uses the LAN Proxy Base it was built with.

**Result lines** (one per run; the console replays recent history on connect, so match on `run=<id>`):

- Requests: `LABRESULT <case> run=<id> status=<code> bytes=<n> fp=<first 12 hex digits of the sha1>`. `json_post` adds `sentfp=` (equal to `fp` = the body arrived intact). `image` reports `status`, `prefixed=<yes|no>` (the catalog's image URL came back as a Prefixed URL) and `poster=<ready|failed>`.
- Playback (`hls`, `dash`, `widevine`): `state=<playing|error|finished|timeout_<state>> errorCode=<n> bitrate=<first video segment bps>`. `widevine` adds `license=`: `2` once the license is acquired (Roku OS 16), the license server's HTTP status when it fails, `none` if none was requested. A playback error also prints `LABERROR <case> run=<id> <errorStr>` (diagnostic only).
- `raf`: one RAF ad break from Google's sample VAST wrapper tag, as a Prefixed URL: `outcome=<completed|no_ads|exited> ads= impressions= completes= errors= media=<lab|direct|none>` (`media`: the first creative is a Prefixed URL). RAF's own `[RAF] fireBeacon(...)` log is on the console. In the RSG app, `impressions`, `completes` and `errors` are `na`: the SDK's `@roku-sdk/ads` task has no tracking callback, so count beacons in mitmweb.
- RSG lines start with `[TS]: ` and carry colour codes; match on `LABRESULT`. A release `rk build` strips `console.*`, so always build with `--debug`. By hand: `cd apps/rsg && LAB_PROXY_BASE=http://<mac-ip>:8080 ./node_modules/.bin/rk build --debug --local`.

### 5. Scenarios

A scenario is a file of named Manipulation rules, `proxy/scenarios/<name>.toml`. One is active at a time, lab-wide, for every Target Device:

```sh
scripts/launch --scenario json-503 "Living Room" json_get     # set it, then launch
scripts/launch --scenario '' "Living Room" json_get           # clear it
```

Or edit `lab_scenario` in mitmweb's Options. Editing the active file reloads it on the next request; a broken edit is logged and the last good rules stay. Shipped: `json-503`, `image-404`, `hls-404`, `dash-404`, `dash-absolute` (absolute `<BaseURL>`), `hls-lowest-variant`, `widevine-license-fail` (`state=error errorCode=-6 license=403`), `raf-ad-tag-drop` (`outcome=no_ads`; a status override alone is not enough, RAF reads a 503's VAST body).

Each rule has a `name`, a mitmproxy `filter` expression and exactly one action. Every matching rule applies, in file order. Flows the lab refused itself are never touched.

```toml
[[rule]]
name = "json fails"
filter = "~d httpbin.org & ~u /json"
status = 503                                    # status override (the Origin's body is kept)
# latency = 2.5                                 # seconds, before the request reaches the Origin
# drop = true                                   # close the connection, no answer, Origin not contacted
# header = { name = "Cache-Control", value = "no-store" }   # replace; "" removes (mitmproxy modify_headers)
# body = { pattern = "regex", replacement = "text" }        # regex replace (mitmproxy modify_body)
# map_local = "mocks/json.json"                 # answer from a file next to the scenario (mitmproxy map_local)
```

`header` and `body` act on the request and the response, like their mitmproxy built-ins: add `~q` or `~s` to the filter to pick one.

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
scripts/grid <classic|rsg> <physical|cloud> <json|json_post|image|hls|dash|widevine|raf> [--proxy-base URL] [--ca-routing]
scripts/grid classic physical json
scripts/grid rsg cloud hls --proxy-base "https://<random>.trycloudflare.com/<LAB_SECRET>"
scripts/grid classic physical json --ca-routing   # CA Routing on the GL.iNet: docs/ca-routing.md
```

It fills one evaluation cell through the running native lab (`scripts/start-lab`, not Compose): it deploys the flavour, launches the case with the cell's Manipulation scenario and then with none (so the lab ends with no scenario), and prints one row: pass, fail or known-limit, with a reason. Each launch's console and flows are kept in `out/grid/` as evidence for the verdict. Cells live in `grid/cells.toml`: per traffic class, the case, the scenario, the expected Origin hosts and the result fields that mean success. A Cloud Device cell prints the projected RCE time and cost (about 5.3 min, $0.018, start-up included) and asks before it touches RCE. It then starts the Cloud Device if it has no Run, reads its console with `rce console`, and stops it after the cell, also when the cell fails or on Ctrl-C or a kill (during the start too), then confirms with `rce device status` that the Run ended; a Run that was already going is left running.

- **Pass:** the run without a scenario succeeded, every expected Origin host showed up in that run's flows from the Target Device, the lab refused nothing, and the scenario changed the result line.
- **Leaks** can only be inferred, since traffic that bypasses the lab never reaches mitmweb: an expected host is missing although the Lab App reports success, or the console prints an absolute URL that is not a Prefixed URL. A bypassing request to a host outside the expected hosts, one the result does not depend on (a beacon, a prefetch), and Roku OS traffic go unseen.
- No result line before the timeout: rerun the cell (an RSG launch crash is possible). A `raf` baseline of `no_ads` is a known flake of Google's sample ad server: rerun. If a run errors part-way, its scenario stays active: clear it with `--scenario ''`.

### 7. Docker Compose

The same addons, config, scenarios and mitmweb flags (`scripts/run-mitmweb`), mounted from the repo; no Python or cloudflared to install. Secrets come from the same `.env`.

```sh
docker compose up                       # LAN listener on :8080, mitmweb UI on http://127.0.0.1:8081
docker compose --profile tunnel up      # plus the quick tunnel, for Cloud Devices
curl -s 127.0.0.1:20241/quicktunnel     # the tunnel's hostname: public Proxy Base https://<hostname>/<LAB_SECRET>
docker compose --profile tunnel down    # stops both, closing the Public Endpoint
LAB_REPLAY=captures/<session>.mitm docker compose up    # replay (path relative to the repo)
```

- `scripts/deploy` and `scripts/launch` work as above with the LAN Proxy Base `http://<this machine's LAN IP>:8080`. The grid runner does not run under Compose.
- Docker Desktop (macOS) hides the client IP: every LAN client shows as `192.168.65.1`. `compose.yaml` therefore sets `LAB_LAN_SUBNETS` (read by `scripts/run-mitmweb`) to the LAN subnet plus `192.168.65.1/32`; the native lab's default `lan_subnets` does not include it. The tradeoff: under Compose on macOS the LAN subnet guard lets in whatever can reach port 8080, and Physical Devices get no device label. On Linux the real client IP shows: set `LAB_LAN_SUBNETS` in `.env` to your LAN subnet alone to drop the Docker Desktop address.
- Linux: the container runs as uid 1000, so `captures/` must be writable by it (`chmod a+w captures/` if your uid differs).
- cloudflared dials the unpublished tunnel listener (`mitmweb:8082`) over the Compose network, so a LAN client cannot pass for the tunnel. CA Routing is not wired into Compose.

## Reference

### Guards

The lab forwards a request only if the client is allowed, the Origin host is on the allowlist, and the Origin resolves to public addresses only. Anything else gets a 403 from the lab with an `X-Lab-Blocked` reason (`secret-segment`, `client-ip`, `origin-host`, `origin-address`) and is marked in mitmweb (filter `~marked`). A non-Prefixed request gets 400 `not-prefixed`; through the tunnel it gets 403 `secret-segment`, so a scanner learns nothing.

- A LAN client must be on the LAN subnet.
- A request through the tunnel (it arrives on the tunnel listener, port 8082, which only cloudflared can reach) needs the secret path segment, and its `CF-Connecting-IP` must be one of the RCE egress IPs. Tunnel headers are trusted only there: a LAN client sending them is judged by its real IP.
- The address guard resolves the Origin, and mitmproxy then dials one of the addresses it checked (IPv4 first), never a later DNS answer: a name that turns private between the check and the connect (DNS rebinding) is not dialled. The cost: no server connection reuse across requests.
- Tunnel and forwarding headers (`CF-*`, `X-Forwarded-*`, `CDN-Loop`, `Forwarded`, `Via`...) never reach the Origin.
- Secrets on the command line: `scripts/run-mitmweb` passes `MITMWEB_PASSWORD` and `LAB_SECRET` to mitmweb as `--set` flags, so any local user can read them with `ps`. Accepted for a single-user lab Mac; do not run the lab on a shared machine.
- Defaults: `guards.json` (`lan_subnets`, `rce_egress_ips`, `origin_allowlist`; a leading dot such as `.mux.com` allows any subdomain). Live changes: mitmweb Options `lab_lan_subnets`, `lab_rce_egress_ips`, `lab_origin_allowlist`.

### Header and body rewriting

URLs in response headers (Location, Content-Location, Link, Refresh) and bodies become Prefixed URLs with the client's Proxy Base, so follow-up requests (segments, images, ads) come back through the lab. Set-Cookie is scoped to the Prefixed path. The body rewriter is chosen by content type, falling back to the URL extension; anything else passes byte for byte.

- Each format has an option `lab_rewrite_<format>` (`hls`, `dash`, `json`, `xml`) listing its content types and `.ext` extensions. Change it in mitmweb's Options or with `--set`; an empty list turns the format off.
- JSON: string values that are absolute http(s) URLs; everything else is left exactly as the Origin sent it.
- DASH: `<BaseURL>`, `<Location>`, and `media`/`initialization`/`index`/`sourceURL` attributes.
- VAST / generic XML (`application/xml`, `text/xml`, `.xml`): every absolute http(s) URL in text, CDATA or attributes. Namespace names and schema locations are kept. A generic XML type yields to a format the URL extension names (a `.mpd` served as `text/xml` gets the DASH rewriter).

### Device labels

Each flow's comment names its Target Device (mitmweb comment column; filter `~comment "Living Room"`). A Physical Device is named by its `ip` in `devices.json`. A Cloud Device is named by the device slug in its Proxy Base, `https://<tunnel-host>/<secret>/<slug>`: `scripts/launch` appends the device's `slug` from `devices.json` to the public Proxy Base you give it. A tunnel request without a known slug whose `CF-Connecting-IP` is an RCE egress IP is labelled `Cloud Device`. Other clients get no label.

### Recording and replay

Every session is saved to `captures/<start time>.mitm` (gitignored); open one with `mitmweb -r <file>`. With `--replay` (or `LAB_REPLAY` under Compose):

- A recorded request gets its recorded response every time; the Origin is not contacted. Replay is offline: an unrecorded request gets an empty 404 from the lab (`server_replay_extra=404`) and never reaches its Origin.
- Matching uses the Origin URL, so a session recorded from one Target Device replays to another; replayed URLs get the replaying client's Proxy Base.
- Guards still apply: a refused request stays refused.
- Record and replay in the same routing mode. A session recorded with Prefix Routing and replayed to a CA-routed client returns Prefixed URLs (Location, Set-Cookie paths, body URLs) of the recording client's Proxy Base: the lab adds no Proxy Base to CA-routed flows, so it does not undo them.

### CA Routing (phase 2, Physical Devices only)

DNS on the GL.iNet router points lab Origins at the Mac, and a CA Routing build of the Lab App (classic or RSG 2.0) calls Origin URLs directly while trusting the lab's CA. Setup and limits: [docs/ca-routing.md](docs/ca-routing.md).

```sh
scripts/start-lab --ca-routing                          # also listens on 443/80; Origin from Host/SNI
scripts/deploy --ca-routing "<device>" apps/classic     # Roku's CA bundle + the lab's CA on every agent
scripts/deploy --ca-routing "<device>" apps/rsg         # certifi's roots + the lab's CA, pkg:/ bundle, HttpsAgent per fetch
```

### Cloud Device notes

- Cloudflare's terms require paid services to serve video through its network, and quick tunnels are for testing only (200 in-flight requests). Keep video over the Public Endpoint small (see [docs/evaluation.md](docs/evaluation.md)).
- RCE costs about $0.20 per device-hour, Widevine is L3 only, and devices cannot be deleted.

### Locks

One person or agent at a time drives the Target Devices. `scripts/deploy`, `scripts/launch` and `scripts/grid` hold the `devices` lock while they run; `scripts/start-lab` holds the `lab` lock for its session. Both are per user (`~/.cache/mitm-lab/locks/`), shared by every checkout and worktree. One lock covers every Target Device because the active scenario is lab-wide.

- Held: the script stops at once, naming the holder (pid, command, and `LAB_LOCK_OWNER` if the holder set it). `LAB_LOCK_WAIT=1` waits for it instead.
- Agents: set `LAB_LOCK_OWNER` to your name, so a refusal tells the other side who to wait for.
- A grid cell's deploy and launches run inside the grid's lock. To hold it across your own commands, run them in one shell that takes it: `bash -c '. scripts/lib.sh && lab_lock devices && scripts/deploy "Living Room" apps/classic && scripts/launch "Living Room" json_get'`.
- A holder that died without releasing (crash, `kill -9`) is detected by its pid; the next script reclaims the lock.

### Tests

```sh
scripts/check                 # every check below, plus shell syntax, the lab lock, deploy and launch against a fake rce, compose config, the glossary lint and the test-import rule
cd proxy && uv run pytest     # Seam A: the full addon chain, no network
cd grid && uv run pytest      # grid verdict logic, and its Cloud Device side against a fake rce; no devices
```

Live checks need the internet or a Target Device, so `scripts/check` leaves them out:

```sh
scripts/grid ...              # one evaluation cell on a Target Device (see Grid runner)
scripts/console <device> --launch <case>  # a Physical Device's console from connect to the run's result line, saved to out/console/ (instead of nc: no replay, no missed lines)
scripts/check-tunnel-reuse    # requests to one Origin over a reused connection to the tunnel listener, as cloudflared sends them; fails if one hangs. Uses the running lab or starts one; no Cloud Device, cloudflared or RCE
```

The pre-commit hook (`git config core.hooksPath .githooks`, once per clone) runs `scripts/check`. The glossary lint fails on any `_Avoid_` term of [GLOSSARY.md](GLOSSARY.md); a legitimate use goes in `scripts/glossary-allow.txt` with its reason, or carries `glossary-ok` on its line.
