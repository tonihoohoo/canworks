## ADDED Requirements

### Requirement: Advertised port from the config
The local-network advertisement SHALL carry the config's `diagnostics.port` when `install-link.sh` is not given `--diag-port`.

#### Scenario: Port 7541
- **WHEN** discovery is installed for a config with `diagnostics.port` 7541
- **THEN** the advertisement says port 7541 and a PC lists the device with 7541
