# CA Routing guide

How a Roku app's Outbound Traffic reaches the lab with no Prefixed URL at all: DNS on your router points the app's Origins at the Mac, and the app trusts the lab's certificate authority. Physical Devices only (a Cloud Device's DNS is Roku's). Vocabulary: `GLOSSARY.md`. Prefix Routing keeps working alongside it; its guide is `docs/prefix-routing.md`.

```
Roku --DNS: api.example?--> router's DNS server --> 192.0.2.10 (the Mac)
Roku --TLS, SNI api.example--> Mac:443 (mitmweb, certificate signed by the lab's CA) --> the real api.example
```

The addresses in this guide are documentation examples: router `192.0.2.1`, Mac `192.0.2.10`, Roku `192.0.2.20`, LAN `192.0.2.0/24`. Use your own.

## Quick start

1. Put the Mac and the Roku on one router whose DNS server can answer per client (AdGuard Home does; several travel routers ship it). Reserve both addresses in the router's DHCP settings, and list the LAN in `lan_subnets` in your roxy `settings.json`.
2. In that DNS server, rewrite each Origin host you want to see to the Mac, for the Roku only:
   ```
   ||api.example^$dnsrewrite=NOERROR;A;192.0.2.10,client=192.0.2.20
   ```
3. Turn on the router's option that answers every client's DNS itself ("override DNS for all clients" or similar), so a hardcoded resolver cannot skip the rewrites.
4. Start the lab: `roxy start --ca-routing` (adds listeners on 443 and 80). Its first start creates the lab's CA, `~/.mitmproxy/mitmproxy-ca-cert.pem`.
5. Build the app so every agent trusts Roku's bundle plus that CA ([The CA bundle on each agent](#the-ca-bundle-on-each-agent)):
   - a Lab App: `scripts/deploy --ca-routing "<device>" apps/classic` (or `apps/rsg`);
   - an app with the kit: `ROXY_KIT=1 scripts/deploy --ca-routing "<device>" kit/example-classic` shows how (see [Apps with the kit](#apps-with-the-kit)).
6. Launch the app: a Lab App with `roxy launch "<device>" case=json_get` (its CA Routing build ignores the Proxy Base); an app with the kit without `proxyBase` (`curl -d '' "http://192.0.2.20:8060/launch/dev"`), or it takes Prefix Routing as well. Its requests show in mitmweb (`http://127.0.0.1:8081`) under their Origin URLs.

## 1. Topology

- **One router for both.** The Mac must reach the Roku (deploy, ECP, the debug console), and the Roku's DNS must be the router you control. If the router sits behind another one (a repeater or travel router on your home Wi-Fi), put both the Mac and the Roku on its side: from the other side the Roku is hidden behind its NAT.
- **Fixed addresses.** Reserve the Mac's and the Roku's addresses in the router, since the DNS rules name them.
- **The lab's client guard.** The lab serves only clients in `lan_subnets` (`settings.json` in your settings root). Add the router's subnet there and restart the lab.
- **The Mac's own DNS must not be rewritten.** The lab looks up each Origin from the Mac. If that lookup also returns the Mac, the request would loop, and the address guard refuses it with `X-Lab-Blocked: origin-address`. So scope every rewrite to the Roku (step 2). An `origin-address` refusal for a host you rewrote means the Mac is being rewritten too.

## 2. DNS rewrites: only the Origins you want, only for the Roku

In AdGuard Home, use **Filters → Custom filtering rules**, one rule per Origin host, scoped with `client=`:

```
||api.example^$dnsrewrite=NOERROR;A;192.0.2.10,client=192.0.2.20
||cdn.example^$dnsrewrite=NOERROR;A;192.0.2.10,client=192.0.2.20
```

- `||host^` matches the host and its subdomains (`img.cdn.example` too).
- From the LAN the lab relays to any public Origin, so any host can be rewritten. Rewrite only hosts your app uses: everything else on the Roku (other apps, Roku OS) does not trust the lab's CA and would fail. For the Lab Apps, the hosts are `origin_allowlist` in `proxy/config/guards.json`.
- The DNS server must see each client's own address for `client=` to match. Check its query log: the Roku's queries must show the Roku's address, not the router's. On some routers this needs an option that hands client queries to AdGuard Home with their source address.
- Turn off the DNS server's own blocklists while you work: the usual ones block ad and tracking hosts, which RAF needs.
- Global **DNS rewrites** (AdGuard Home's other rewrite page) apply to every client, the Mac included. Use them only if the Mac's DNS comes from elsewhere.
- **IPv6.** The rules above rewrite A records. If the network gives the Roku IPv6, add matching AAAA rewrites or turn IPv6 off on that network, or the app can reach the Origin over IPv6 directly.

Check from the Mac that its own answer is untouched:

```
dig +short api.example @192.0.2.1        # a public address, not 192.0.2.10
dig +short AAAA api.example @192.0.2.1   # nothing pointing at the Mac
```

To see the Roku's answer, add the Mac to a rule for a moment (`client='192.0.2.20'|'192.0.2.10'`), run the `dig` again (it must print `192.0.2.10`), then remove it.

## 3. Answer every client's DNS

A device with a hardcoded resolver (say `8.8.8.8`) would skip the rewrites. Turn on the router's option that intercepts plain DNS (port 53) to any server and answers it itself.

- Prefer the router's own option to a hand-made port 53 redirect: firmware that marks or filters DNS packets can lose every client's DNS, the router's included, under a plain redirect rule.
- It does not catch DNS over HTTPS or over TLS. Roku OS is not known to use either for apps.
- Check: with the Mac added to a rule as above, `dig +short api.example @8.8.8.8` must also print `192.0.2.10`.
- To see which resolver the Roku really uses, watch its DNS packets on the router, if it has a shell: `tcpdump -ni <lan-interface> host 192.0.2.20 and port 53 or port 853`. Queries to `192.0.2.1` go through the rewrites; any other address is a hardcoded resolver. The DNS server's query log is the better record of what the Roku asked.
- Before changing DNS or firewall settings over SSH, back up the config and arm a timed restore that you cancel once DNS still works: a broken answer also cuts off a session that resolves through the router.

## 4. Run the lab and the app

```
roxy start --ca-routing                              # also listens on 443 and 80
scripts/deploy --ca-routing "<device>" apps/classic  # a Lab App's CA Routing build
roxy launch "<device>" case=json_get                 # the build ignores the Proxy Base
```

- **The lab** (`--ca-routing`): a request that is not a Prefixed URL takes its Origin from `Host`, or from the TLS SNI without one. Every guard still applies, and Scenarios apply as usual. The lab adds no Proxy Base to these flows: URLs in headers and bodies stay Origin URLs, since DNS already brings them back. Without the flag a non-Prefixed request is refused with `not-prefixed`, unless the App Profile's [fallback Origin](settings.md#app-profiles) takes it; with the flag the fallback Origin never applies.
- **Check the lab from the Mac**, with no router involved:
  ```
  curl --cacert ~/.mitmproxy/mitmproxy-ca-cert.pem --resolve api.example:443:192.0.2.10 https://api.example/
  ```
- **HTTP/2.** A Roku negotiates HTTP/2 with the lab's TLS listener, so CA-routed flows show as `HTTP/2.0` in mitmweb (Prefix Routing flows stay HTTP/1.1). HTTP/2 forbids connection-specific headers (`Connection`, `Keep-Alive`, `Transfer-Encoding`, `Upgrade`), and strict Origins reset a request that carries one (a 502 in mitmweb). The lab never adds them to an HTTP/2 flow; a Scenario that sets headers must not either.
- **The CA must stay the same.** A build carries the lab's CA at build time. mitmweb keeps it in `~/.mitmproxy/`; deleting that folder makes a new CA, and every CA Routing build must be rebuilt. Docker Compose does not wire CA Routing for that reason: it would need a persistent mitmproxy folder.

## The CA bundle on each agent

Each kind of request uses its own agent, and each needs the bundle: Roku's public roots plus the lab's CA. The Lab Apps' CA Routing builds and the kit set it everywhere it can be set.

| Agent | Classic BrightScript | RSG 2.0 SDK |
|---|---|---|
| roUrlTransfer / `fetch` | `SetCertificatesFile(bundle)`, `InitClientCertificates()` | a `new HttpsAgent({ certificatesFile })` on each `Request` (`HttpsAgent.setGlobalAgent` is undefined at runtime) |
| Poster and other non-Video nodes | the scene's `m.top.getHttpAgent()`, set as above | not possible: the SDK has no API for the app's default agent |
| Video content | content `HttpCertificatesFile` | `VideoContentNode` `httpCertificatesFile` |
| DRM license requests | content `DrmHttpCertificatesFile` | the Video's agent above (a Widevine license passed with it) |
| RAF | two undocumented settings (below) | not possible: the `<Ads>` task owns RAF |

Where the bundle comes from:

- **Classic:** the package carries the lab's CA as `pkg:/certs/lab-ca.crt`. At start-up the app writes `tmp:/lab-ca-bundle.crt`, Roku's `common:/certs/ca-bundle.crt` plus that CA, so Roku's part stays as current as the device.
- **RSG 2.0:** an `HttpsAgent` reads `pkg:/` files only, so the bundle is combined at build time and shipped in the package. `scripts/deploy --ca-routing` uses certifi's public roots from the proxy venv plus the lab's CA. Those roots age with the build: rebuild to refresh them.

### RAF's undocumented certificate settings

RAF has no documented certificate API. Two undocumented ways work (Roku OS 16.0.4):

- `raf.setCertificatesFile(bundle)`, a member of every RAF instance, called before `getAds()`, covers RAF's own requests: ad tag, wrappers and beacons. Without it the ad tag fails with `SSL certificate OpenSSL verify result: unable to get local issuer certificate (20)`.
- `HttpCertificatesFile` set on each ad that `getAds()` returns, before `showAds()`: RAF copies it into its player's content, so the creative trusts the lab too. Set on the ad's streams instead, it is ignored (render failure `-3`).

## Apps with the kit

The kit (`docs/prefix-routing.md`, The kit) also covers CA Routing, behind the same build-time constant:

- **Classic:** package the lab's CA as `pkg:/certs/lab-ca.crt` in the kit build. `RoxyTrust`, `RoxyTrustContent`, `RoxyTrustAds` and `RoxyTrustAdPods` then use the combined bundle; without the file they use Roku's. `ROXY_KIT=1 scripts/deploy --ca-routing` packages the example that way.
- **RSG 2.0:** build with `ROXY_KIT=1` and `ROXY_CA_BUNDLE=<bundle file>`; `roxy-config.ts` ships it as `pkg:/certs/lab-ca-bundle.crt`, and `withRoxyAgent()` and `roxyCertificatesFile` use it. Make the bundle with any public roots plus the lab's CA, for example:
  ```
  cat "$(cd proxy && uv run python -c 'import certifi; print(certifi.where())')" ~/.mitmproxy/mitmproxy-ca-cert.pem > out/lab-ca-bundle.crt
  ```
- Launch without `proxyBase`: the kit leaves Origin URLs alone, and DNS does the routing. With one, the app uses Prefix Routing as well.

## Known limits

- **RSG 2.0 Poster:** it uses the app's default agent, which the SDK cannot set, so a Poster image from a rewritten host fails TLS. Leave image hosts out of the rewrites, or use Prefix Routing for them.
- **RSG 2.0 Ads:** the SDK's `<Ads>` task (`@roku-sdk/ads`) owns its RAF instance and exposes neither RAF setting, so the ad break cannot trust the lab's CA. Leave the ad hosts out of the rewrites to let ads play directly.
- **RSG 2.0 roots** are the build's (certifi), not the device's, and age with the build.
- The grid runner marks the cells these limits break as known-limit (`grid/cells.toml`, `known_limits`).
- **Other apps and Roku OS** do not trust the lab's CA: rewrite only the hosts of the app you are working on, only for its Roku.
- **Physical Devices only.** A Cloud Device's DNS cannot be pointed at your router; use Prefix Routing there.
- **Docker Compose** does not wire CA Routing (see `compose.yaml`).
