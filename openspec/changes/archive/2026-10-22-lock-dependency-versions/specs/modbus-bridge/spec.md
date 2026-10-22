## ADDED Requirements

### Requirement: Bridge installs locked dependency versions
`install-bridge.sh` SHALL take `--constraints FILE` and install the tools into the bridge's venv with it, falling back as `install-stock.sh` does when none is given. A release install through `install-runtime.sh` or the bridge's one-line install SHALL pass the release's constraints file. The bridge image SHALL be built with the constraints exported from `uv.lock` of the commit it is built from.

#### Scenario: Bridge image
- **WHEN** the bridge image is built on `main`
- **THEN** its venv holds the dependency versions of that commit's `uv.lock`
