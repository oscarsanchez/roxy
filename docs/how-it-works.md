# How it works

How a request reaches the lab and what the lab does to it. Vocabulary: [GLOSSARY.md](../GLOSSARY.md). The trust rules the code follows: [CODING_STANDARDS.md](../CODING_STANDARDS.md#trust).

## Routing

**Prefix Routing** works on every Target Device. The app puts the Proxy Base in front of every URL it builds, `<Proxy Base>/<Origin URL>`, or `<Proxy Base>/;<Origin URL>` as a Charles-enabled build does (port 8888). How to wire an app, with its Charles hook or with the kit for apps you own (`kit/`): [Prefix Routing guide](prefix-routing.md). The Lab Apps take the Proxy Base from the `proxyBase` launch param, with a build-time default as the fallback, and build the `/` form unless launched with `separator=/;`. The Proxy Base differs by Target Device kind:

| Target Device | Proxy Base |
|---|---|
| Physical Device | `http://<mac-lan-ip>:8080`, or `:8888` (Charles's port). Give the Mac a DHCP reservation so it stays stable. |
| Cloud Device | `https://<tunnel-host>/<secret>/<device-slug>`: the Public Endpoint (a Cloudflare quick tunnel), the secret segment, and the slug that names the Cloud Device (`roxy launch` adds it). |

**CA Routing** (Physical Devices only): DNS on the router points Origins at the Mac, and a CA Routing build of the app calls Origin URLs directly while trusting the lab's CA on every agent. See [CA Routing](ca-routing.md).

**Proxy Routing** (Proxied Devices only): the Proxied Device sets the lab's Proxy Routing listener, `<mac-lan-ip>:8090`, as its HTTP proxy and trusts the lab's CA, the same one CA Routing uses. Its requests arrive as the Origin URLs they are, with no Proxy Base, so the lab rewrites nothing in their responses. See [Proxied Devices](proxied-devices.md).

## What the lab does to a request

mitmweb's listeners run in mitmproxy's `reverse` mode, except the Proxy Routing listener, an HTTP proxy in its `regular` mode. The lab tells tunnel and Proxy Routing requests apart by the listener they arrived on, never by anything the client sends. mitmweb's UI listens on `127.0.0.1` only, needs a password, and is never tunnelled. The lab's addons, in order:

1. **Origin decoding**: recovers the Origin and the client's Proxy Base from the Prefixed URL path, or from Host/SNI in CA Routing. A Proxy Routing request keeps the Origin URL it carries, and has no Proxy Base: a path that looks Prefixed is an ordinary Origin path there.
2. **Target Devices**: decides once which Target Device sent the flow: the throttle shares bandwidth per Target Device, and mitmweb and `roxy flows` show its name (see [Target Device names](rewriting.md#target-device-names)).
3. **Guards**: refuse anything but an allowed client and a public Origin address, and on the Public Endpoint an allowlisted Origin host (see [Guards](guards.md)).
4. **Request header cleanup**: `Host` is the Origin's, `Referer` and `Origin` are decoded back, tunnel headers are stripped.
5. **Response header and body rewriting**: URLs in headers and in HLS, DASH, VAST/XML and JSON bodies become Prefixed URLs with the client's Proxy Base, so follow-up requests come back through the lab. A flow with no Proxy Base (CA Routing, Proxy Routing) is left as the Origin sent it.
6. **Scenarios**: the active Scenarios' Manipulation rules, last, so they see the response as the client gets it. The one exception, `map_remote`, swaps the Origin right after Origin decoding, before the guards.

While the lab runs, any registered device and any device on your LAN subnets can relay through it to any public host, the same as with Charles.
