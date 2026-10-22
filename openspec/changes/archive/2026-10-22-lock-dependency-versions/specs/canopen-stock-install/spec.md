## ADDED Requirements

### Requirement: Locked dependency versions on the device
`install-stock.sh` SHALL take `--constraints FILE` and install the tools into `<prefix>/venv` with it. `install-runtime.sh` and `install-runtime.ps1` SHALL download the release's `canworks-<version>-constraints.txt` and pass it on. When no file is given and `uv` is on PATH, `install-stock.sh` SHALL export the constraints from the checkout's `tools/deploy/uv.lock`. Otherwise it SHALL say in one line that the dependency versions are not locked and install as before.

#### Scenario: Release install on the Pi
- **WHEN** release 0.110.0 is installed with `install-runtime.sh`
- **THEN** `pip freeze` in `/opt/canworks/venv` lists the versions of `canworks-0.110.0-constraints.txt` for every package that file names

#### Scenario: Checkout without uv
- **WHEN** `install-stock.sh` runs from a checkout with no `--constraints` and no `uv`
- **THEN** it says the dependency versions are not locked and installs as before

### Requirement: dcf-tools venv pinned
`build-lely.sh` SHALL install dcf-tools with the exact versions in `scripts/dcf-tools-constraints.txt`. That file SHALL name the Lely commit it was made for, and a test SHALL fail when the Lely commit changes without it.

#### Scenario: Lely commit bumped alone
- **WHEN** a change updates `_lely_dcf/VERSION` and not `scripts/dcf-tools-constraints.txt`
- **THEN** the test fails, naming both files
