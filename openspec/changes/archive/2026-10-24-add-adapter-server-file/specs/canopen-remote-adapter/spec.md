## ADDED Requirements

### Requirement: Adapter server file
Each `deploy-v` release SHALL attach `canworks-adapter-<version>.pyz` and `install-adapter.sh` as assets. The file SHALL run `canworks-diag` (`python3 FILE COMMAND …`, `adapter-serve` included) on Python 3.11 or newer with only the standard library, and `--version` SHALL print the release version.

#### Scenario: Bare Python
- **WHEN** the file is copied to a Linux machine with Python 3.11, no pip packages and no network, and the user runs `python3 canworks-adapter-X.pyz adapter-serve --adapter socketcan:can0 --bitrate 500 --allow-changes`
- **THEN** the server starts and prints its token, and a PC with the tools scans, reads and writes SDOs through it as with a server from the installed PC tools

### Requirement: Adapter server file contents
The file SHALL carry canworks without the configurator, the editor library, the Node-RED package and the CODESYS code, and python-can and pyserial with their pure-Python dependencies at the release's locked versions, and no other package. It SHALL be at most 2 MB.

#### Scenario: Release asset
- **WHEN** release X is created
- **THEN** `canworks-adapter-X.pyz` is at most 2 MB and holds no `canworks/configurator/`, no `cantools`, no `paramiko` and no compiled extension

### Requirement: Adapter server file on an old Python
On a Python older than 3.11 the file SHALL exit with status 1 and one sentence saying that it needs Python 3.11 or newer.

#### Scenario: Old Python
- **WHEN** the user runs the file with Python 3.9
- **THEN** it exits with status 1 saying that it needs Python 3.11 or newer, and starts nothing

### Requirement: Service from the file
`adapter-serve --install-service` run from the file SHALL write the unit's `ExecStart` as the Python that runs it and the file's absolute path, followed by the server options.

#### Scenario: Installed from the file
- **WHEN** root runs `python3 /opt/canworks-adapter/canworks-adapter.pyz adapter-serve --adapter socketcan:can0 --bitrate 500 --install-service --service-user pi`
- **THEN** the unit's `ExecStart` starts `/usr/bin/python3 /opt/canworks-adapter/canworks-adapter.pyz adapter-serve` with those options, and the service runs after a reboot

## MODIFIED Requirements

### Requirement: Adapter server install script
Each release SHALL ship `scripts/install-adapter.sh` (`--version`, `--file`, `--adapter`, `--bitrate`, `--user`, `--port`, `--allow-changes`, `--without-discovery`, `--verifier-file`). It SHALL first check for `python3` 3.11 or newer and the `openssl` command and stop with one sentence naming what is missing. It SHALL install the release's adapter server file as `/opt/canworks-adapter/canworks-adapter.pyz` unless that version is there, from `--file PATH` when given and otherwise downloaded from the release, SHALL remove an `/opt/canworks-adapter/venv` left by an older install, and SHALL NOT run pip, make a venv or install packages. It SHALL add the user to `dialout` for a serial adapter and install the server with `--install-service --service-user`. It SHALL print `::canworks-step` lines and never a token.

#### Scenario: Device with the bridge
- **WHEN** the script runs for release X on a device whose `/opt/canworks-adapter/canworks-adapter.pyz` is the file of X
- **THEN** it downloads nothing and only installs and starts the service

#### Scenario: Uploaded file on a device without internet
- **WHEN** the script runs with `--version X --file /tmp/up/canworks-adapter-X.pyz` on a device that cannot reach github.com
- **THEN** the file is installed and the service started, and nothing is downloaded

#### Scenario: No openssl
- **WHEN** the script runs on a device without the `openssl` command
- **THEN** it stops before installing anything, saying that the adapter server needs the `openssl` command

### Requirement: Adapter server uninstall
`install-adapter.sh --uninstall --adapter TYPE:CHANNEL` SHALL remove that server and its Avahi file and nothing else; `--uninstall` alone SHALL remove every adapter server, and the last one removed SHALL take the installed file (and an old venv) with it. CI SHALL run `shellcheck` on the script and test install and uninstall with a stub download and systemctl.

#### Scenario: Uninstall one server
- **WHEN** servers run on can0 and can1 and the script runs with `--uninstall --adapter socketcan:can1`
- **THEN** `canworks-adapter-can1.service` is gone, the can0 server keeps running, and `/opt/canworks-adapter/canworks-adapter.pyz` is still there
