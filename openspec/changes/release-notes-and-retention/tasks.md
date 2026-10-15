## 1. Release notes

- [ ] 1.1 `tools/deploy/release-notes.md`: what a release contains (wheel, `canworks.stlib`, `canworks-sim-runtime` image, `canworks-bridge` image), install command, links to docs; placeholders `{version}`, `{owner}`
- [ ] 1.2 `scripts/release_notes.py`: render the template, "What's new" from `git log <previous>..<sha>` `(#N)` subjects and each PR's "After:" paragraph via REST (title only when missing; subject for commits without a PR), "Full changelog" compare link; no previous release → no "What's new" section
- [ ] 1.3 `release-deploy.yml`: notes step uses the script, writes `RELEASE_NOTES`, runs `check-banned-words.py --env-text RELEASE_NOTES` (with `BANNED_WORDS`) before `gh release create --notes-file`; drop `--generate-notes`
- [ ] 1.4 `test/pc-tools/test_release_notes.py`: template names every asset in `gh release create`, every image the `image` job pushes and every `[project.scripts]` command; After-paragraph parsing (present, missing, CRLF, last paragraph); rendering with and without a previous tag

## 2. Retention

- [ ] 2.1 `release_version.py --prune KEEP`: reads release tags and all tags, prints releases to delete (all but the newest KEEP by version) and orphan `deploy-v*` tags older than the oldest kept; `KEEP_RELEASES = 4`
- [ ] 2.2 Unit tests: fewer than 4 releases → nothing; mixed patch versions; orphan tag newer than the oldest kept is kept; non-`deploy-v` tags ignored; the latest is never listed
- [ ] 2.3 `prune` job after `manifest` (and alone on `prune_only`): list to the run summary; delete only when `vars.RELEASE_PRUNE == 'on'` (`gh release delete --cleanup-tag --yes`, orphan tags via REST)
- [ ] 2.4 `workflow_dispatch` input `prune_only`

## 3. Docs

- [ ] 3.1 `docs/install-pc.md`: how notes are made, newest 4 releases kept, older versions from `archive/<commit>.zip`, `RELEASE_PRUNE` switch; mention the Modbus bridge image
- [ ] 3.2 README release paragraph

## 4. After merge (needs Toni)

- [ ] 4.1 "Run workflow" with `prune_only` (switch off): check the listed releases and tags match the proposal's list (plus any releases made since)
- [ ] 4.2 Toni sets `RELEASE_PRUNE=on` and runs `prune_only` again (or waits for the next release); check only 4 `deploy-v` releases remain
- [ ] 4.3 Next version bump: the release notes show the template text and the "What's new" entries with After paragraphs
