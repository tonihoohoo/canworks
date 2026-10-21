## MODIFIED Requirements

### Requirement: Dependency floors without known vulnerabilities
The PC tools SHALL require Python 3.11 or newer and dependency versions without known advisories in the code paths they use, including `zeroconf>=0.149.16` and, on Windows, `libusb>=1.0.30`. The Python floor SHALL NOT be higher than the Python of the pinned runtime image, because the same package runs there.

#### Scenario: Fresh install
- **WHEN** the PC tools are installed into an environment with zeroconf 0.148
- **THEN** zeroconf is upgraded to a fixed version

#### Scenario: Run from a checkout on Windows
- **WHEN** a Windows user runs `uv run` on the deploy tool from a source checkout
- **THEN** uv resolves the dependencies, including `libusb`, without a Python version error

#### Scenario: Python 3.10
- **WHEN** a user installs the tools with pip on Python 3.10
- **THEN** pip refuses, saying the package needs Python 3.11 or newer

### Requirement: One-line installer

The repository SHALL provide `scripts/install-pc.sh` (macOS and Linux, POSIX `sh`) and `scripts/install-pc.ps1` (Windows, PowerShell 5.1), and the documentation SHALL give, first among the install routes, the one line per operating system that runs them from the newest release's assets on GitHub (Requirement: Install scripts from the release): on macOS and Linux piped into `sh`, on Windows downloaded to a file and run from it (Requirement: Windows installers without download-and-run). Each script SHALL install uv when uv is not found (`install-pc.sh` with uv's official installer, `install-pc.ps1` from uv's release zip checked against its published SHA-256), use it in the same session, and install the wheel of the newest `deploy-v` release (or of `--version <version>`) from its release download URL with `uv tool install --force --compile-bytecode --python 3.14` (or the Python given with `--python` / `-Python`), so running the same line again updates to the newest release. When the uv found is older than the first uv release that knows the default Python (0.9.0 for 3.14), the script SHALL run `uv self update`, and when that fails SHALL exit non-zero saying to update uv with the tool that installed it. The script SHALL find the newest release from the `releases/latest` redirect without the GitHub API, SHALL install only released wheels (never the code on `main`), and with `--wheel <file>` SHALL install that local wheel instead. `--uninstall` SHALL remove the tools and leave uv and the settings folder. When uv's bin folder is not on PATH, the script SHALL add it (`uv tool update-shell`) and say to open a new terminal. The script SHALL print the installed version at the end and exit non-zero, saying why, when any step fails. The documentation SHALL also show the same scripts pinned to a release and how to download and read a script before running it.

CI SHALL run `shellcheck` on `install-pc.sh` and test both scripts' release lookup and argument handling without network access, and the PC tools job SHALL install through the scripts (with `--wheel`) on each of its runners.

#### Scenario: Fresh PC
- **WHEN** a Windows user with neither uv nor Python pastes the documented PowerShell line
- **THEN** uv is installed from its release zip into `%USERPROFILE%\.local\bin` without starting another PowerShell, the newest release's wheel is installed on Python 3.14, `canworks-deploy --version` in a new terminal prints that release's version, and `canworks-config` opens the configurator

#### Scenario: Update with the same line
- **WHEN** a Mac user who has 0.82.0 installed pastes the documented line after 0.83.0 was released
- **THEN** 0.83.0 is installed over it, uv is not reinstalled, and the configurator's saved settings are kept

#### Scenario: Old uv
- **WHEN** the PC has uv 0.8.0 from uv's own installer
- **THEN** the script updates uv before installing, and the tools are installed on Python 3.14

#### Scenario: Given version
- **WHEN** the user runs the script with `--version 0.82.0`
- **THEN** the wheel of `deploy-v0.82.0` is installed, also when a newer release exists

#### Scenario: Uninstall
- **WHEN** the user runs the script with `--uninstall`
- **THEN** the tools' commands are no longer on PATH and uv is still installed

#### Scenario: No release reachable
- **WHEN** the script cannot reach github.com
- **THEN** it exits non-zero, names the URL it could not reach and the proxy setting the docs describe, and changes nothing that was installed

### Requirement: Skip an up-to-date install

Before installing, the one-line PC installers SHALL read the installed version of the tools and the Python of their environment from uv (`uv tool list --show-python`). When the version equals the version they would install, the environment's Python has the same major and minor version as the Python they would install with (checked only when that Python is given as a version, not as a path), and neither `--force` (`-Force`) nor `--wheel` (`-Wheel`) is given, they SHALL say that this version is already installed and how to install it again, change nothing, and exit 0. Otherwise, including when the installed version or Python cannot be read, they SHALL install as before. `--force` SHALL install even the same version again and recreate the shortcut.

#### Scenario: Line run again
- **WHEN** a user with 0.92.0 installed on Python 3.14 runs the one-line installer while 0.92.0 is the newest release
- **THEN** it prints that canworks 0.92.0 is already installed and that `--force` installs it again, exits 0 within seconds, and the tools' environment is unchanged

#### Scenario: Newer release
- **WHEN** a user with 0.92.0 installed runs the line after 0.93.0 was released
- **THEN** 0.93.0 is installed as before

#### Scenario: Same version on an older Python
- **WHEN** a user who has 0.95.0 installed on Python 3.12 runs the installer and 0.95.0 is the newest release
- **THEN** it installs 0.95.0 again on Python 3.14 and recreates the shortcut

#### Scenario: Force
- **WHEN** a user runs the installer with `-Force` and the newest version is already installed
- **THEN** it installs that version again and recreates the shortcut
