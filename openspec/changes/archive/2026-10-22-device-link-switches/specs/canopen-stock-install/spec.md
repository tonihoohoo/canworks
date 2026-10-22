## ADDED Requirements

### Requirement: Link script on its own
`scripts/install-link.sh` SHALL run on its own on a device. Installing the link from a downloaded copy of the script (no checkout next to it), or with `--version X`, SHALL download the `deploy-vX` release tarball (the newest release without `--version`) and run that release's `install-link.sh` with the same options, as `install-bridge.sh` does; `--dry-run` SHALL print the download and the command. It SHALL take `--without-discovery` (the link service without the advertisement, removing an existing Avahi file), `--discovery-only` (the advertisement alone, the same as `--without-link`), `--remove-discovery` (removes the Avahi file only) and, with `--uninstall`, `--keep-discovery` (keeps the advertisement without the link ID). The Avahi file SHALL carry the link ID whenever the link service is installed, whichever option wrote it. Uninstalling the link SHALL keep `/etc/canworks-link` (key and paired PCs) unless `--purge` is given.

#### Scenario: Discovery after the link
- **WHEN** `install-link.sh --discovery-only --config /opt/canworks/lib/canworks.json` runs on a device whose link service is installed
- **THEN** the Avahi file carries the link's ID and the link keeps running

#### Scenario: Link off, discovery stays
- **WHEN** `install-link.sh --uninstall --keep-discovery` runs on a device with the link and the advertisement
- **THEN** the link service is gone, `/etc/canworks-link` stays, and the Avahi file is there without the link ID

#### Scenario: From the release
- **WHEN** `install-link.sh --version 0.114.0 --config /opt/canworks/lib/canworks.json` runs from a downloaded copy of the script
- **THEN** it downloads `deploy-v0.114.0` and installs the link from that release's PC tools package
