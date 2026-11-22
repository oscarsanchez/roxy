# Grid runner

Fills grid cells: a Lab App flavour on a kind of Target Device, for one traffic class, with and without that class's Scenario. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

`scripts/grid --help` lists every flavour, Target Device kind, traffic class and option.

```sh
scripts/grid classic physical json
scripts/grid classic physical json --device Bedroom   # another Physical Device, for this call only
scripts/grid rsg cloud hls   # through the running tunnel (roxy start --tunnel)
scripts/grid classic physical json --ca-routing   # CA Routing (see ca-routing.md)
scripts/grid classic physical hls --separator '/;'   # the Charles-style form
scripts/grid classic,rsg physical all   # a batch: comma lists or all, in each of the three
scripts/grid all physical,cloud json,hls --separator '/,/;'   # each cell in both forms
```

A batch fills many cells in one call. Each of flavour, Target Device kind and traffic class takes one value, a comma list or `all`, and `--separator` takes `/`, `/;` or both (`'/,/;'`). The cells run one after another in a fixed order, under the one `devices` lock: Physical Device cells first, then by flavour, separator and class (in `grid/cells.toml`'s order). Each flavour is deployed once per Target Device, not once per cell. Each cell prints its lines as a single cell does; then the batch prints a table of every cell's row and a count (`N pass, N known-limit, N fail`), and exits 1 if any cell failed. A failing cell does not stop the batch, whatever went wrong in it (a launch, the flows read, a console that closed: its row says what); Ctrl-C does, after stopping a Run the grid started. A single cell prints no table.

Cloud Device cells in a batch share one cost question and one Run: the grid prints the projected time and cost of all of them (one start-up, one deploy per flavour, two launches per cell), asks once, and starts one Run capped (`rce device start --max-runtime`) at that projection plus `rce_cap_margin_s` (`grid/cells.toml`), a backstop if the grid is killed outright. It keeps the Run across the cells and stops it after the last one. In a batch with both kinds, the Run is started only after the Physical Device cells.

`--device NAME` fills the cells on NAME (from `devices.json`) instead of the device `grid_devices` names, for one call and one Target Device kind: the Mac moves between networks, and a Physical Device is reachable only from its own. A Physical Device the Mac cannot reach stops the grid before the deploy, naming the device and saying it may be on another network.

A Cloud Device cell launches with the running tunnel's public Proxy Base, as `roxy launch` does; a Physical Device cell, with the LAN Proxy Base. `--proxy-base URL` sends another.

`--separator '/;'` runs the cell in the Charles-style form: the Lab App gets the `separator=/;` launch param and builds every Prefixed URL as `<Proxy Base>/;<Origin URL>`, and the row says `(/; form)`. The default `/` is the lab's own form. Quote `/;`: in a shell, `;` ends the command. CA Routing has no Prefixed URLs, so it takes no `--separator`. Outside the grid, `roxy launch "Living Room" case=hls 'separator=/;'` does the same.

It fills one grid cell through the running native lab (`scripts/start-lab`, not Compose), on the Target Device that `grid_devices` in your `settings.json` names for that kind: it deploys the flavour, launches the case with the cell's Manipulation Scenario and then with none (so the lab ends with no Scenario), and prints one row: pass, fail or known-limit, with a reason. It reads the lab through `roxy status --json` (the lab must be this checkout's, and in CA Routing for a CA Routing cell) and, once each launch settles, `roxy flows --json --since <its run id>`, keeping the flows whose `device` is the cell's Target Device. Each launch's console and flows are kept in `out/grid/` as evidence for the verdict. Cells live in `grid/cells.toml`: per traffic class, the case, the Scenario, the expected Origin hosts and the result fields that mean success. A Cloud Device cell prints the projected RCE time and cost (about 5.3 min, $0.018, start-up included) and asks before it touches RCE. It then starts the Cloud Device if it has no Run, reads its console with `rce console`, and stops it after the cell, also when the cell fails or on Ctrl-C or a kill (during the start too), then confirms with `rce device status` that the Run ended; a Run that was already going is left running.

- **Pass:** the run without a Scenario succeeded, every expected Origin host showed up in that run's flows from the Target Device, the lab refused nothing, and the Scenario changed the result line.
- **Leaks** can only be inferred, since traffic that bypasses the lab never reaches it: an expected host is missing although the Lab App reports success, or the console prints an absolute URL that is not a Prefixed URL. A bypassing request to a host outside the expected hosts, one the result does not depend on (a beacon, a prefetch), and Roku OS traffic go unseen.
- No result line before the timeout: rerun the cell (an RSG launch crash is possible). A `raf` or `raf_vmap` baseline of `no_ads` is a known flake of Google's sample ad server: rerun. If a run errors part-way, its Scenario stays active: clear it with `--scenario ''`.
