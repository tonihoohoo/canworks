## RENAMED Requirements

- FROM: `### Requirement: Tested on Windows and macOS`
- TO: `### Requirement: Tested on Windows, macOS and Linux`

## MODIFIED Requirements

### Requirement: Install on a PC without Python

The documentation SHALL give, for Windows, for macOS and for Linux, the commands that install the tools on a PC with no Python and no admin rights: install uv with its official installer, then install the release wheel with uv using a uv-managed Python. After these commands the user's shell SHALL find `openplc-canopen-config`, `openplc-canopen-deploy` and `openplc-canopen-diag`, and they SHALL behave as when installed with pip. The documentation SHALL name, per operating system, the folder uv links the commands into and the configurator's settings folder, and SHALL say that the tools reach the CAN bus only through the runtime, so a CAN adapter on the PC is used only by a runtime running on that PC.

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

### Requirement: pip route kept

Installing the tools with pip or pipx into an existing Python 3.8+ SHALL keep working and stay documented as an alternative to uv. The documentation SHALL say that Linux distributions that mark their Python as externally managed (PEP 668) refuse a plain `pip install`, and SHALL point those users at uv, pipx or a virtual environment.

#### Scenario: pipx install from a checkout
- **WHEN** a user runs `pipx install ./tools/deploy` from a checkout
- **THEN** the same three commands are installed as with uv

#### Scenario: Externally managed Python
- **WHEN** a Debian or Ubuntu user follows the pip section and their distribution refuses `python3 -m pip install` with "externally-managed-environment"
- **THEN** the same section tells them to use uv, pipx or a virtual environment instead

### Requirement: Tested on Windows, macOS and Linux

CI SHALL install the wheel with uv on a Windows runner, a macOS runner, a Linux x86_64 runner and a Linux ARM64 runner, run the tools' test suite there, and run each of the three commands at least once (deploy tool: schema/EDS check, DCF export and DBC export of a shipped example config; configurator: start and answer its page with its access token; diagnostics: `--help`). The job SHALL run on pushes to `main` that change `tools/deploy/pyproject.toml` (where a version bump is released), on release tags, and when started by hand on any branch; it SHALL NOT run on pull requests, whose Linux run covers the same code. An automatic release SHALL wait for this job's run on the released commit. The README SHALL give the commands to run the same checks on a Windows PC, a Mac or a Linux PC. A test SHALL NOT be skipped on these runners unless it needs something the job does not install (a browser for page tests, the C++ parity binary, CAN hardware), and each such skip SHALL say why.

#### Scenario: Version bump merged
- **WHEN** a pull request that raises the version in `tools/deploy/pyproject.toml` is merged to `main`
- **THEN** the Windows, macOS and both Linux jobs run on the merge commit and the release waits for them

#### Scenario: Linux job fails
- **WHEN** a version bump is merged and the installed-wheel job fails on the Linux ARM64 runner only
- **THEN** no release is created for that commit

#### Scenario: Change to the tools
- **WHEN** a pull request changes files under `tools/deploy/`
- **THEN** the installed-wheel jobs do not run unless started by hand on its branch; the Linux tests in CI still run

#### Scenario: Unrelated change
- **WHEN** a commit on `main` changes only plugin C++ code or docs
- **THEN** the installed-wheel jobs do not run
