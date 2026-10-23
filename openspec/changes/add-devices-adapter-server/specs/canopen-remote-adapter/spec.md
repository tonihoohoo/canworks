## ADDED Requirements

### Requirement: Root installs of the server
`canworks-diag adapter-serve --install-service --service-user USER` SHALL install the service to run as USER when root runs it without `SUDO_USER`, with the token's verifier in USER's settings folder; USER root SHALL be refused. `--token-verifier-file FILE` SHALL store the verifier in FILE (made with the token elsewhere) instead of making or reading a token, and SHALL be refused when FILE does not hold a valid verifier. Without a token option an install SHALL keep the stored verifier.

#### Scenario: Installed by a root job
- **WHEN** root runs `canworks-diag adapter-serve --adapter socketcan:can0 --bitrate 500 --install-service --service-user pi --token-verifier-file v`
- **THEN** the unit runs as `pi`, `~pi/.config/canworks/adapter-serve.json` holds the verifier from `v`, no token is printed, and a PC logs in with the token the verifier was made from

### Requirement: Adapter server install script
Each release SHALL ship `scripts/install-adapter.sh` (`--version`, `--interface`, `--bitrate`, `--user`, `--port`, `--allow-changes`, `--without-discovery`, `--verifier-file`). It SHALL use `/opt/canworks/venv/bin/canworks-diag`, first installing the release's locked PC tools there when missing (no Lely, no build), add the user to `dialout` for a serial adapter, and install the server with `--install-service --service-user`. It SHALL print `::canworks-step` lines and never a token.

#### Scenario: Device with the bridge
- **WHEN** the script runs on a device whose `/opt/canworks/venv` has `canworks-diag`
- **THEN** it installs nothing with pip and only installs and starts the service

### Requirement: Adapter server uninstall
`install-adapter.sh --uninstall --interface IF` SHALL remove that interface's server and its Avahi file and nothing else. CI SHALL run `shellcheck` on the script and test install and uninstall with a stub pip and systemctl.

#### Scenario: Uninstall one server
- **WHEN** servers run on can0 and can1 and the script runs with `--uninstall --interface can1`
- **THEN** `canworks-adapter-can1.service` is gone and the can0 server keeps running
