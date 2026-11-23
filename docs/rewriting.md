# Header and body rewriting

Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

URLs in response headers (Location, Content-Location, Link, Refresh) and bodies become Prefixed URLs with the client's Proxy Base and the separator (`/` or `/;`) the request used, so follow-up requests (segments, images, ads) come back through the lab. A URL already carrying the client's Proxy Base, in either form, is never prefixed twice: it comes back with the separator the request used. Set-Cookie is scoped to the Prefixed path (to the Proxy Base for `/;`: a cookie path cannot hold `;`), and its `Domain` is dropped. The body rewriter is chosen by content type, falling back to the URL extension; anything else passes byte for byte.

- Each format has an option `lab_rewrite_<format>` (`hls`, `dash`, `json`, `xml`, `text`) listing its content types and `.ext` extensions; a `+suffix` entry (`+json`, `+xml`) covers every type with that structured-syntax suffix (`application/vnd.example+json`), and a type ending in `/*` (`text/*`) covers its whole family, each after every exact type and extension, suffixes before families. Change it in mitmweb's Options or with `--set`; an empty list turns the format off.
- HLS: URI lines and `URI=` attributes (`EXT-X-KEY`, `EXT-X-MAP`, `EXT-X-MEDIA`, `EXT-X-I-FRAME-STREAM-INF`).
- JSON (`application/json`, `+json`, `.json`): string values that are absolute http(s) URLs; everything else is left exactly as the Origin sent it.
- DASH: `<BaseURL>`, `<Location>`, and `media`/`initialization`/`index`/`sourceURL` attributes.
- VAST / generic XML (`application/xml`, `text/xml`, `+xml`, `.xml`): every absolute http(s) URL in text, CDATA or attributes. Namespace names and schema locations are kept. A generic XML type yields to a format the URL extension names (a `.mpd` served as `text/xml` gets the DASH rewriter).
- Text (`text/*`, `application/javascript`): every absolute http(s) URL in HTML, JS, plain text or any other text type no format above claims; root-relative and relative URLs are left alone. Off unless the loaded App Profile's `profile.json` has `"rewrite_text": true` (restart the lab after changing it), for an app whose pages or scripts name the URLs it fetches next. Binary bodies are never touched.

## Target Device names

Each flow's comment names its Target Device (mitmweb comment column; filter `~comment "Living Room"`), and so does its `device` in `roxy flows --json`. A Physical Device or a Proxied Device is named by its `ip` in your `devices.json`. A Cloud Device is named by the device slug in its Proxy Base, `https://<tunnel-host>/<secret>/<slug>`: `roxy launch` appends the device's `slug` from `devices.json` to the public Proxy Base. A tunnel request without a known slug whose `CF-Connecting-IP` is an RCE egress IP is named `Cloud Device`. Other clients get no name.
