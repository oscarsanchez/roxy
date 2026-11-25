# Releasing

A release is the plugin's version (`.claude-plugin/plugin.json`), a `CHANGELOG.md` section, an annotated tag `v<version>` and a GitHub Release. Semantic Versioning, from `main`.

1. **Device smoke run**, with the user's OK (`AGENTS.md`): a ticket that checks the unreleased work on their Mac, settings root and a Physical Device, as `.scratch/settings-setup/issues/12-device-smoke-0-3-0.md` did for 0.3.0. Back up the settings root first and compare checksums after. Done when every `- [ ]` is ticked or the gap is named in the ticket.
2. **Version**: set `"version"` in `.claude-plugin/plugin.json`.
3. **Changelog**: rename `## [Unreleased]` to `## [<version>] - <date>`, add an empty `## [Unreleased]` above it, and open the section with a one-line summary of the release. At the bottom, point `[Unreleased]` at `compare/v<version>...HEAD` and add `[<version>]: …/compare/v<previous>...v<version>`. `scripts/check docs` checks a section exists for the plugin's version.
4. **Commit and tag**: commit both files as `chore(release): <version>`; tag it `git tag -a v<version> -m "roxy <version>" -m "<summary line>"`.
5. **Push** `main` and the tag, with the user's OK. Done when the `check` workflow is green on the release commit.
6. **GitHub Release** titled `roxy <version>`, its notes the changelog section without its heading or `glossary-ok` comments:

   ```sh
   awk '/^## \[<version>\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md \
     | sed -E 's/ <!-- glossary-ok:[^>]*-->//' | sed '1{/^$/d;}' > notes.md
   gh release create v<version> --verify-tag --title "roxy <version>" --notes-file notes.md
   ```
