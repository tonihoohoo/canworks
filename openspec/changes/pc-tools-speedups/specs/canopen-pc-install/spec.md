## MODIFIED Requirements

### Requirement: Install on a PC without Python

The documentation SHALL give, for Windows, for macOS and for Linux, the commands that install the tools on a PC with no Python and no admin rights: install uv with its official installer, then install the release wheel with uv using a uv-managed Python. Every documented `uv tool install` command SHALL compile the package's bytecode at install time (`--compile-bytecode`), so the first start after an install is as fast as later ones. After these commands the user's shell SHALL find `canworks-config`, `canworks-deploy` and `canworks-diag`, and they SHALL behave as when installed with pip. The documentation SHALL name, per operating system, the folder uv links the commands into and the configurator's settings folder. It SHALL say that the tools reach the CAN bus through a runtime, or directly through a USB CAN adapter on the PC (canopen-local-bus), and SHALL give per operating system what an slcan adapter needs: no driver on Windows 10 and 11, macOS and Linux, and the port name pattern on each, plus on Linux the `dialout` group for serial ports.

#### Scenario: Fresh Windows PC
- **WHEN** a Windows user with no Python installed runs the documented uv install command and then the documented `uv tool install` command on the downloaded wheel, and opens a new terminal
- **THEN** `canworks-deploy --version` prints the wheel's version and `canworks-config` opens the configurator in the browser

#### Scenario: Fresh Mac
- **WHEN** a macOS user with no Python installed runs the documented commands
- **THEN** the three commands are on PATH and `canworks-deploy --version` prints the wheel's version

#### Scenario: Fresh Linux desktop
- **WHEN** a Linux user (x86_64 or ARM64, glibc) runs the documented uv install command and the documented `uv tool install` command, and opens a new terminal
- **THEN** the three commands are in `~/.local/bin` and on PATH, `canworks-deploy --version` prints the wheel's version, and `canworks-config` opens the configurator in the default browser

#### Scenario: First start after install
- **WHEN** a user installs the wheel with the documented command and runs `canworks-config --version` for the first time
- **THEN** no module of the package is compiled at that start, because its bytecode was written at install

#### Scenario: Linux without a browser
- **WHEN** `canworks-config` starts on a Linux machine with no browser to open (for example over SSH)
- **THEN** it still serves the page and prints its URL with the access token, and `--no-browser` skips the attempt

#### Scenario: Editor CLI on Linux
- **WHEN** the OpenPLC Editor AppImage has run `openplc-cli install-cli` and the user runs the deploy tool's Build only or New editor project
- **THEN** the tools find `openplc-cli` on PATH and run it

#### Scenario: Corporate proxy
- **WHEN** the PC reaches the internet through a TLS-inspecting proxy
- **THEN** the documentation names the uv option that makes uv trust the operating system's certificate store

#### Scenario: USB adapter after install
- **WHEN** a user installed the tools with uv on Windows, macOS or Linux and plugs in a CANable with stock firmware
- **THEN** `canworks-diag adapters` lists it without any further install step (on Linux, after joining `dialout` when the docs say so)

### Requirement: Update and uninstall

The documentation SHALL give one command to replace an installed version with a newer wheel and one command to remove the tools, both working without Python on the PC. The update command SHALL compile bytecode at install time like the install command.

#### Scenario: Update
- **WHEN** the user runs the documented update command on a newer wheel
- **THEN** `canworks-deploy --version` prints the newer version and the configurator's saved settings are kept

#### Scenario: Uninstall
- **WHEN** the user runs the documented uninstall command
- **THEN** the three commands are no longer on PATH

## ADDED Requirements

### Requirement: Fast start

The configurator and the deploy tool SHALL start without importing the libraries that only some of their work needs: `jsonschema` until a config, simulation file, machine file or notes file is validated, and `python-can`, `cantools`, `can-j1939`, `zeroconf` and `iroh` until an adapter, DBC, J1939, discovery or remote-link feature is used. A unit test in CI SHALL import the entry modules of `canworks-config`, `canworks-deploy` and `canworks-diag` in a fresh interpreter and fail when any of these libraries was imported.

#### Scenario: Configurator start
- **WHEN** a fresh Python process imports `canworks.configurator.server`
- **THEN** none of `jsonschema`, `can`, `cantools`, `j1939`, `zeroconf` or `iroh` is in `sys.modules`

#### Scenario: Validation still works
- **WHEN** the configurator then opens a project and checks its `canworks.json`
- **THEN** the config is validated against its schema exactly as before, with the same messages
