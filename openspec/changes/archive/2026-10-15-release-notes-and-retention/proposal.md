## Why

PC tools releases (`deploy-v<version>`) are created automatically by `release-deploy.yml`, but their description is weak and the release list only grows:

- **The description is a fixed sentence in the workflow.** It names the wheel, `canworks.stlib` and the simulator runtime image, but not the Modbus bridge image that every release has published since the bridge shipped. Nothing notices when a release starts publishing something new or a command changes, so the text goes stale silently.
- **"What changed" is only PR titles.** GitHub's generated notes list each merged pull request by title and author. The pull requests already open with a plain-language "After:" paragraph that says what a user gets, but the release does not use it, so a reader has to open every PR to learn what is new.
- **Old releases pile up.** There are 32 releases (0.31.0 to 0.63.0), five of them from today alone, plus 8 tags (0.23.0 to 0.32.0) whose releases are already gone. Only the newest is installed by anyone; the rest crowd the Releases page and the tag list.

## What Changes

- **Release notes from a template in the repository.** The fixed sentence moves out of the workflow into `tools/deploy/release-notes.md`, a short template with placeholders (`{version}`, `{owner}`, `{previous}`) that lists what a release contains (wheel, `canworks.stlib`, simulator runtime image, Modbus bridge image) and how to install and use each. A new script `scripts/release_notes.py` fills it in.
- **The template is kept current by a test.** A CI unit test reads the assets and images `release-deploy.yml` publishes and the commands `tools/deploy/pyproject.toml` installs, and fails when the template does not name each of them. So a change that adds an asset, an image or a command cannot merge without updating the description.
- **"What's new" from the pull requests' own words.** For every pull request merged between the previous `deploy-v` release and the released commit (found from the `(#N)` suffix of the squash commits), the notes give the PR title as a link and its "After:" paragraph. A PR without an "After:" paragraph is listed by title only. Version bumps that were never released (superseded) are covered, because the range starts at the previous release, not the previous version. The "Full changelog" compare link stays.
- **Banned-word check before publishing.** The generated notes go through `scripts/check-banned-words.py --env-text`; on a hit the release job fails before anything is published, and names only the PR number (never the word). "Run workflow" releases again after the PR text is fixed.
- **Retention: keep the newest release plus 3 previous ones.** After a release and its images are published, a new `prune` job deletes every other `deploy-v*` release with its tag, oldest first, ordered by version (not date). Tags `deploy-v*` with no release that are older than the oldest kept release are deleted too. Nothing else is touched: no other tag or release, no container images (an installed older wheel still pulls its own `canworks-sim-runtime:<version>`), no draft.
- **Deletion needs an explicit switch.** The prune job only lists what it would delete until the repository variable `RELEASE_PRUNE` is `on`. Toni sets it after reviewing the list; until then nothing is deleted. "Run workflow" gets a `prune_only` input that runs only the prune job (listing or deleting, by the same switch).
- **Docs.** `docs/install-pc.md` and the README say how notes are made, that only the newest 4 releases are kept, and how to install an older version from source (`.../archive/<commit>.zip`).

No change to the plugin, the tools' behaviour or the release gate. Tools version unchanged.

## What the rule would remove today

Kept: `deploy-v0.63.0` (latest), `deploy-v0.62.0`, `deploy-v0.61.1`, `deploy-v0.61.0`.

Releases and their tags removed (28): 0.31.0, 0.31.1, 0.33.0, 0.35.0, 0.36.0, 0.37.0, 0.38.0, 0.41.0, 0.42.0, 0.43.0, 0.43.1, 0.44.0, 0.46.2, 0.46.3, 0.48.1, 0.50.0, 0.50.1, 0.51.0, 0.51.1, 0.52.0, 0.52.2, 0.53.0, 0.54.0, 0.55.0, 0.56.0, 0.56.1, 0.58.0, 0.59.0.

Tags without a release removed (8): 0.23.0, 0.24.0, 0.25.0, 0.28.0, 0.29.0, 0.30.0, 0.30.1, 0.32.0.

(Listed 2026-10-15 from the GitHub API; the first prune run lists the then-current set again before anything is deleted.)

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-pc-install`: the release notes requirement becomes its own requirement (template, "What's new" from PR text, banned-word check, template test), and a new requirement for release retention.

## Impact

- `.github/workflows/release-deploy.yml`: notes step calls the script and the banned-word check; new `prune` job after `manifest`; `prune_only` input; needs `BANNED_WORDS` secret in the release job.
- New `tools/deploy/release-notes.md`, `scripts/release_notes.py`; `scripts/release_version.py` gains a `--prune` listing helper.
- Tests: `test/pc-tools/test_release_notes.py` (template coverage, PR parsing, rendering), more cases in `test_release_version.py` (prune selection).
- Docs: `docs/install-pc.md`, README.
- Repository settings: variable `RELEASE_PRUNE` (Toni sets it; not part of the PR).
