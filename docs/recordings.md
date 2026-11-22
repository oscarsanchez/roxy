# Recordings

Recording, replay and HAR export. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

Every Lab Session is saved as a Recording in the Recordings folder, `~/.local/share/roxy/captures/<App Profile or no-profile>/<start time>.mitm`; open one with `mitmweb -r <file>`. With `--replay` (or `LAB_REPLAY` under Compose):

- A recorded request gets its recorded response every time; the Origin is not contacted. Replay is offline: an unrecorded request gets an empty 404 from the lab (`server_replay_extra=404`) and never reaches its Origin.
- Matching uses the Origin URL, so a Recording made on one Target Device replays to another; replayed URLs get the replaying client's Proxy Base.
- Guards still apply: a refused request stays refused.
- Record and replay in the same routing mode. A Recording made with Prefix Routing and replayed to a CA-routed client returns Prefixed URLs (Location, Set-Cookie paths, body URLs) of the recording client's Proxy Base: the lab adds no Proxy Base to CA-routed flows, so it does not undo them.

## Export as HAR

`roxy export --har` writes a Recording as a HAR file, for browser devtools, HAR viewers and bug reports, with one entry per HTTP flow. It reads the Recording file only, never mitmweb, so it works with the lab up or down; a running lab's Recording exports the flows recorded so far.

```sh
roxy export --har                                       # the newest Recording, in any App Profile's folder, to ./<recording name>.har
roxy export --har <recording>.mitm -o bug-1234.har      # that Recording, to bug-1234.har
roxy export --har --filter '~d example.com'             # only flows matching a mitmproxy filter expression
```

It prints the path written and its number of entries. It never writes over an existing file, and refuses a missing file, one that is not a Recording, and a bad filter expression.

- Request URLs are Origin URLs. Response bodies are as the Target Device received them, so URLs inside them are Prefixed URLs: the lab keeps no body from before its rewriting.
- The lab secret (`LAB_SECRET`) becomes `<secret>` everywhere in the file: URLs, headers and bodies, where a Cloud Device's Prefixed URLs carry it.
- Everything else the Recording held is in the file, the app's own headers, cookies and tokens included. Check it before you share it.
