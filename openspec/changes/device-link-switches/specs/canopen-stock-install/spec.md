## ADDED Requirements

### Requirement: Link script on its own
`scripts/install-link.sh` SHALL run on its own on a device: with `--version X`, or when it runs outside a checkout, it SHALL download the `deploy-vX` release tarball (the newest release without `--version`) and run that release's `install-link.sh` with the same options, as `install-bridge.sh` does. It SHALL take `--without-discovery` (the link service without the advertisement, removing an existing Avahi file) and `--discovery-only` (the advertisement alone, the same as `--without-link`). The Avahi file SHALL carry the link ID whenever the link service is installed, whichever option wrote it, and SHALL be written without it when the link is uninstalled while the advertisement stays. Uninstalling the link alone SHALL keep `/etc/canworks-link` (key and paired PCs) unless `--purge` is given.

#### Scenario: Discovery after the link
- **WHEN** `install-link.sh --discovery-only --config /opt/canworks/lib/canworks.json` runs on a device whose link service is installed
- **THEN** the Avahi file carries the link's ID and the link keeps running

#### Scenario: From the release
- **WHEN** `install-link.sh --version 0.113.0 --config /opt/canworks/lib/canworks.json` runs from a downloaded copy of the script
- **THEN** it downloads `deploy-v0.113.0` and installs the link from that release's PC tools package
