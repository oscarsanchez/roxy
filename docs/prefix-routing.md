# Prefix Routing guide

How a Roku app sends its Outbound Traffic through the lab by putting the Proxy Base in front of each URL it builds. It works on every Target Device and needs no certificate on the device. Vocabulary: `GLOSSARY.md`. Why two forms: ADR-0002.

## The two forms

A Prefixed URL is the Proxy Base, a separator, then the Origin URL, byte for byte (query included):

| Form | Prefixed URL | Who uses it |
|---|---|---|
| The lab's own | `http://<proxy-ip>:8080/https://cdn.example/a.m3u8` | the Lab Apps |
| Charles-style | `http://<proxy-ip>:8888/;https://cdn.example/a.m3u8` | Product Apps with a Charles hook, unchanged |

- Both listeners (8080 and 8888) run the same lab and take either form. 8888 is Charles's port, which Charles hooks usually hardcode.
- `scripts/start-lab` prints the Proxy IP (the Mac's LAN address, to type into an app's debug proxy setting) and both LAN Proxy Bases.
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
- **Cookies.** `Set-Cookie` loses its `Domain` and is scoped by path to the Prefixed URL. A cookie path cannot hold `;`, so a Charles-style cookie is scoped to the Proxy Base (`Path=/`).
- **Bodies.** URLs in HLS playlists (variant, segment, key and map URIs), DASH manifests (`BaseURL`, `Location`, segment templates), VAST and other XML (media files, tracking, wrappers) and JSON (absolute URL values) become Prefixed URLs. Relative URLs stay as they are: they already resolve through the Prefixed URL.
- **No double Proxy Base.** A URL that already carries this client's Proxy Base, in either form, is not given another one.

## What the lab never sees

Only what the app sends to a Prefixed URL reaches the lab. Traffic the hook never touches goes straight to its Origin and stays invisible, as it did under Charles:

- requests built by code that skips the hook (a second HTTP helper, a third-party SDK);
- DRM license requests, unless the app sends the license URL through the hook;
- Roku Advertising Framework requests, unless the app hands it a Prefixed ad tag (the lab then rewrites the VAST that comes back);
- analytics and crash SDKs with their own endpoints;
- Roku OS's own traffic.

A missing flow in mitmweb usually means the request was built outside the hook.
