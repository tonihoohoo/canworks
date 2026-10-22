## MODIFIED Requirements

### Requirement: Updater matches the installers

The updater's `uv tool install` arguments SHALL stay the same as those of `install-pc.sh` and `install-pc.ps1`, including `--constraints` with the new release's constraints file, downloaded the same way and with the same handling of a release that has none.

#### Scenario: Same arguments as the installers
- **WHEN** the test suite compares the `uv tool install` arguments in `install-pc.sh`, `install-pc.ps1` and the updater
- **THEN** they are the same, and the test fails when one of them changes alone

#### Scenario: Update installs the locked versions
- **WHEN** the configurator updates from 0.110.0 to 0.111.0
- **THEN** the tools' environment has the dependency versions of `canworks-0.111.0-constraints.txt`
