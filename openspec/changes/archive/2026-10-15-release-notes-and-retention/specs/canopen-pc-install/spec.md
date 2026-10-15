## MODIFIED Requirements

### Requirement: Release wheel

Each release of the PC-side tools SHALL publish exactly one platform-independent wheel (`py3-none-any`) of the tools package as an asset of a GitHub release named and tagged `deploy-v<version>`, where `<version>` is the package version.

The release SHALL be created automatically, without a person pushing a tag, for a commit on `main` when all of these hold: the package version in `pyproject.toml` equals `__version__`; no release or tag `deploy-v<version>` exists yet; the `CI` workflow succeeded on that commit; and the PC tools workflow succeeded on that commit or did not run for it. The tag SHALL point at that commit. While a required run on the commit is still pending, nothing SHALL be published yet, and a later completion SHALL publish it. When a required run failed, nothing SHALL be published for that commit.

An existing release SHALL never be replaced, re-tagged or given a new asset by the automation; running it again for a released version SHALL do nothing and succeed. Removing old releases under the retention rule (Requirement: Release retention) is the only change the automation SHALL make to an existing release.

Pushing a tag `deploy-v<version>` by hand SHALL still publish a release, and SHALL fail without publishing anything when `<version>` differs from the package version.

Each release's notes SHALL be made as described in Requirement: Release notes.

#### Scenario: Version bump merged
- **WHEN** a pull request that changes the package version from 0.20.0 to 0.21.0 is merged to `main`, and `CI` and the PC tools workflow both succeed on the merge commit
- **THEN** a GitHub release `deploy-v0.21.0` exists, its tag points at the merge commit, and it has the asset `canworks-0.21.0-py3-none-any.whl`

#### Scenario: No version change
- **WHEN** a commit on `main` keeps the package version 0.21.0 and `deploy-v0.21.0` is already released
- **THEN** no release is created or changed

#### Scenario: Tests failed
- **WHEN** a version bump is merged and the PC tools workflow fails on that commit
- **THEN** no release `deploy-v<version>` is created for that commit

#### Scenario: Second workflow still running
- **WHEN** `CI` finishes green on a version-bump commit while the PC tools workflow on the same commit is still running
- **THEN** nothing is published until the PC tools workflow finishes, and the release is created then if it succeeded

#### Scenario: Older versions are not backfilled
- **WHEN** `main` carries version 0.21.0 and versions 0.18.0 and 0.19.0 were never released
- **THEN** only `deploy-v0.21.0` is released

#### Scenario: Tag matches the package version
- **WHEN** the tag `deploy-v0.16.0` is pushed by hand and the package version at that commit is 0.16.0
- **THEN** a GitHub release `deploy-v0.16.0` exists with the asset `canworks-0.16.0-py3-none-any.whl`

#### Scenario: Tag does not match
- **WHEN** the tag `deploy-v0.16.1` is pushed and the package version is 0.16.0
- **THEN** the release job fails, names both versions, and no release asset is published

## ADDED Requirements

### Requirement: Release notes

Each release's notes SHALL be generated from a template file in the repository, `tools/deploy/release-notes.md`, filled in with the version and repository owner. The template SHALL say what the release contains and how to install or use each part: the wheel (with the uv install command), `canworks.stlib`, and every container image the release publishes.

A test in CI SHALL fail when the template does not name every asset the release workflow attaches, every container image it publishes, and every command the tools package installs, so a change to what a release ships cannot merge without updating the description.

After the template text, the notes SHALL have a "What's new" section with one entry per pull request merged between the previous `deploy-v` release and the released commit, in merge order: the pull request title as a link, followed by the text of its "After:" paragraph when the pull request description has one, else the title alone. A commit in that range without a pull request SHALL be listed by its subject. The notes SHALL end with a link comparing the previous release tag with the new one. Without a previous release the "What's new" section and link SHALL be left out.

Before anything is published, the complete notes SHALL pass the banned-word check; when they do not, the release job SHALL fail without creating the tag or the release and SHALL name the pull request whose text matched, never the matched text.

#### Scenario: Notes describe the release
- **WHEN** `deploy-v0.64.0` is released after `deploy-v0.63.0`, and PR #101 merged in between has a description with an "After:" paragraph
- **THEN** the release notes contain the template text with 0.64.0 in the install command and image tags, and a "What's new" entry linking PR #101 followed by its "After:" text, and a compare link from `deploy-v0.63.0` to `deploy-v0.64.0`

#### Scenario: Unreleased versions in between
- **WHEN** version 0.60.0 was never released and `deploy-v0.61.0` follows `deploy-v0.59.0`
- **THEN** "What's new" for 0.61.0 lists the pull requests merged for 0.60.0 as well

#### Scenario: Pull request without an After paragraph
- **WHEN** a pull request in the range has a description without an "After:" paragraph
- **THEN** its entry is the linked title alone and the release is still published

#### Scenario: New image without template update
- **WHEN** a pull request adds a container image to the release workflow and does not mention it in `tools/deploy/release-notes.md`
- **THEN** CI fails on that pull request and names the missing image

#### Scenario: Banned word in a pull request description
- **WHEN** a pull request description in the range was edited after merge to contain a banned word, and a version bump is then released
- **THEN** the release job fails naming that pull request number, and no tag or release `deploy-v<version>` is created

### Requirement: Release retention

After a release and its container images are published, the automation SHALL keep the newest 4 `deploy-v` releases, ordered by version, and SHALL delete every older `deploy-v` release together with its tag. It SHALL also delete `deploy-v` tags that have no release and are older than the oldest kept release. It SHALL NOT delete the release it just published, the release GitHub marks as latest, draft releases, tags or releases whose name does not start with `deploy-v`, or container images.

Deletion SHALL only happen while the repository variable `RELEASE_PRUNE` is `on`; otherwise the job SHALL only list, in the run summary, the releases and tags it would delete. Starting the workflow by hand with `prune_only` SHALL run only this step, with the same switch.

When publishing the release or its images fails, nothing SHALL be deleted.

#### Scenario: Fifth release
- **WHEN** `RELEASE_PRUNE` is `on`, releases 0.61.0, 0.61.1, 0.62.0 and 0.63.0 exist, and 0.64.0 is released with its images
- **THEN** releases 0.61.1, 0.62.0, 0.63.0 and 0.64.0 remain, and release and tag `deploy-v0.61.0` are gone

#### Scenario: Switch off
- **WHEN** `RELEASE_PRUNE` is not set and a release is made while 32 older releases exist
- **THEN** no release or tag is deleted, and the run summary lists the 29 releases and the orphan tags that would be

#### Scenario: Image publish failed
- **WHEN** `RELEASE_PRUNE` is `on` and the image job fails for a new release
- **THEN** no older release or tag is deleted

#### Scenario: Order by version, not date
- **WHEN** `deploy-v0.62.1` is pushed by hand after `deploy-v0.64.0` exists
- **THEN** the kept set is the four highest versions, and `deploy-v0.62.1` is deleted only if it is not among them

#### Scenario: Other tags untouched
- **WHEN** the repository has a tag `v1.0` and a release made from it
- **THEN** pruning never deletes them
