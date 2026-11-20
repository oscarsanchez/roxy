# Prefix Routing guide

How a Roku app sends its Outbound Traffic through the lab by putting the Proxy Base in front of each URL it builds. It works on every Target Device and needs no certificate on the device. Vocabulary: `GLOSSARY.md`. Why two forms: ADR-0002. Routing by DNS and the lab's CA instead: `docs/ca-routing.md`.

## Quick start

**An app with a Charles hook** (nothing in the app changes):

1. `roxy start`. It prints the Proxy IP.
2. In a sideloaded build, type the Proxy IP into the app's debug proxy setting (port 8888).
3. Use the app. Its requests show in mitmweb (`http://127.0.0.1:8081`).

**An app you own, without a hook** (the kit, below):

1. Copy the kit into the app and route its URLs through it: [Wiring a classic app](#wiring-a-classic-app) or [Wiring an RSG 2.0 app](#wiring-an-rsg-20-app).
2. Build it with the kit's constant: `bs_const=roxy_kit=true` (classic) or `ROXY_KIT=1` (RSG 2.0).
3. `roxy start`, then `roxy launch "<device>"`: it launches the dev channel with the `proxyBase` launch param set to the LAN Proxy Base. Without a device in your `devices.json`, set it over ECP yourself, with a Proxy Base the start prints:
   ```
   curl -d '' "http://192.0.2.20:8060/launch/dev?proxyBase=http%3A%2F%2F192.0.2.10%3A8888"
   ```
   (`192.0.2.20` stands for the Roku, `192.0.2.10` for the Mac.)
4. Its requests show in mitmweb as `http://192.0.2.10:8080/;https://...` (or `:8888`, the Proxy Base you gave).

## The two forms

A Prefixed URL is the Proxy Base, a separator, then the Origin URL, byte for byte (query included):

| Form | Prefixed URL | Who uses it |
|---|---|---|
| The lab's own | `http://<proxy-ip>:8080/https://cdn.example/a.m3u8` | the Lab Apps |
| Charles-style | `http://<proxy-ip>:8888/;https://cdn.example/a.m3u8` | Product Apps with a Charles hook (unchanged) or with the kit |

- Both listeners (8080 and 8888) run the same lab and take either form. 8888 is Charles's port, which Charles hooks usually hardcode.
- `roxy start` prints the Proxy IP (the Mac's LAN address, to type into an app's debug proxy setting) and both LAN Proxy Bases.
- A Cloud Device uses the Public Endpoint instead (`https://<tunnel-host>/<secret>/<device-slug>`). A Charles hook builds `http://<ip>:8888/;` and cannot express it, so a Product App with only a Charles hook works on Physical Devices only.

## Switching the Charles-style hook on

Apps that support Charles switch the hook on in sideloaded builds only. The usual ways:

- **A hidden debug page** where you type the proxy IP; the app keeps it in its registry section.
- **A config key** (in a bundled or remote config) holding the proxy IP or the whole Proxy Base.
- **A build-time constant** (a manifest `bs_const` or the like) set from an environment variable of the packager, so a release build never carries it.
- **A build-time replace of request calls**: the packager swaps the app's request helper (or each `SetUrl`/`url =` call) for one that adds the Proxy Base.

Whichever it is, point it at the Proxy IP the start prints, on port 8888. Nothing in the app changes.

## What the lab handles by itself

Charles needs an imported Rewrite set for these; the lab does them for every request:

- **Recovering the Origin.** It takes the Origin URL from the path, after `/` or `/;`, and sends the Origin a normal request: `Host` is the Origin's, and `Referer` and `Origin` headers that carry a Prefixed URL are decoded back.
- **Keeping the separator.** Every URL it sends back uses the separator the request arrived with, so the app's own "already prefixed?" check keeps working.
- **Response headers.** `Location` (redirects and 201), `Content-Location`, `Link` and `Refresh` become Prefixed URLs.
- **Cookies.** `Set-Cookie` loses its `Domain` and is scoped by path to the Prefixed URL. A cookie path cannot hold `;`, so a Charles-style cookie is scoped to the Proxy Base (`Path=/`). With `/;`, then, every Origin behind the Proxy Base shares one cookie scope: a cookie one Origin sets is sent to the others too.
- **Bodies.** URLs in HLS playlists (variant, segment, key and map URIs), DASH manifests (`BaseURL`, `Location`, segment templates), VAST and other XML (media files, tracking, wrappers) and JSON (absolute URL values) become Prefixed URLs. Relative URLs stay as they are: they already resolve through the Prefixed URL.
- **No double Proxy Base.** A URL that already carries this client's Proxy Base, in either form, is never given another one: it comes back with the separator the request used.

## What the lab never sees

Only what the app sends to a Prefixed URL reaches the lab. Traffic the hook never touches goes straight to its Origin and stays invisible, as it did under Charles:

- requests built by code that skips the hook (a second HTTP helper, a third-party SDK);
- DRM license requests, unless the app sends the license URL through the hook;
- Roku Advertising Framework requests, unless the app hands it a Prefixed ad tag (the lab then rewrites the VAST that comes back);
- analytics and crash SDKs with their own endpoints;
- Roku OS's own traffic.

A missing flow in mitmweb usually means the request was built outside the hook.

## The kit: apps without a Charles hook

An app you own that has no Charles hook opts in with the kit: drop-in code that builds Charles-style Prefixed URLs (`/;`) from the `proxyBase` launch param, and sets the lab's CA bundle on every agent for CA Routing. The kit lives in two example apps, which show the wiring with one JSON request:

| Flavour | Copy into your app | Example |
|---|---|---|
| Classic BrightScript/SceneGraph | `source/RoxyKit.brs` | `kit/example-classic` |
| RSG 2.0 SDK | `src/roxy-kit.ts`, and `roxy-config.ts` next to `roku-config.ts` | `kit/example-rsg` |

What it does:

- **Opt-in at launch.** With a `proxyBase` launch param, every URL given to the kit becomes `<proxyBase>/;<url>`. Without it, URLs are left exactly as they are, so a normal dev run behaves as before.
- **Safe to call on any URL.** Non-http(s) URLs (`pkg:/`, `tmp:/`) and URLs that already carry the Proxy Base (the lab puts it in the URLs of the bodies it rewrites) come back unchanged.
- **Compiled out of release builds.** Everything that reaches the lab sits behind a build-time constant, and a release build leaves it off ([The build-time constant](#the-build-time-constant)).

### Wiring a classic app

1. Copy `kit/example-classic/source/RoxyKit.brs` into the app's `source/`, and add the constant to the manifest, off: `bs_const=roxy_kit=false` (append `;roxy_kit=false` to an existing `bs_const`).
2. In `Main`, before `CreateScene`: `RoxyStart(screen, args)`. It keeps the `proxyBase` launch param in a global node field, for every thread.
3. In each component that builds a URL or sets up an agent: `<script type="text/brightscript" uri="pkg:/source/RoxyKit.brs"/>`.
4. Route each URL through `RoxyUrl(url)` and each agent through the helpers (next section). `kit/example-classic` does it in `ExampleScene.brs` and `JsonTask.brs`.

### Wiring an RSG 2.0 app

1. Copy `kit/example-rsg/src/roxy-kit.ts` into `src/`, and `kit/example-rsg/roxy-config.ts` next to `roku-config.ts`.
2. In `roku-config.ts`: `buildVariables: { ...roxyBuildVariables }` under `app`, and `postBuild: roxyPostBuild` under `pipeline.build` (call it from your own `postBuild` if you have one).
3. In the root component: `const proxyBase = useProxyBase();`. It is `undefined` until the launch params arrive (the SDK delivers them after the first render), then the Proxy Base, or `""` without one. Start requests once it is defined, as `kit/example-rsg/src/components/example-app.tsx` does.
4. Route each URL through `prefixedUrl(proxyBase(), url)` and each request through `withRoxyAgent()` (next section).

### Which URLs to route, request by request

Route every URL the app builds itself. URLs the lab hands back in responses (manifest variants and segments, VAST media and beacons, image URLs inside JSON) are already Prefixed URLs: the kit leaves them alone, and relative URLs resolve through the Prefixed URL by themselves.

| Request | Classic | RSG 2.0 |
|---|---|---|
| HTTP request (roUrlTransfer / `fetch`) | `xfer.SetUrl(RoxyUrl(url))`, `RoxyTrust(xfer)` | `fetch(new Request(prefixedUrl(proxyBase(), url), withRoxyAgent()))`; `withRoxyAgent(init)` keeps your method, headers and body |
| Video content URL | `content.url = RoxyUrl(url)`, `RoxyTrustContent(content)` | `<VideoContentNode url={prefixedUrl(proxyBase(), url)} httpCertificatesFile={roxyCertificatesFile} />` |
| Poster | `poster.uri = RoxyUrl(url)`; `RoxyTrust(m.top.getHttpAgent())` once in the scene's `init()` | `<poster uri={prefixedUrl(proxyBase(), url)} />` |
| DRM license URL | `drmParams.licenseServerURL = RoxyUrl(url)` (`RoxyTrustContent` covers its certificates) | `drmParams={{ keySystem, licenseServerURL: prefixedUrl(proxyBase(), url) }}` |
| RAF ad tag | `raf.setAdUrl(RoxyUrl(tag))`; `RoxyTrustAds(raf)` before `getAds()`, `RoxyTrustAdPods(pods)` after it | `<Ads adUrl={prefixedUrl(proxyBase(), tag)} />` |
| Configurable SDK base URLs (analytics, player and ad SDKs) | pass `RoxyUrl(baseUrl)` where the SDK takes its base URL | pass `prefixedUrl(proxyBase(), baseUrl)` |

- **SDK base URLs** work when the SDK appends paths and queries to the base it is given: the Origin URL after `/;` is kept byte for byte. An SDK with fixed endpoints stays invisible ([What the lab never sees](#what-the-lab-never-sees)).
- **RAF** fetches the ad tag, then wrappers, creatives and beacons from the VAST it gets back; the lab rewrites the VAST, so all of them follow. RAF without an ad URL of yours (Roku's default ad server) is not prefixed.
- The trust helpers matter for CA Routing (`docs/ca-routing.md`). With Prefix Routing the classic ones set Roku's bundle, which an `https` Proxy Base (a Cloud Device's Public Endpoint) needs; RSG 2.0's `fetch` and Video trust public roots by themselves.

### The launch param

`proxyBase` is the whole Proxy Base, without a trailing slash (the kit drops one):

| Target Device | `proxyBase` |
|---|---|
| Physical Device | `http://<proxy-ip>:8888` or `http://<proxy-ip>:8080`: both listeners take the `/;` form |
| Cloud Device | the public Proxy Base plus the device slug, `https://<tunnel-host>/<secret>/<device-slug>` |

- `roxy launch "<device>" [key=value...]` sends it: the LAN Proxy Base (port 8080) for a Physical Device, the public Proxy Base plus the slug for a Cloud Device, or `--proxy-base URL`. The `run` param it adds is ignored by an app that does not read it.
- By hand, over ECP, URL-encoded: `curl -d '' "http://<roku-ip>:8060/launch/dev?proxyBase=<encoded Proxy Base>"`.
- Unlike a Charles hook, the kit takes a Public Endpoint, so an app with the kit also runs through the lab on Cloud Devices.
- The launch param is one of the usual switches ([Switching the Charles-style hook on](#switching-the-charles-style-hook-on) lists the others). To use another one, keep the kit and change where it reads the Proxy Base: `RoxyStart` (classic) or `useProxyBase` (RSG 2.0).

### The build-time constant

| Flavour | Constant | Set by |
|---|---|---|
| Classic | `bs_const` `roxy_kit` | the manifest; keep `roxy_kit=false` in the repo and let the dev packager write `true` |
| RSG 2.0 | `__ROXY_KIT__` (from `roxy-config.ts`) | `ROXY_KIT=1` in the build's environment |

- **Without it the build carries no proxy code.** Classic: the BrightScript compiler drops the `#if roxy_kit` blocks, so `RoxyUrl` returns its argument and the trust helpers set Roku's bundle. RSG 2.0: the exports become no-ops and the release build (minified) drops the rest; a debug build (`rk build --debug`) is not minified and keeps the kit's code, dead. A CA bundle given without the constant is not shipped either. `scripts/tests/kit-build.sh` (part of `scripts/check`) builds both examples each way and checks this.
- A store build cannot route through the lab even with a `proxyBase` param: there is no code left to read it.

### Trying the examples

```
roxy start
ROXY_KIT=1 scripts/deploy "<device>" kit/example-classic   # or kit/example-rsg
roxy launch "<device>"                                      # sends proxyBase=<LAN Proxy Base>
```

- With `proxyBase`, mitmweb shows `GET http://<proxy-ip>:8080/;https://httpbin.org/json`, and the app shows the URL and `status=200`.
- Launched without it (`curl -d '' "http://<roku-ip>:8060/launch/dev"`), the request goes straight to httpbin.org: the app shows the Origin URL, and mitmweb shows no new flow.
- Without `ROXY_KIT=1` the app is the release build: it never uses the lab, whatever the launch param.
