## MODIFIED Requirements

### Requirement: Install on a PC without Python

The documentation SHALL give, for Windows, for macOS and for Linux, the commands that install the tools on a PC with no Python and no admin rights: install uv with its official installer, then install the release wheel with uv using a uv-managed Python. After these commands the user's shell SHALL find `openplc-canopen-config`, `openplc-canopen-deploy` and `openplc-canopen-diag`, and they SHALL behave as when installed with pip. The documentation SHALL name, per operating system, the folder uv links the commands into and the configurator's settings folder. It SHALL say that the tools reach the CAN bus through a runtime, or directly through a USB CAN adapter on the PC (canopen-local-bus), and SHALL give per operating system what an slcan adapter needs: no driver on Windows 10 and 11, macOS and Linux, and the port name pattern on each, plus on Linux the `dialout` group for serial ports.

#### Scenario: Fresh Windows PC
- **WHEN** a Windows user with no Python installed runs the documented uv install command and then the documented `uv tool install` command on the downloaded wheel, and opens a new terminal
- **THEN** `openplc-canopen-deploy --version` prints the wheel's version and `openplc-canopen-config` opens the configurator in the browser

#### Scenario: Fresh Mac
- **WHEN** a macOS user with no Python installed runs the documented commands
- **THEN** the three commands are on PATH and `openplc-canopen-deploy --version` prints the wheel's version

#### Scenario: Fresh Linux desktop
- **WHEN** a Linux user (x86_64 or ARM64, glibc) runs the documented uv install command and the documented `uv tool install` command, and opens a new terminal
- **THEN** the three commands are in `~/.local/bin` and on PATH, `openplc-canopen-deploy --version` prints the wheel's version, and `openplc-canopen-config` opens the configurator in the default browser

#### Scenario: Linux without a browser
- **WHEN** `openplc-canopen-config` starts on a Linux machine with no browser to open (for example over SSH)
- **THEN** it still serves the page and prints its URL with the access token, and `--no-browser` skips the attempt

#### Scenario: Editor CLI on Linux
- **WHEN** the OpenPLC Editor AppImage has run `openplc-cli install-cli` and the user runs the deploy tool's Build only or New editor project
- **THEN** the tools find `openplc-cli` on PATH and run it

#### Scenario: Corporate proxy
- **WHEN** the PC reaches the internet through a TLS-inspecting proxy
- **THEN** the documentation names the uv option that makes uv trust the operating system's certificate store

#### Scenario: USB adapter after install
- **WHEN** a user installed the tools with uv on Windows, macOS or Linux and plugs in a CANable with stock firmware
- **THEN** `openplc-canopen-diag adapters` lists it without any further install step (on Linux, after joining `dialout` when the docs say so)

## ADDED Requirements

### Requirement: Adapter libraries in the package
The tools package SHALL depend on python-can and pyserial, and every dependency SHALL install with uv from wheels or pure Python sources on Windows, macOS (Intel and Apple silicon) and Linux (x86_64 and ARM64) without a compiler. The PC tools CI job SHALL run the local backend's virtual-bus tests on each of its runners.

#### Scenario: Fresh install on each runner
- **WHEN** the PC tools job installs the wheel with uv on its four runners
- **THEN** the install needs no compiler and the local backend's virtual-bus tests pass on each
