## MODIFIED Requirements

### Requirement: Simulator installed with the plugin
`scripts/install-stock.sh` SHALL build and install `canworks-canopen-sim` with the plugin, under the plugin's prefix, with a link in `/usr/local/bin` on native installs, and the uninstall SHALL remove both. In Docker mode the simulator SHALL be installed inside the runtime container and be runnable with `docker exec`. An install SHALL also remove the earlier `canworks-sim` binary under the plugin's prefix and its `/usr/local/bin/canworks-sim` link when that link points into this install, printing one line, so a bench device updated from an older install keeps no dangling link.

#### Scenario: Native install
- **WHEN** `install-stock.sh` finishes on a native runtime
- **THEN** `canworks-canopen-sim --version` prints the same version as the plugin

#### Scenario: Update from an install with the old name
- **WHEN** `install-stock.sh` runs on a native runtime that has `/usr/local/bin/canworks-sim` linking into `/opt/canworks`
- **THEN** afterwards that link and the old binary are gone, `canworks-canopen-sim` is installed, and the output names the removal

### Requirement: One-line install and update on the device

The repository SHALL provide `scripts/install-runtime.sh`, and `docs/install-stock.md` and the README SHALL give, first among the install routes, the one line that runs it straight from the repository on GitHub as root (`curl -LsSf <url> | sudo bash`, options after `-s --`). It SHALL download the source of the newest `deploy-v` release (or of `--version <version>`), found from the `releases/latest` redirect without the GitHub API, and run that release's `scripts/install-stock.sh` with every other option given, without a git checkout on the device. Running the same line again SHALL install the newer release over the existing one as `install-stock.sh` re-runs do; `--uninstall` and the other `install-stock.sh` options SHALL pass through unchanged. It SHALL never install code from `main`. Without root it SHALL exit non-zero and say how to run it. It SHALL remove its downloaded source afterwards. The documentation SHALL keep the git checkout route and show the script pinned to a release.

The same install SHALL be possible from a Windows, macOS or Linux PC onto a remote Linux device over SSH: `scripts/install-runtime.sh --ssh USER@HOST` (macOS, Linux) and `scripts/install-runtime.ps1 -Ssh USER@HOST` (Windows, PowerShell 5.1 with the built-in OpenSSH client), each runnable with one documented line straight from GitHub. The PC side SHALL need no root, no Python and no canworks tools; it SHALL resolve the release once and run the device side over `ssh -t` with that exact `--version`, so a `sudo` password prompt works and both sides agree on the release. Options other than the PC side's own (`--ssh`, `--port`, `--identity`, `--dry-run`) SHALL pass through to the device. The PC side SHALL exit with the device side's exit status, and SHALL say so before connecting when `ssh` is missing.

CI SHALL run `shellcheck` on the script and test its release lookup, option pass-through and the SSH command line it builds (for both scripts) without network access.

#### Scenario: Install on a fresh device
- **WHEN** an operator pastes the documented line on a Raspberry Pi with a stock OpenPLC Runtime v4 and no canworks checkout
- **THEN** the newest release's `install-stock.sh` runs, the plugin is installed as in Requirement: Install on a stock runtime, and no source folder of the release is left behind

#### Scenario: Update
- **WHEN** the line is run again on a device that has the plugin of an older release
- **THEN** the newest release is built and installed, `canworks-canopen-sim --version` prints its version and `plugins.conf` still has exactly one `canworks` line

#### Scenario: Options pass through
- **WHEN** the operator runs the line with `-s -- --with-link`
- **THEN** `install-stock.sh` of the release runs with `--with-link`

#### Scenario: Install from a Windows PC
- **WHEN** a user on Windows runs the documented PowerShell line with `-Ssh pi@rpi.local` against a device with a stock runtime
- **THEN** an SSH session to `pi@rpi.local` asks for the `sudo` password when needed, the newest release's `install-stock.sh` runs on the device, and the PowerShell command ends with its exit status

#### Scenario: Remote update from a Mac with options
- **WHEN** a Mac user runs `install-runtime.sh --ssh pi@rpi.local --with-link`
- **THEN** the device runs the newest release's `install-stock.sh --with-link`, and the release named on the Mac and on the device is the same

#### Scenario: Not root
- **WHEN** the line is run without `sudo`
- **THEN** the script exits non-zero before downloading anything and shows the line with `sudo`

### Requirement: Release install reports its version

When `scripts/install-runtime.sh` installs a release, the plugin and `canworks-canopen-sim` SHALL be built with that release's version, so the diagnostics channel and `canworks-canopen-sim --version` report it, although the downloaded source has no git history.

#### Scenario: Version after a one-line install
- **WHEN** the one-line install installs release `0.84.0` on a device
- **THEN** `canworks-canopen-sim --version` prints `0.84.0`, not `unknown`
