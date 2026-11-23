# Troubleshooting

Symptom, cause, fix. Each entry links to the page that explains it in full. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

## The lab refused a request

A refused request is marked ⛔ in mitmweb, carries an `X-Lab-Blocked` header, and shows as `refusal` in `roxy flows --json`. Full rules: [Guards](guards.md).

| Refusal | Cause | Fix |
|---|---|---|
| `403 secret-segment` | Through the tunnel, the request lacks the secret path segment, or is not a Prefixed URL behind it. | Launch with `roxy launch`, which sends the real public Proxy Base. Pasting by hand: `roxy status --show-secret`. The tunnel hostname changes on every `roxy start`: relaunch after a restart. |
| `403 client-ip` | On the LAN, the client is not on your `lan_subnets`: a Proxied Device on another Wi-Fi network than the Mac's too. Through the tunnel, its `CF-Connecting-IP` is not one of the RCE egress IPs. | Register the device, `roxy device add NAME --ip IP` (`--proxied` for a Proxied Device), which allows its IP in `lan_subnets`, or on a network you trust `roxy setup --trusted-network`; then restart the lab ([Settings](settings.md#setup)). Or join the Proxied Device to the Mac's LAN ([Proxied Devices](proxied-devices.md#before-you-start)). RCE egress IPs may change: add the new one with mitmweb's `lab_rce_egress_ips` option, then in `proxy/config/guards.json`. |
| `403 origin-host` | Through the tunnel, the Origin host is not on the allowlist. | Add it to the App Profile's `origin_allowlist` (a leading dot allows any subdomain) and restart ([App Profiles](settings.md#app-profiles)). |
| `403 origin-address` | The Origin resolves to a private, loopback, link-local or unique-local address. | By design: the lab never reaches private Origins, `map_remote` targets included. A `This Mac` flow to `127.0.0.1`: see [mitmweb says `lab refused: origin-address`](#mitmweb-says-lab-refused-origin-address-while-the-macs-web-proxies-point-at-the-lab). |
| `400 not-prefixed` | A request reached a LAN listener with no Origin in its path: the app resolved a root-relative URL against the Proxy Base, or the app sent a URL without the Proxy Base. | Put the Proxy Base in front of that URL in the app ([Prefix Routing guide](prefix-routing.md)), or catch the bare path with the App Profile's [fallback Origin](settings.md#app-profiles). |

## `roxy start` stops before mitmweb starts

**Cause:** a settings file or a secret it needs (`MITMWEB_PASSWORD`; `LAB_SECRET` with `--tunnel`) is missing, or `lan_subnets` is empty, as `./install.sh` leaves them. It names each, in one run, with the command that fills it in:
```
error: missing secrets in .../roxy/secrets.env: MITMWEB_PASSWORD (roxy setup generates them; roxy setup --cloud for LAB_SECRET)
error: missing setting lan_subnets (the LAN subnets allowed to use the lab, CIDR) in .../roxy/settings.json (roxy setup sets them for this Mac's network)
```
An empty `devices.json` only warns (`warning: no Target Devices in ...`): the lab still serves This Mac's own clients, such as the iOS Simulator, the Android Emulator and `curl`.
A bad App Profile `fallback_origin` or a profile Scenario named like one of the lab's own stops it too, naming the profile.
**Fix:** run the command it names: `roxy setup` (`--cloud` for `LAB_SECRET`), then `roxy device add` or `roxy device discover` for a Roku or a Proxied Device. A missing file: run `./install.sh` to seed it ([Settings](settings.md#setup)).

## `roxy start` says the lab lock is held

```
error: the lab lock is held by pid 4211 since 2026-11-23 09:00:00: bash .../scripts/start-lab. Retry later, or wait with LAB_LOCK_WAIT=1
```
**Cause:** a lab is already running for this user, in another terminal or another checkout: one lab per user. The start checks the lock before its ports, so it names the running lab rather than the ports that lab holds.
**Fix:** use the running lab (`roxy status`), or stop it (Ctrl-C in its terminal) and start again.

## `roxy start` says a port is in use

**Cause:** another process listens on a port the lab needs: 8080 or 8888 (the LAN listeners; 8888 is Charles's port), 8090 (Proxy Routing), 8081 (the mitmweb UI), 8082 (the tunnel listener), or with `--ca-routing` 443 and 80. Often Charles, a lab already running in another terminal, or `docker compose up`. The start stops before mitmweb starts, naming every busy port in one run, its role, and the process holding it:
```
error: port 8888 (Charles's port, the second LAN listener) is in use by Charles (pid 4211): quit it, then start again (docs/troubleshooting.md)
```
A process of another user (a root process on 443 or 80) is named by the port alone, with the `sudo lsof` command that names it.
**Fix:** quit that process (`docker compose down` stops the Compose lab; a roxy lab already running is named by its lock instead, above), then start again. The ports are fixed.

## `roxy start` or `roxy setup` warns that a VPN holds the default route

```
warning: a VPN holds the default route: Rokus reach the lab only if it allows local LAN access (split tunnel); otherwise disconnect it while you use the lab
```
**Cause:** a VPN is connected on the Mac (its interface is `utun`, `ipsec`, `ppp`, `tun`, `tap` or `gpd`). The Proxy IP, the LAN Proxy Bases, the address setup allows in `lan_subnets` and the address `roxy device discover` searches from are still the Mac's own: the first active Wi-Fi or Ethernet interface in macOS's network service order (System Settings → Network → ⋯ → Set Service Order), never the VPN's, and never iPhone or iPad USB tethering, Bluetooth PAN or Thunderbolt Bridge, which do not reach a Roku's LAN. But a VPN that sends all traffic through its tunnel drops the replies to devices on the LAN, so Rokus and Proxied Devices time out against the lab.
**Fix:** allow local LAN access in the VPN's settings (split tunnel), or disconnect it while you use the lab. Nothing to change in roxy; the start and setup go on ([Prefix Routing](prefix-routing.md)).

## `roxy setup` warns

Setup still finishes; each warning says what is left:

- `no Roku developer password (ROKU_DEV_PASSWORD)`: it had no terminal to ask in, and no `--roku-password-stdin`. Run `roxy setup` in a terminal, or pipe the password to `roxy setup --roku-password-stdin`. An agent leaves this to you.
- `could not find this Mac's address: lan_subnets left as they are`: the Mac is on no network. Join one and run it again.
- `rce is not installed`, `rce token status fails` or `cloudflared is not installed` (`--cloud`): install it, or set the token with `rce token set` ([Cloud Devices](cloud-devices.md#prerequisites)).
- `<ip> not registered: ...`: a Roku it offered took a name that exists; `roxy device add` it under another name. When that name is registered at another IP (the Roku's address changed), the warning names it: `roxy device remove "<name>"`, then run setup again or `roxy device add` it.
- A Roku that `did not answer ECP` or `is not in developer mode`: registered anyway; turn it on, or turn on developer mode before `scripts/deploy`. The same goes for `roxy device add`.

## A flow is marked double-prefixed

Its mitmweb comment ends in `double-prefixed`, and `roxy flows --json` shows `"double_prefixed": true`. The flow itself succeeded.
**Cause:** the app put the Proxy Base in front of a URL that already had it (a Nested Prefixed URL): its Charles hook or URL wrapper runs on every URL, including ones the lab already rewrote in a response, or a config value already carries the Proxy Base. The lab strips the extra Proxy Base and serves the real Origin, as Charles does over two hops ([Nested Prefixed URLs](prefix-routing.md#nested-prefixed-urls)).
**Fix:** in the app, fix the "already prefixed?" check, so a URL that starts with the Proxy Base, in either form (`/` or `/;`), is left alone. The kit does this already ([The kit](prefix-routing.md#the-kit-apps-without-a-charles-hook)). A nested Prefixed URL with another Proxy Base is not unwrapped: it shows as a refusal (`origin-address`, or `origin-host` on the Public Endpoint).

## A Scenario seems to do nothing

**Cause:** its rule's filter matched no flow (the CDN moved hosts, a throttle matched no segment), the Scenario is not active, or its file no longer loads.
**Fix:** run `roxy status --since <run>` after the launch. A rule flagged `acted on nothing yet` needs a filter that matches: compare it with the `url` values in `roxy flows --json`. A Scenario that no longer loads shows why instead of its rules, and the last good rules stay. Not listed: `roxy scenario add <name>` ([Scenarios](scenarios.md)).

## A Scenario is still active after a failed run

**Cause:** a run that errors part-way leaves its Scenario set; Scenarios are lab-wide.
**Fix:** `roxy scenario clear`, or `roxy launch --scenario '' ...` ([Scenarios](scenarios.md)).

## A throttle is ignored

**Cause:** the flow is HTTP/2: it shares its connection with other flows, so it is sent unthrottled, and the mitmweb event log says so. CA-routed flows from a Roku and a Proxied Device's HTTPS flows are usually HTTP/2; Prefixed URL flows and plain HTTP flows stay HTTP/1.1.
**Fix:** throttle over Prefix Routing ([Scenarios](scenarios.md), [CA Routing guide](ca-routing.md)). A Proxied Device has no Prefix Routing: the lab cannot pace its HTTP/2 flows, but a `latency` rule still slows them ([Proxied Devices](proxied-devices.md#3-see-its-flows)).

## A Proxied Device shows no HTTPS flows, or its app reports TLS errors

**Cause:** the Proxied Device does not trust the lab's CA, so it ends each HTTPS connection at the TLS handshake, and the mitmweb event log says "The client does not trust the proxy's certificate for" the host. Plain HTTP flows still show. On iOS and iPadOS, the CA profile is often installed but not fully trusted; an iOS Simulator needs the CA added; on Android, see the next entry.
**Fix:** with the proxy set, install the CA from `http://mitm.it`; on iOS and iPadOS, also turn on full trust in Certificate Trust Settings ([Proxied Devices](proxied-devices.md#2-install-and-trust-the-labs-ca)). On an iOS Simulator, `xcrun simctl keychain booted add-root-cert ~/.mitmproxy/mitmproxy-ca-cert.pem` ([iOS Simulator](proxied-devices.md#ios-simulator)).

## An Android build's HTTPS fails, though the CA is installed

**Cause:** since Android 7, apps ignore CAs the user installed unless their network security config opts in. Chrome trusts the CA, so `mitm.it` and websites work while the app's HTTPS requests fail, with the same event log line.
**Fix:** let the debug build trust user CAs (`<certificates src="user" />` under `debug-overrides` in its network security config), then rebuild and reinstall it ([Proxied Devices](proxied-devices.md#android)).

## One app's HTTPS fails while other apps' works

**Cause:** the app pins its certificates: it accepts only its Origins' own, never one signed by the lab's CA, however trusted. Pinned apps are out of scope.
**Fix:** none in the lab. A debug build with pinning turned off goes through it ([Proxied Devices](proxied-devices.md#before-you-start)).

## mitmweb says `lab refused: origin-address` while the Mac's web proxies point at the lab

**Cause:** with the Mac's web proxies set to the lab (for an iOS Simulator), the browser sends its request for mitmweb on `127.0.0.1:8081` through the Proxy Routing listener, which refuses a loopback Origin `origin-address`. macOS's default bypass list holds only `*.local` and `169.254/16`. `roxy` itself never goes through a proxy.
**Fix:** add `127.0.0.1` and `localhost` to the bypass list (`networksetup -setproxybypassdomains Wi-Fi '*.local' 169.254/16 127.0.0.1 localhost`), or turn the web proxies off ([iOS Simulator](proxied-devices.md#ios-simulator)).

## `scripts/deploy`, `roxy launch` or `roxy console` says "not a Roku"

**Cause:** the device it names is a Proxied Device (`"kind": "proxied"`, or `"mobile"` from roxy 0.2.0, in `devices.json`): `'<name>' is a Proxied Device, not a Roku`. Deploys, launches, the console and the grid runner drive Rokus only, and refuse before any device or rce call.
**Fix:** name a Roku. A Proxied Device needs none of them: run the app with its own tooling, and its flows show as it sends them ([Settings](settings.md), [Proxied Devices](proxied-devices.md#3-see-its-flows)).

## No result line before the timeout

**Cause:** the launch crashed (possible with the RSG 2.0 Lab App), or an RSG 2.0 build was made without `--debug`, which strips `console.*`.
**Fix:** rerun. Build RSG 2.0 with `rk build --debug` ([Lab Apps](lab-apps.md), [Grid runner](grid.md)).

## `raf` or `raf_vmap` baseline says `outcome=no_ads`

**Cause:** a known flake of Google's sample ad server.
**Fix:** rerun the cell ([Grid runner](grid.md)).

## A Physical Device cannot be reached

**Cause:** the Mac is on another network than the device. The grid runner stops before the deploy, naming the device. The Mac's LAN IP may also have changed, which changes the LAN Proxy Base a build carries as its default.
**Fix:** join the device's network, or fill the cells on a reachable device with `--device NAME`. Give the Mac a DHCP reservation; `roxy launch` always sends the current Proxy Base ([Grid runner](grid.md), [How it works](how-it-works.md)).

## A script stops at once, naming a lock holder

**Cause:** another person or agent holds the `devices` or `lab` lock.
**Fix:** wait, or set `LAB_LOCK_WAIT=1` to wait for it. A holder that died is detected by its pid and the lock reclaimed ([Locks](locks.md)).

## `roxy flows` fails

**Cause:** the lab is down, `MITMWEB_PASSWORD` is wrong, or mitmweb rejected the `--filter` expression. Each has its own error.
**Fix:** `roxy status` to check the lab is up; fix the password in `secrets.env`; fix the filter ([Agents](agent-setup.md#flows-for-agents)).

## `./install.sh` refuses

**Cause:** `~/.local/bin/roxy` exists and is not a link; the install changes nothing.
**Fix:** move that file away and run it again.
