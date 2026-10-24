## ADDED Requirements

### Requirement: Probe reads Python and openssl
The device probe SHALL report the version of `python3` on PATH (or null) and whether the `openssl` command is there. The **Remote CAN adapter** row SHALL then offer no **Turn on…**, **Add…** or **Change…** and say in one sentence what the device is missing: Python 3.11 or newer, or the `openssl` command.

#### Scenario: Old Python on the device
- **WHEN** the probe reports `python3` 3.9
- **THEN** the row says the remote CAN adapter needs Python 3.11 or newer on the device, and offers no **Turn on…**

## MODIFIED Requirements

### Requirement: Remote CAN adapter job
Each adapter action SHALL run as an install job with the release's `install-adapter.sh` at the newest release X. The configurator SHALL download the release's `install-adapter.sh` and `canworks-adapter-X.pyz` on the PC and upload them with the token's verifier to the job's upload folder, so the job downloads nothing; when the PC cannot download them, the job SHALL download them on the device. The job installs the file in `/opt/canworks-adapter` when that version is not there and installs the server as a service of the SSH user. Adapter actions SHALL NOT be blocked because the device cannot reach github.com while the PC can, nor by the bridge build's free-space check. A root SSH login SHALL be refused with one sentence to log in as a user with sudo. The first server SHALL use port 7536, a server on another interface the next free port from 7537.

#### Scenario: Turn on with no config
- **WHEN** no config is open, the device has can0 up at 500 kbit/s, no bridge and no internet access, and the user turns the remote CAN adapter on with the defaults from a PC with internet access
- **THEN** the job installs the uploaded file and the service without downloading anything on the device, and the row reads `can0 · 500 kbit/s · running · changes allowed`
