## ADDED Requirements

### Requirement: Link and discovery install options
`scripts/install-stock.sh` and `scripts/install-bridge.sh` SHALL install the Avahi advertisement by default (skipped with `--without-discovery`) and, with `--with-link`, the link service: a Python virtual environment with the pinned `iroh` package under the install prefix, the `canworks-link` command, `canworks-link.service` (enabled, relays off) and `/etc/canworks-link/` with an empty allow-list. `--uninstall` SHALL remove the service, the command and the Avahi file and keep `/etc/canworks-link/` unless `--purge` is given.

#### Scenario: Fresh install with the link
- **WHEN** `install-stock.sh --with-link` runs on a device with no internet route
- **THEN** the service starts with relays off, `canworks-link id` prints the device's link ID, and no PC can connect until one is allowed
