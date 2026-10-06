## ADDED Requirements

### Requirement: Simulator installed with the plugin
`scripts/install-stock.sh` SHALL build and install `openplc-canopen-sim` with the plugin, under the plugin's prefix, with a link in `/usr/local/bin` on native installs, and the uninstall SHALL remove both. In Docker mode the simulator SHALL be installed inside the runtime container and be runnable with `docker exec`.

#### Scenario: Native install
- **WHEN** `install-stock.sh` finishes on a native runtime
- **THEN** `openplc-canopen-sim --version` prints the same version as the plugin
