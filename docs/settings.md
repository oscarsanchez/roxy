# Settings and App Profiles

Where your secrets, devices, LAN subnets and App Profiles live, and what each file holds. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

Your secrets, devices and LAN subnets live in the **settings root**, `~/.config/roxy/` (`$XDG_CONFIG_HOME/roxy` if you set that), never in the repo. The environment variable `ROXY_CONFIG_DIR` points the lab at another settings root, for tests or experiments. The install seeds each file the settings root lacks with nothing set yet: no devices, no LAN subnets, every secret empty. `roxy setup` and `roxy device` fill them in (below), or edit them by hand; `settings.example/` in the repo shows every field with made-up values.

| File | Holds |
|---|---|
| `secrets.env` | `NAME=value` lines, readable only by you: `MITMWEB_PASSWORD` (mitmweb UI), `LAB_SECRET` (secret path segment of the public Proxy Base, Cloud Devices), `ROKU_DEV_USER` and `ROKU_DEV_PASSWORD` (sideloading to Physical Devices; a Cloud Device's dev password is kept by `rce`) |
| `devices.json` | Target Devices by name: `{"ip": ...}` for a Physical Device, `{"rce_device_name": ..., "slug": ...}` for a Cloud Device (its rce Device Name, see `rce device list`; the scripts check it with `rce device resolve`), `{"ip": ..., "kind": "proxied"}` for a Proxied Device (no `kind` means a Roku; `"kind": "mobile"`, as roxy 0.2.0 wrote it, means a Proxied Device too; `scripts/deploy`, `roxy launch` and `roxy console` refuse a Proxied Device: not a Roku). `roxy device` edits it for you (see [Target Devices](#target-devices)) |
| `settings.json` | `lan_subnets`: the LAN subnets (CIDR) whose clients may use the LAN listeners and Proxy Routing; `roxy setup` allows this Mac (see [Setup](#setup)), and `roxy device add` and `remove` keep a device's `/32` in step. `grid_devices`: the Target Device the grid runner uses for each kind (`physical`, `cloud`, `ca-routing`) |
| `apps/<name>/` | App Profiles, made by `roxy app new` (see [App Profiles](#app-profiles)) |

- `roxy start` stops before mitmweb starts if a file or a secret it needs is missing, or `lan_subnets` is empty, naming each with the command that fills it in. An empty `devices.json` is only a warning: the lab still serves This Mac's own clients (iOS Simulator, Android Emulator, `curl`).
- Every settings file stays readable only by you: `roxy setup` and `roxy device` write each one whole, private to you.
- The RCE token is `rce`'s (`rce token set`), not the lab's. Keep `RCE_TOKEN` out of `secrets.env`: the scripts export it, and `rce` takes `RCE_TOKEN` over its stored token.
- The lab's own defaults, the same for everyone, stay in the repo: `proxy/config/guards.json` (RCE egress IPs and the Origin allowlist, see [Guards](guards.md)). Restart the lab after editing a setting.

## Setup

`roxy setup` fills the settings root for this Mac, keeping what is there: run it again any time.

```sh
roxy setup                                 # in a terminal: shows each value, Enter keeps it; then offers the Rokus it finds
roxy setup --trusted-network               # allow this Mac's whole subnet: every device on a network you trust, such as home
roxy setup --this-mac-only                 # back to this Mac's address only
roxy setup --cloud                         # Cloud Devices too: the lab secret, and rce and cloudflared checked
pbpaste | roxy setup --roku-password-stdin   # the Roku password from stdin, never a flag
```

- **Secrets.** It generates `MITMWEB_PASSWORD` when there is none, and with `--cloud` `LAB_SECRET` too. Both go to `secrets.env`, readable only by you, and are never printed; a re-run keeps them. When the mitmweb UI asks for its password, read it there (`roxy start` names the file).
- **Example values.** Values roxy 0.2.0's install seeded from `settings.example/` go: each device on a documentation range (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) and the examples' Cloud Device are unregistered, each with `removed the example device '<name>'`.
- **`lan_subnets`.** It drops each entry inside a documentation range (the examples' `192.0.2.0/24`, for instance). With nothing left but registered devices' `/32`s, it allows this Mac's address as a `/32` beside them: on a shared network, such as work, no one else can relay through your lab. `--trusted-network` allows the Mac's whole subnet instead. Either flag replaces `lan_subnets`, with a `/32` for each registered device's IP the new entry does not cover; without one, setup keeps the `lan_subnets` you have. In a terminal it asks (`t`: trust this network; `m`: this Mac only; Enter keeps).
- **Roku developer login.** `ROKU_DEV_USER` (`--roku-user`, default `rokudev`) and `ROKU_DEV_PASSWORD`, one for all your Rokus. The password comes from a hidden prompt in a terminal, or with `--roku-password-stdin` from the first line of stdin; never from a flag (`roxy setup --roku-password` is refused). Without a terminal and without `--roku-password-stdin`, setup never reads stdin. Without it, setup warns `no Roku developer password (ROKU_DEV_PASSWORD): ...`, and `scripts/deploy` to a Physical Device will need it.
- **Rokus.** In a terminal it then searches this network as `roxy device discover` does and offers each unregistered Roku: Enter registers it under its own name, as `roxy device add` would; type another name, or `n` to skip. Without a terminal it never asks and registers none.
- **Cloud Devices** (`--cloud`). It checks that `rce` is installed and `rce token status` works, and that `cloudflared` is installed, warning with what to do: `rce is not installed: install it as its README says, ...`, `rce token status fails: the user runs rce token set (pbpaste | rce token set)`, `cloudflared is not installed: brew install cloudflared ...`. With all three in place it says `rce and cloudflared installed, and rce token status works`.
- It prints what it set and kept, then warnings on stderr, and, when it changed something, ends reminding you to restart a running lab. It never touches `grid_devices`.

## Target Devices

`roxy device` registers your Target Devices in `devices.json` without editing JSON, and keeps `lan_subnets` in step. It never prompts, so an agent can run it too:

```sh
roxy device discover                                       # the Rokus on this network, with an add line for each new one
roxy device add "Living Room" --ip 192.0.2.54             # a Roku on your LAN: a Physical Device
roxy device add Phone --ip 192.0.2.60 --proxied           # a phone, tablet or TV box: a Proxied Device
roxy device add "Cloud Device" --rce player                # a Cloud Device, by its rce Device Name; slug cloud-device
roxy device add "Cloud Device" --rce player --slug desk    # the same, with the slug you choose
roxy device list                                           # each device, its IP or rce Device Name, and its kind
roxy device remove Phone
```

- `discover` searches this network for Rokus (SSDP, three searches over about 3 seconds, sent from the Mac's LAN address so a VPN does not take them) and asks each one's ECP, never through a proxy. It prints each Roku's IP, its own name, model, developer mode and the device it is registered as, and a ready `roxy device add "<its name>" --ip <ip>` line for each one not registered yet; it adds nothing itself. A Roku that is off or on another network, a VPN that keeps the search from the LAN, or a network that blocks discovery (many work and guest networks do) finds none: a Roku shows its IP in Settings → Network → About.
- `add` refuses a name that exists (one registered at another IP, say after the Roku's address changed, is named with that IP: `roxy device remove "<name>"` it first), an IP that is not one, and a slug that is taken or is not lowercase letters, digits and single dashes. A Cloud Device's slug, the last segment of its public Proxy Base, defaults to its name in lowercase with dashes.
- `add` asks a Roku's ECP (`http://<ip>:8060/query/device-info`, never through a proxy) and a Cloud Device's `rce device resolve`. A Roku that does not answer or is not in developer mode, or a Device Name `rce` does not know, is registered anyway with a warning: it may only be off, or on another network, today.
- `add` with an IP that no `lan_subnets` entry covers appends `<ip>/32` to them, and says so. `remove` drops a `/32` equal to the device's IP when no other device has that IP; it never touches a wider subnet, so a trusted network you allowed stays allowed.
- Both keep every other key and entry of both files (`grid_devices` included), and end by reminding you to restart a running lab: it reads them when it starts.

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
