# Troubleshooting

Symptom, cause, fix. Each entry links to the page that explains it in full. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

## The lab refused a request

A refused request is marked ⛔ in mitmweb, carries an `X-Lab-Blocked` header, and shows as `refusal` in `roxy flows --json`. Full rules: [Guards](guards.md).

| Refusal | Cause | Fix |
|---|---|---|
| `403 secret-segment` | Through the tunnel, the request lacks the secret path segment, or is not a Prefixed URL behind it. | Launch with `roxy launch`, which sends the real public Proxy Base. Pasting by hand: `roxy status --show-secret`. The tunnel hostname changes on every `roxy start`: relaunch after a restart. |
| `403 client-ip` | On the LAN, the client is not on your `lan_subnets`. Through the tunnel, its `CF-Connecting-IP` is not one of the RCE egress IPs. | Add the subnet to `lan_subnets` ([Settings](settings.md)) and restart the lab. RCE egress IPs may change: add the new one with mitmweb's `lab_rce_egress_ips` option, then in `proxy/config/guards.json`. |
| `403 origin-host` | Through the tunnel, the Origin host is not on the allowlist. | Add it to the App Profile's `origin_allowlist` (a leading dot allows any subdomain) and restart ([App Profiles](settings.md#app-profiles)). |
| `403 origin-address` | The Origin resolves to a private, loopback, link-local or unique-local address. | By design: the lab never reaches private Origins, `map_remote` targets included. |
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

**Cause:** the flow is HTTP/2: it shares its connection with other flows, so it is sent unthrottled, and the mitmweb event log says so. CA-routed flows from a Roku are usually HTTP/2; Prefixed URL flows stay HTTP/1.1.
**Fix:** throttle over Prefix Routing ([Scenarios](scenarios.md), [CA Routing guide](ca-routing.md)).

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
