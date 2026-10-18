## ADDED Requirements

### Requirement: Release install reports its version

When `scripts/install-runtime.sh` installs a release, the plugin and `canworks-sim` SHALL be built with that release's version, so the diagnostics channel and `canworks-sim --version` report it, although the downloaded source has no git history.

#### Scenario: Version after a one-line install
- **WHEN** the one-line install installs release `0.84.0` on a device
- **THEN** `canworks-sim --version` prints `0.84.0`, not `unknown`
