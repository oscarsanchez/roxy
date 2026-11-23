# Troubleshooting

Symptom, cause, fix. Each entry links to the page that explains it in full. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

## The lab refused a request

A refused request is marked ⛔ in mitmweb, carries an `X-Lab-Blocked` header, and shows as `refusal` in `roxy flows --json`. Full rules: [Guards](guards.md).

| Refusal | Cause | Fix |
|---|---|---|
| `403 secret-segment` | Through the tunnel, the request lacks the secret path segment, or is not a Prefixed URL behind it. | Launch with `roxy launch`, which sends the real public Proxy Base. Pasting by hand: `roxy status --show-secret`. The tunnel hostname changes on every `roxy start`: relaunch after a restart. |
| `403 client-ip` | On the LAN, the client is not on your `lan_subnets`: a Mobile Device on another Wi-Fi network than the Mac's too. Through the tunnel, its `CF-Connecting-IP` is not one of the RCE egress IPs. | Add the subnet to `lan_subnets` ([Settings](settings.md)) and restart the lab, or join the Mobile Device to the Mac's LAN ([Mobile Devices](mobile-devices.md#before-you-start)). RCE egress IPs may change: add the new one with mitmweb's `lab_rce_egress_ips` option, then in `proxy/config/guards.json`. |
| `403 origin-host` | Through the tunnel, the Origin host is not on the allowlist. | Add it to the App Profile's `origin_allowlist` (a leading dot allows any subdomain) and restart ([App Profiles](settings.md#app-profiles)). |
| `403 origin-address` | The Origin resolves to a private, loopback, link-local or unique-local address. | By design: the lab never reaches private Origins, `map_remote` targets included. A `This Mac` flow to `127.0.0.1`: see [mitmweb says `lab refused: origin-address`](#mitmweb-says-lab-refused-origin-address-while-the-macs-web-proxies-point-at-the-lab). |
| `400 not-prefixed` | A request reached a LAN listener with no Origin in its path: the app resolved a root-relative URL against the Proxy Base, or the app sent a URL without the Proxy Base. | Put the Proxy Base in front of that URL in the app ([Prefix Routing guide](prefix-routing.md)), or catch the bare path with the App Profile's [fallback Origin](settings.md#app-profiles). |

## `roxy start` stops before mitmweb starts

**Cause:** a settings file, a secret it needs (`MITMWEB_PASSWORD`; `LAB_SECRET` with `--tunnel`) or `lan_subnets` is missing. It names which. A bad App Profile `fallback_origin` or a profile Scenario named like one of the lab's own stops it too, naming the profile.
**Fix:** fill in the named setting in the settings root, or run `./install.sh` to seed missing files ([Settings](settings.md)).

## A Scenario seems to do nothing

**Cause:** its rule's filter matched no flow (the CDN moved hosts, a throttle matched no segment), the Scenario is not active, or its file no longer loads.
**Fix:** run `roxy status --since <run>` after the launch. A rule flagged `acted on nothing yet` needs a filter that matches: compare it with the `url` values in `roxy flows --json`. A Scenario that no longer loads shows why instead of its rules, and the last good rules stay. Not listed: `roxy scenario add <name>` ([Scenarios](scenarios.md)).

## A Scenario is still active after a failed run

**Cause:** a run that errors part-way leaves its Scenario set; Scenarios are lab-wide.
**Fix:** `roxy scenario clear`, or `roxy launch --scenario '' ...` ([Scenarios](scenarios.md)).

## A throttle is ignored

**Cause:** the flow is HTTP/2: it shares its connection with other flows, so it is sent unthrottled, and the mitmweb event log says so. CA-routed flows from a Roku and a Mobile Device's HTTPS flows are usually HTTP/2; Prefixed URL flows and plain HTTP flows stay HTTP/1.1.
**Fix:** throttle over Prefix Routing ([Scenarios](scenarios.md), [CA Routing guide](ca-routing.md)). A Mobile Device has no Prefix Routing: the lab cannot pace its HTTP/2 flows, but a `latency` rule still slows them ([Mobile Devices](mobile-devices.md#3-see-its-flows)).

## A Mobile Device shows no HTTPS flows, or its app reports TLS errors

**Cause:** the Mobile Device does not trust the lab's CA, so it ends each HTTPS connection at the TLS handshake, and the mitmweb event log says "The client does not trust the proxy's certificate for" the host. Plain HTTP flows still show. On iOS and iPadOS, the CA profile is often installed but not fully trusted; an iOS Simulator needs the CA added; on Android, see the next entry.
**Fix:** with the proxy set, install the CA from `http://mitm.it`; on iOS and iPadOS, also turn on full trust in Certificate Trust Settings ([Mobile Devices](mobile-devices.md#2-install-and-trust-the-labs-ca)). On an iOS Simulator, `xcrun simctl keychain booted add-root-cert ~/.mitmproxy/mitmproxy-ca-cert.pem` ([iOS Simulator](mobile-devices.md#ios-simulator)).

## An Android build's HTTPS fails, though the CA is installed

**Cause:** since Android 7, apps ignore CAs the user installed unless their network security config opts in. Chrome trusts the CA, so `mitm.it` and websites work while the app's HTTPS requests fail, with the same event log line.
**Fix:** let the debug build trust user CAs (`<certificates src="user" />` under `debug-overrides` in its network security config), then rebuild and reinstall it ([Mobile Devices](mobile-devices.md#android)).

## One app's HTTPS fails while other apps' works

**Cause:** the app pins its certificates: it accepts only its Origins' own, never one signed by the lab's CA, however trusted. Pinned apps are out of scope.
**Fix:** none in the lab. A debug build with pinning turned off goes through it ([Mobile Devices](mobile-devices.md#before-you-start)).

## mitmweb says `lab refused: origin-address` while the Mac's web proxies point at the lab

**Cause:** with the Mac's web proxies set to the lab (for an iOS Simulator), the browser sends its request for mitmweb on `127.0.0.1:8081` through the Proxy Routing listener, which refuses a loopback Origin `origin-address`. macOS's default bypass list holds only `*.local` and `169.254/16`. `roxy` itself never goes through a proxy.
**Fix:** add `127.0.0.1` and `localhost` to the bypass list (`networksetup -setproxybypassdomains Wi-Fi '*.local' 169.254/16 127.0.0.1 localhost`), or turn the web proxies off ([iOS Simulator](mobile-devices.md#ios-simulator)).

## `scripts/deploy`, `roxy launch` or `roxy console` says "not a Roku"

**Cause:** the device it names is a Mobile Device (`"kind": "mobile"` in `devices.json`): `'<name>' is a Mobile Device, not a Roku`. Deploys, launches, the console and the grid runner drive Rokus only, and refuse before any device or rce call.
**Fix:** name a Roku. A Mobile Device needs none of them: run the app with its own tooling, and its flows show as it sends them ([Settings](settings.md), [Mobile Devices](mobile-devices.md#3-see-its-flows)).

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
