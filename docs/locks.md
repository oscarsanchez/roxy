# Locks

Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

One person or agent at a time drives the Target Devices. `scripts/deploy`, `scripts/launch` and `scripts/grid` hold the `devices` lock while they run; `scripts/start-lab` holds the `lab` lock for its session. Both are per user (`~/.cache/roxy/locks/`), shared by every checkout and worktree. One lock covers every Target Device because the active Scenarios are lab-wide.

- Held: the script stops at once, naming the holder (pid, command, and `LAB_LOCK_OWNER` if the holder set it). `LAB_LOCK_WAIT=1` waits for it instead.
- Agents: set `LAB_LOCK_OWNER` to your name, so a refusal tells the other side who to wait for.
- A grid cell's deploy and launches run inside the grid's lock. To hold it across your own commands, run them in one shell that takes it: `bash -c '. scripts/lib.sh && lab_lock devices && scripts/deploy "Living Room" apps/classic && scripts/launch "Living Room" case=json_get'`.
- A holder that died without releasing (crash, `kill -9`) is detected by its pid; the next script reclaims the lock.
