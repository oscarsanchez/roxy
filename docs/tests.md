# Tests

Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

```sh
scripts/check                 # every check below, plus shell syntax, the lab lock, deploy and launch against a fake rce, settings and Recordings against a fake mitmweb, the roxy CLI and install.sh against fake curl and rce in a temp HOME, the kit's example builds with and without its constant, the kit check against a fake device, compose config, the glossary lint, the docs link and anchor check, and the test-import rule
scripts/check glossary syntax # only the named steps, in that order (each header names its step; an unknown name lists them)
cd proxy && uv run pytest     # Seam A: the full addon chain, no network
cd grid && uv run pytest      # grid verdict logic, its settings, batches, and its Cloud Device side against a fake rce; no devices
```

No check reads your own settings: `scripts/check` points `ROXY_CONFIG_DIR` at a temp folder seeded from `settings.example/` (the user data directory and `ROXY_OUT_DIR`, the build output and logs that default to `out/`, at others), and the pytest suites seed their own.

Live checks need the internet or a Target Device, so `scripts/check` leaves them out:

```sh
scripts/grid ...              # grid cells on Target Devices, one or a batch (see grid.md)
scripts/console <device> --launch <case>  # a Physical Device's console from connect to the run's result line, saved to out/console/ (instead of nc: no replay, no missed lines)
scripts/kit-check <device>     # both kit examples on a Physical Device, launched with proxyBase and without; checks the app's screen and the lab's flows, exits 1 on a mismatch
scripts/check-tunnel-reuse    # requests to one Origin over a reused connection to the tunnel listener, as cloudflared sends them; fails if one hangs. Uses the running lab or starts one; no Cloud Device, cloudflared or RCE
```

The pre-commit hook, which `install.sh` turns on (`core.hooksPath .githooks`), runs `scripts/check`. The glossary lint fails on any `_Avoid_` term of [GLOSSARY.md](../GLOSSARY.md); a legitimate use goes in `scripts/glossary-allow.txt` with its reason, or carries `glossary-ok` on its line.
