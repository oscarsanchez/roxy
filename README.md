# roxy

A mitmproxy/mitmweb lab on your Mac for inspecting and manipulating the traffic of Roku apps, on Physical Devices and on Roku Cloud Emulator (Cloud Devices). The app calls Prefixed URLs (`<Proxy Base>/<Origin URL>`), so no device proxy setting or CA is needed.

Vocabulary: [GLOSSARY.md](GLOSSARY.md). Code conventions: [CODING_STANDARDS.md](CODING_STANDARDS.md). Changes: [CHANGELOG.md](CHANGELOG.md).

Issues are welcome on GitHub Issues; pull requests aren't accepted yet. To report a security problem, see [SECURITY.md](SECURITY.md). Licence: [MIT](LICENSE).

## Scope

- Every kind of Outbound Traffic: JSON APIs, images, HLS, DASH, Widevine licenses, RAF ads (VAST, VAST wrappers, VMAP) and their beacons.
- Inspection in mitmweb, and Manipulation: mocked or map-local responses, rewritten headers and bodies, injected faults (status, latency, drops), edited manifests, held-and-edited flows, and Recordings replayed or exported as HAR files.
- Two disposable Lab Apps (classic BrightScript/SceneGraph and RSG 2.0) exercise every traffic class and serve as the regression grid. Store apps and Roku OS's own traffic are out of scope.

## How it works

The app puts the Proxy Base in front of every URL it builds, `<Proxy Base>/<Origin URL>` (or `<Proxy Base>/;<Origin URL>`, as a Charles-enabled build does): this is Prefix Routing, and it works on every Target Device. The lab recovers the Origin, applies its guards, rewrites URLs in responses so follow-up requests come back through it, then applies the active Scenarios. CA Routing, for Physical Devices only, uses DNS and the lab's CA instead. The full picture: [How it works](docs/how-it-works.md).

## Quickstart

### 1. Prerequisites

- macOS with [uv](https://docs.astral.sh/uv/) (installs the pinned mitmproxy 12.3.1 into `proxy/.venv`) and `brew install jq`.
- A Roku in developer mode on the same LAN as the Mac.

Cloud Devices, the RSG 2.0 Lab App and Docker Compose need more: [Cloud Devices](docs/cloud-devices.md), [Lab Apps](docs/lab-apps.md), [Docker Compose](docs/compose.md).

### 2. Install and settings

```sh
git clone <roxy's repository URL> roxy && cd roxy
./install.sh                               # links roxy into ~/.local/bin (put that on your PATH); seeds missing settings
git config core.hooksPath .githooks        # pre-commit hook: runs scripts/check (see docs/tests.md)
```

`install.sh` links `bin/roxy` from this checkout, so `git pull` updates it, and `roxy` works from any terminal, Cursor's included. Run it again whenever you like: it refreshes the link and never overwrites a setting. It refuses, changing nothing, when `~/.local/bin/roxy` exists and is not a link. For an agent in an app's repo, add the plugin and a pointer too: [Agents](docs/agent-setup.md).

The install seeds your **settings root**, `~/.config/roxy/`, from `settings.example/`, and never overwrites a setting. Fill in `secrets.env`, `devices.json` and `settings.json`: [Settings and App Profiles](docs/settings.md).

### 3. Start the lab

```sh
roxy start                           # mitmweb UI http://127.0.0.1:8081; prints the Proxy IP and both LAN Proxy Bases
roxy start --tunnel                  # plus the Public Endpoint for Cloud Devices: prints https://<random>.trycloudflare.com/<secret>
roxy status                          # from another terminal: up or down (exit 1); Proxy IP, Proxy Bases, App Profile, active Scenarios and their rules
roxy flows --json --limit 20         # the last 20 flows as JSON, for agents (see docs/agent-setup.md)
```

`roxy --help` lists the subcommands and `roxy <subcommand> --help` gives every option of one; the docs show examples only. `roxy` is a thin dispatcher over `scripts/` (`roxy start` runs `scripts/start-lab`). The lab runs in the foreground: there is no daemon and no `stop`. Ctrl-C stops mitmweb and the tunnel together. Every Lab Session is saved as a Recording in your user data directory, `~/.local/share/roxy/captures/<App Profile>/<start time>.mitm`, or `captures/no-profile/` without one (`$XDG_DATA_HOME/roxy/...` if you set that). The tunnel hostname changes on every start; its log is `out/cloudflared.log`.

### 4. Deploy and launch

Device names come from your `devices.json`; these examples use the example names.

```sh
scripts/deploy "Living Room" apps/classic                # classic (BrightScript) Lab App
roxy launch "Living Room" case=json_get                  # prints run=<id>; the result line is on the debug console
roxy console "Living Room" --launch json_get             # the console from connect to the run's result line, saved to out/console/
```

`roxy launch <device> [key=value...]` launches the dev channel with `proxyBase`, your launch params, and a fresh `run` id; it never builds or sideloads. `proxyBase` goes by kind of Target Device: the LAN Proxy Base for a Physical Device, the running tunnel's public Proxy Base plus the device slug for a Cloud Device. `--proxy-base URL` sends another. The Lab Apps read `case`; a Product App reads whatever params it takes.

Cases and result lines: [Lab Apps](docs/lab-apps.md). On a Cloud Device: [Cloud Devices](docs/cloud-devices.md).

## Documentation

Everything else, as how-tos, reference and explanation: [docs/README.md](docs/README.md).
