# Lab Apps

The two disposable Lab Apps, classic BrightScript/SceneGraph (`apps/classic`) and RSG 2.0 (`apps/rsg`): their prerequisites, cases and result lines. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

## RSG 2.0 prerequisites

Node 24+ (`brew install node@24`; `scripts/deploy` puts it first on PATH), pnpm 11, `brew install squashfs`.

```sh
scripts/deploy "Living Room" apps/rsg                    # RSG 2.0 Lab App: pnpm install if needed, rk build --debug, sideload
```

## Cases

Same ids, labels and Origins in both flavours, also in an on-screen menu: `json_get`, `redirect`, `json_post`, `image`, `hls`, `dash`, `widevine`, `raf`, `raf_vmap`; classic also has `uuid` (new data on each request, to prove replay). Launched without a Proxy Base, the app uses the LAN Proxy Base it was built with.

## Result lines

One per run; the console replays recent history on connect, so match on `run=<id>`.

- Requests: `LABRESULT <case> run=<id> status=<code> bytes=<n> fp=<first 12 hex digits of the sha1>`. `json_post` adds `sentfp=` (equal to `fp` = the body arrived intact). `image` reports `status`, `prefixed=<yes|no>` (the catalog's image URL came back as a Prefixed URL) and `poster=<ready|failed>`.
- Playback (`hls`, `dash`, `widevine`): `state=<playing|error|finished|timeout_<state>> errorCode=<n> bitrate=<first video segment bps>`. `widevine` adds `license=`: `2` once the license is acquired (Roku OS 16), the license server's HTTP status when it fails, `none` if none was requested. A playback error also prints `LABERROR <case> run=<id> <errorStr>` (diagnostic only).
- `raf`: one RAF ad break from Google's sample VAST wrapper tag, as a Prefixed URL: `outcome=<completed|no_ads|exited> ads= impressions= completes= errors= media=<lab|direct|none>` (`media`: the first creative is a Prefixed URL). RAF's own `[RAF] fireBeacon(...)` log is on the console. In the RSG app, `impressions`, `completes` and `errors` are `na`: the SDK's `@roku-sdk/ads` task has no tracking callback, so count beacons in mitmweb.
- `raf_vmap`: the same, from Google's IMA VMAP pre-roll sample tag: RAF follows the VMAP's `AdTagURI` to the VAST ad and plays the pre-roll pod.
- RSG lines start with `[TS]: ` and carry colour codes; match on `LABRESULT`. A release `rk build` strips `console.*`, so always build with `--debug`. By hand: `cd apps/rsg && LAB_PROXY_BASE=http://<mac-ip>:8080 ./node_modules/.bin/rk build --debug --local`.
