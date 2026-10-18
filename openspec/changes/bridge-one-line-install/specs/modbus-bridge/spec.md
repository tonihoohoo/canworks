## ADDED Requirements

### Requirement: One-line bridge install and update

`scripts/install-bridge.sh` SHALL also run straight from the repository on GitHub as root (`curl -LsSf <url> | sudo bash`, options after `-s --`), and `docs/modbus-bridge.md` and the README SHALL give that line first among the bridge's install routes. Run outside a checkout, it SHALL download the source of the newest `deploy-v` release (or of `--version <version>`), found from the `releases/latest` redirect without the GitHub API, run that release's `scripts/install-bridge.sh` with every other option given, build the bridge with the release's version, and remove the downloaded source afterwards. It SHALL never install code from `main`. Running the same line again SHALL install the newer release; `--uninstall`, `--purge` and the other options SHALL pass through unchanged. Without root it SHALL exit non-zero before downloading anything and show the line with `sudo`. Run from a checkout without `--ssh` or `--version`, it SHALL install the checkout as before. The documentation SHALL keep the checkout route and the container image, and show the line pinned to a release.

The same install SHALL be possible from a Windows, macOS or Linux PC onto a remote Linux device over SSH: `install-bridge.sh --ssh USER@HOST` (macOS, Linux) and `scripts/install-bridge.ps1 -Ssh USER@HOST` (Windows PowerShell 5.1 with the built-in OpenSSH client), each runnable as one documented line straight from GitHub. The PC side SHALL need no root, no Python and no canworks tools; it SHALL resolve the release once and run the device side over `ssh -t` with that exact `--version`, so a `sudo` password prompt works and both sides agree on the release. Options other than the PC side's own (`--ssh`, `--port`, `--identity`, `--dry-run`) SHALL pass through to the device. The PC side SHALL exit with the device side's exit status, and SHALL say so before connecting when `ssh` is missing.

CI SHALL run `shellcheck` on the script and test, without network access, its release lookup, option pass-through and the `ssh` and `scp` command lines both scripts build.

#### Scenario: Install on a fresh device
- **WHEN** an operator pastes the documented line on a Linux device with CAN interfaces and no canworks checkout
- **THEN** the newest release's bridge is built and installed with its unit `canworks-bridge@.service`, `canworks-bridge --version` prints the release, and no source folder of the release is left behind

#### Scenario: Install from a Windows PC
- **WHEN** a user on Windows runs the documented PowerShell line with `-Ssh pi@rpi.local`
- **THEN** an SSH session asks for the `sudo` password when needed, the newest release's bridge is installed on the device, and the PowerShell command ends with the device side's exit status

#### Scenario: Not root
- **WHEN** the device line is run without `sudo`
- **THEN** the script exits non-zero before downloading anything and shows the line with `sudo`

### Requirement: Bridge instance from the install line

`install-bridge.sh` SHALL take `--instance NAME --config DIR` (`-Instance`, `-Config` in `install-bridge.ps1`), where `DIR` holds a `canworks.json` and the files it names. After installing, it SHALL copy the folder's files to `/etc/canworks-bridge/NAME/`, run the bridge's `--check-only` on it, and when the check passes enable and start (or restart) `canworks-bridge@NAME`. When the check fails it SHALL leave the instance's service stopped, print the check's messages and exit non-zero. `NAME` SHALL be a plain name (letters, digits, `-`, `_`), and either option without the other SHALL be refused before anything is installed. With `--ssh`, the PC side SHALL first copy `DIR` to a temporary folder on the device with `scp` (same port and key), pass that folder to the device side, and the device side SHALL remove it afterwards.

#### Scenario: Bridge set up from a Mac
- **WHEN** a Mac user runs `install-bridge.sh --ssh pi@rpi.local --instance line1 --config ./line1`
- **THEN** the device has `/etc/canworks-bridge/line1/canworks.json` with the folder's EDS files, `canworks-bridge@line1` is enabled and running, and no temporary upload folder is left on the device

#### Scenario: Config that fails its check
- **WHEN** the config in `DIR` names an EDS file the folder does not have
- **THEN** the install line exits non-zero with the check's message and `canworks-bridge@NAME` is not started

### Requirement: Bridge update restarts running instances

When `install-bridge.sh` installs a new bridge binary over an existing one, it SHALL restart every `canworks-bridge@` instance that was active and list them; stopped and disabled instances SHALL stay as they were.

#### Scenario: Update with two bridges
- **WHEN** the install line runs on a device where `canworks-bridge@press` runs and `canworks-bridge@feeder` is stopped
- **THEN** `press` runs the new binary afterwards and `feeder` is still stopped

### Requirement: Bridge prefix next to a Docker runtime

When no `--prefix` is given and the default prefix `/opt/canworks` holds a Python environment the host cannot use (a prefix the OpenPLC runtime's Docker container set up), `install-bridge.sh` SHALL install into `/opt/canworks-bridge` instead and say so; `--uninstall` and later updates without `--prefix` SHALL find that install. An explicit `--prefix /opt/canworks` SHALL keep today's refusal with its message.

#### Scenario: Device with the managed Docker runtime
- **WHEN** the install line runs without `--prefix` on a device whose runtime runs in Docker with the canworks plugin
- **THEN** the bridge is installed under `/opt/canworks-bridge`, the output says so, and the runtime's `/opt/canworks` is unchanged
