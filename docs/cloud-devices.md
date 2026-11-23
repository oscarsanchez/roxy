# Cloud Devices

Running a Lab App or a Product App on a Cloud Device in Roku Cloud Emulator (RCE), through the Public Endpoint. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

## Prerequisites

`brew install cloudflared` and the [`rce` CLI](https://github.com/oscarsanchez/rce-cli) (install it as its README says), which does every RCE call for the lab. Give the Cloud Device an rce Device Name and a Dev Snapshot once: `rce device alias <id> player`, `rce device setup-dev player`. Then, once:

```sh
roxy setup --cloud                              # generates the lab secret; checks rce, its token and cloudflared
roxy device add "Cloud Device" --rce player     # registers it by its rce Device Name, slug cloud-device
```

You should see `generated LAB_SECRET (in .../roxy/secrets.env; the Public Endpoint's secret path segment)`, never the secret itself, and `rce and cloudflared installed, and rce token status works`; a missing tool or token is a warning saying what to do. `roxy device add` warns, and still registers it, when `rce device resolve` does not know the name. Every option: [Settings](settings.md#setup).

## Deploy and launch

Start the lab with `roxy start --tunnel`. Deploy and launch go through `rce`, and need a running Cloud Device:

```sh
rce device start player                                  # billed from here, $0.20 per hour
scripts/deploy "Cloud Device" apps/classic               # rce sideload, with the Cloud Device's own dev password
roxy launch "Cloud Device" case=json_get                 # proxyBase https://<random>.trycloudflare.com/<LAB_SECRET>/<slug>
rce console player --until 'LABRESULT json_get' --timeout 60   # roxy console "Cloud Device" streams it without --until
rce device stop player                                   # billing ends here
```

## Notes

- The tunnel hostname changes on every start; its log is `out/cloudflared.log`.
- Cloudflare's terms require paid services to serve video through its network, and quick tunnels are for testing only (200 in-flight requests). Keep video over the Public Endpoint small and runs short.
- RCE costs about $0.20 per device-hour, Widevine is L3 only, and devices cannot be deleted.
