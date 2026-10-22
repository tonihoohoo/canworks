## MODIFIED Requirements

### Requirement: Dependency floors without known vulnerabilities
The PC tools SHALL require Python 3.11 or newer and dependency versions without known advisories in the code paths they use, including, on Windows, `libusb>=1.0.30`. The PC tools SHALL NOT depend on `zeroconf`. The Python floor SHALL NOT be higher than the Python of the pinned runtime image, because the same package runs there.

#### Scenario: Fresh install
- **WHEN** the PC tools are installed into a new environment
- **THEN** `zeroconf` is not installed, and `ifaddr` is

#### Scenario: Run from a checkout on Windows
- **WHEN** a Windows user runs `uv run` on the deploy tool from a source checkout
- **THEN** uv resolves the dependencies, including `libusb`, without a Python version error

#### Scenario: Python 3.10
- **WHEN** a user installs the tools with pip on Python 3.10
- **THEN** pip refuses, saying the package needs Python 3.11 or newer

### Requirement: Fast start

The configurator and the deploy tool SHALL start without importing the libraries that only some of their work needs: `jsonschema` until a config, simulation file, machine file or notes file is validated, and `python-can`, `cantools`, `can-j1939`, `ifaddr` and `iroh` until an adapter, DBC, J1939, discovery or remote-link feature is used. A unit test in CI SHALL import the entry modules of `canworks-config`, `canworks-deploy` and `canworks-diag` in a fresh interpreter and fail when any of these libraries was imported.

#### Scenario: Configurator start
- **WHEN** a fresh Python process imports `canworks.configurator.server`
- **THEN** none of `jsonschema`, `can`, `cantools`, `j1939`, `ifaddr` or `iroh` is in `sys.modules`

#### Scenario: Validation still works
- **WHEN** the configurator then opens a project and checks its `canworks.json`
- **THEN** the config is validated against its schema exactly as before, with the same messages
