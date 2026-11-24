# Implementing a ticket

For an agent building one ticket in its own git worktree, to be merged into the feature's integration branch.

1. **Start on the integration branch tip.** A new worktree may start from `origin/main`, often behind the integration branch. Check with `git merge-base --is-ancestor <integration-branch> HEAD`; if it is not an ancestor, `git reset --hard <integration-branch>` (only in a fresh worktree, before any work).
2. **Edit with the Edit and Write tools.** The worktree guard refuses shell commands it cannot prove stay in the worktree (heredocs into files, inline Python rewrites, chained `cd`). Run git as plain, separate commands from the worktree root.
3. **Iterate on one step.** `scripts/check STEP` runs only that step (the steps are listed at the top of `scripts/check`): `proxy` for the proxy tests, `roxy` and `settings` for the CLI and start-lab, `glossary` and `docs` for wording and links.
4. **Commit once the ticket is green.** The pre-commit hook runs the whole `scripts/check` (over two minutes), so commit at ticket boundaries, not after each edit. After each commit, `git show --stat HEAD` lists only the files you meant to change.
5. **Merge the integration branch tip into yours** before reporting done.

Tests follow the Tests section of [CODING_STANDARDS.md](../../CODING_STANDARDS.md). Docs link only to tracked files: `docs/adr/` and `.scratch/` are local and gitignored, so cite an ADR by its number in prose.
