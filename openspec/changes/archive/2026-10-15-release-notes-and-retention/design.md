## Context

`release-deploy.yml` releases `deploy-v<version>` when a version bump on `main` passes CI and PC tools. Its notes are `--notes "<fixed sentence>" --generate-notes --notes-start-tag <previous>`: a hard-coded paragraph plus GitHub's PR title list. Releases are never deleted. Pull requests in this repository open with "Before:" / "After:" / "How:" paragraphs, and their title and body already pass the banned-word check in CI.

## Goals / Non-Goals

**Goals:** a release description that says what a user gets in this release and cannot drift from what the release publishes; a short Releases page; no deletion until Toni switches it on.

**Non-Goals:** editing the notes of releases that already exist; deleting container image versions from ghcr.io; changing when a release happens; a CHANGELOG file in the repository.

## Decisions

**Template file plus a coverage test, not a hand-maintained paragraph in YAML.** `tools/deploy/release-notes.md` holds the static part. `test_release_notes.py` derives the required names from the sources of truth: asset file names passed to `gh release create`, image names pushed by the `image` job, and `[project.scripts]` in `pyproject.toml`; each must appear in the template. This is what "update the description when needed" means in practice: the test forces it in the same PR that changes what ships. Alternative considered: generate the whole text from the workflow; rejected, the install steps need human wording.

**"What's new" from the squash commits' `(#N)`, PR body via REST.** `git log <previous>..<sha> --format=%s` gives the merged PRs in order (squash merge is the rule here). For each, `gh api repos/{repo}/pulls/N` gives title and body; the script takes the paragraph starting with `After:` (up to the next blank line), strips the prefix, and writes `- **[Title](url)**: <after text>`. Missing After paragraph: title only. Commits without `(#N)` (direct pushes) are listed by subject. GraphQL is not needed. GitHub's `--generate-notes` is dropped; the compare link is written by the script.

**Banned words fail the release.** The notes are public. PR bodies are checked when the PR runs CI, but a body edited after merge is not, so the release checks again (`--env-text RELEASE_NOTES`). Failing before `gh release create` keeps the "nothing half-published" property; the fix is editing the PR body and "Run workflow".

**Keep 4 (newest + 3), ordered by version.** Four covers the usual same-day burst of releases and leaves one or two steps to fall back to if a release is broken. Ordering by version (the existing `version_key`) rather than date makes a late hand-pushed older tag unable to push a newer release out. The count is a constant in `release_version.py` (`KEEP_RELEASES = 4`), changed by a PR.

**Delete the tag with the release.** A tag left behind would be treated by the gate as "tag pushed by hand" for that version; harmless, but it is clutter and the reason Toni asked. Kept releases' "Full changelog" links still work because they point at kept or newer tags, except the oldest kept one, whose compare base disappears; accepted. Orphan `deploy-v*` tags older than the oldest kept release go too.

**Prune runs after `manifest`, and only when a release was made (or on `prune_only`).** A failed image job leaves the old releases in place. It uses `gh release delete <tag> --cleanup-tag --yes` and `gh api -X DELETE repos/{repo}/git/refs/tags/<tag>` for orphan tags. Never touches the release just made, the GitHub "latest" release, drafts or tags outside `deploy-v*`.

**Switch: repository variable `RELEASE_PRUNE`.** Without `on`, the job writes the list to the run summary and deletes nothing. This keeps the first real deletion an explicit act by Toni, after reading the list in a run summary.

## Risks / Trade-offs

- Someone needs an old wheel → install from the commit archive URL (documented); old images stay on ghcr.io.
- PR body format drifts → falls back to the title, never fails.
- REST rate limit for many PRs → one call per PR, at most a few dozen per release; fine with `GITHUB_TOKEN`.
