## ADDED Requirements

### Requirement: Locked dependency versions
The tools' dependencies SHALL be locked in `tools/deploy/uv.lock`, resolved for every supported system and for Python 3.11 and newer, while `pyproject.toml` keeps open minimum versions. Each release SHALL attach `canworks-<version>-constraints.txt`, the lock of the release's commit exported with exact versions and without hashes. The one-line installers SHALL install a release with that file as `uv tool install --constraints`.

#### Scenario: Same versions a month apart
- **WHEN** canworks 0.110.0 is installed with the one-line installer on two PCs a month apart, and `cantools` has had a new major release in between
- **THEN** both PCs have the `cantools` version in `canworks-0.110.0-constraints.txt`

#### Scenario: Release asset
- **WHEN** a version bump is released
- **THEN** the release has `canworks-<version>-constraints.txt`, and it pins every package in `uv.lock` of the tagged commit except `canworks` itself

### Requirement: Installs without a lock
When the release has no constraints file, the one-line installers SHALL say in one line that the release does not lock its dependency versions and install without constraints. When the file exists but cannot be downloaded, the install SHALL fail with a message and leave the installed tools unchanged. With `--wheel FILE` the installers SHALL take `--constraints FILE`, and without it install unlocked with the same one line.

#### Scenario: Release older than the lock
- **WHEN** the user installs a release that has no constraints asset with `--version`
- **THEN** the installer says the release does not lock its dependency versions and installs it as before

#### Scenario: Constraints download fails
- **WHEN** the release has a constraints asset and its download fails
- **THEN** the installer stops with a message naming the file, and the installed tools are unchanged

