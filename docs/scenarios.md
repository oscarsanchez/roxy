# Scenarios

Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

A Scenario is a file of named Manipulation rules, `proxy/scenarios/<name>.toml`. Any number can be active at once, in an order you choose, lab-wide, for every Target Device. Their rules apply in that order, then file order: two `body` rules on one response apply in set order, and of two `throttle` caps the lower wins.

```sh
roxy scenario list                                      # the App Profile's Scenarios and the lab's, each with its source
roxy scenario set json-503                              # make it the one active in the running lab
roxy scenario set json-503 image-404                    # make these the active ones, in this order
roxy scenario add hls-404                               # make it active too, after the others
roxy scenario remove json-503                           # stop its rules, keep the others
roxy scenario clear                                     # none active
roxy launch --scenario json-503 "Living Room" case=json_get   # set it, then launch (repeat --scenario for several; '' clears them)
```

Each prints the active Scenarios after the change (`scenario=json-503,image-404`); an unknown name is refused and leaves them as they were. Or edit `lab_scenario` in mitmweb's Options: the active names in order, comma-separated. Editing an active file reloads it on the next request; a broken edit is logged and the last good rules stay.

A rule whose filter matches nothing fails silently: the check passes while the Manipulation never happened (the CDN moved hosts, a throttle matched no segment). After a launch, check `roxy status --since <run>` (the `run=<id>` that `roxy launch` prints): under each active Scenario it lists every rule with the flows it acted on since then, and flags a rule that acted on none, such as `slow segments  0 flows  (acted on nothing yet)`. Without `--since` it counts every flow of the Lab Session. A Scenario file that no longer loads shows why instead of its rules. `roxy status --json` adds the same counts as `rules: [{"scenario", "rule", "flows"}]`, in Scenario then file order.

Shipped: `json-503`, `image-404`, `hls-404`, `dash-404`, `dash-absolute` (absolute `<BaseURL>`), `hls-lowest-variant`, `widevine-license-fail` (`state=error errorCode=-6 license=403`), `raf-ad-tag-drop` (`outcome=no_ads` for `raf` and `raf_vmap`; a status override alone is not enough, RAF reads a 503's VAST body).

In mitmweb, a flow a rule acted on is marked 🧪 (unless the lab refused it: ⛔) and its comment lists the rules after the Target Device's name, `Living Room | json-503/httpbin json fails`; filter `~comment json-503/` for one Scenario's flows.

Each rule has a `name`, a mitmproxy `filter` expression and exactly one action. Every matching rule applies, in file order. Flows the lab refused itself are never touched.

```toml
[[rule]]
name = "json fails"
filter = "~d httpbin.org & ~u /json"
status = 503                                    # status override (the Origin's body is kept)
# latency = 2.5                                 # seconds, before the request reaches the Origin
# throttle = { kbps = 400 }                     # what the rule matches reaches each Target Device at no more than 400 kbps together
# throttle = { kbps = 400, per = "request" }    # each matching response on its own at no more than 400 kbps
# drop = true                                   # close the connection, no answer, Origin not contacted
# header = { name = "Cache-Control", value = "no-store" }   # replace; "" removes (mitmproxy modify_headers)
# body = { pattern = "regex", replacement = "text" }        # regex replace (mitmproxy modify_body)
# map_local = "mocks/json.json"                 # answer from a file next to the Scenario (mitmproxy map_local)
# map_remote = "https://postman-echo.com:443"   # send to another Origin: scheme, host and optional port only
```

`header` and `body` act on the request and the response, like their mitmproxy built-ins: add `~q` or `~s` to the filter to pick one.

A `header` value or `body` replacement can hold placeholders, filled per flow from the client that made it, so one rule points a URL at the lab for every Target Device without an address in it:

| Placeholder | Filled with | LAN client | Public Endpoint client |
| --- | --- | --- | --- |
| `{proxy_base}` | the client's Proxy Base | `http://192.0.2.10:8080` | `https://<public-endpoint>/<secret>/<slug>` |
| `{proxy_base_no_scheme}` | the same without its scheme | `192.0.2.10:8080` | `<public-endpoint>/<secret>/<slug>` |
| `{separator}` | the separator the client used | `/` or `/;` | `/` or `/;` |

```toml
[[rule]]
name = "cdn through the lab"                    # the app reads mediaHost="cdn.example.com/media" and adds its own scheme
filter = "~s & ~d api.example.com"
body = { pattern = 'mediaHost="', replacement = 'mediaHost="{proxy_base_no_scheme}{separator}https://' }
```

A placeholder is `{name}`, lowercase letters and underscores: braces stay clear of regex replacement syntax (`\1`, `\g<1>`). Any other `{name}` in a replacement is refused when the Scenario loads (a broken edit keeps the last good rules), so a literal `{word}` cannot be written there. A flow that was not Prefixed (CA Routing) has no Proxy Base: a rule with placeholders leaves it alone.

`throttle` paces responses to the client: a response starts at once and arrives slowly, so a player sees a slow download, not a late one, and ABR can step down. It paces after every other rule and the lab's own rewriting, and takes a positive `kbps`, in one of two modes:

- `{ kbps = N }`, shared: everything the rule matches for one Target Device shares N kbps, like one slow link. Concurrent responses split it fairly, so a player's parallel range requests add up to N, not k × N, and a response alone gets all of N. Each Target Device has its own N, and so does each rule. A Physical Device is told apart by its IP; a Cloud Device, which reaches the lab through cloudflared like every other, by the device slug in its Proxy Base (else its client IP from the tunnel, so Cloud Devices without a slug behind one RCE egress IP share N).
- `{ kbps = N, per = "request" }`: each matching response gets N on its own.

When two `throttle` rules match one flow, the lower cap wins. Unlike Charles's Throttle: it caps downloads only (the request goes up at full speed); latency is a separate `latency` rule, added once per request, not per packet; and the cap is steady, with no packet loss or fluctuation, and no presets. HTTP/1 only: a flow whose client speaks HTTP/2 shares its connection with other flows, so it is sent unthrottled and the mitmweb event log says so. Add a `latency` rule with the same filter for a slow, high-latency link. On a Cloud Device the paced bytes go through the quick tunnel: keep such runs short.

`map_remote` keeps the request's path and query, and Host follows the new Origin. It runs before the guards, so the new host is judged like any other: a private address is refused, and through the tunnel so is a host off the allowlist. Responses from it are rewritten with the client's Proxy Base, as usual. Later rules' filters see the new Origin.

Manifest edits change manifests only (`filter = "~all"` is fine) and run after Prefixed URL rewriting, so the manifest still routes through the lab:

```toml
drop_variants = { all_but = "lowest" }          # or "highest"; or bandwidth_above / bandwidth_below = bps; or resolution = "WxH"
drop_renditions = { type = "SUBTITLES" }        # HLS EXT-X-MEDIA matching every key given: type, group_id, language, name
drop_renditions = { content_type = "audio" }    # DASH AdaptationSets matching every key given: content_type, mime_type, lang
drop_segments = { from = 3, to = 5 }            # HLS media playlist, segment indexes from 0; no `to` = to the end
alter_segments = { from = 2, uri = "missing.ts", duration = 1.5 }   # HLS: new URI and/or EXTINF duration
```

`drop_variants` also drops DASH Representations (`all_but` per AdaptationSet), and `drop_renditions` with DASH keys drops whole AdaptationSets; the segment edits are HLS only. `--scenario hls-lowest-variant ... hls` drops `bitrate=` to the lowest variant.
