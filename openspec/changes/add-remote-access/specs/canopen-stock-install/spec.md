## ADDED Requirements

### Requirement: Link and discovery install options
`scripts/install-stock.sh` and `scripts/install-bridge.sh` SHALL install the Avahi advertisement by default (skipped with `--without-discovery`) and, with `--with-link`, the link service: a Python virtual environment with the pinned `iroh` package under the install prefix, the `canworks-link` command, `canworks-link.service` (enabled and started, watching the deployed config), and `/etc/canworks-link/` with no paired PCs. No other step on the device SHALL be needed. `--uninstall` SHALL remove the service, the command and the Avahi file and keep `/etc/canworks-link/` unless `--purge` is given.

#### Scenario: Fresh install with the link
- **WHEN** `install-stock.sh --with-link` runs on a device with no internet route
- **THEN** the service starts, makes no outside connection, appears in discovery with its link ID, and the first PC that logs in with the right token on the LAN gets paired
