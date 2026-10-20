## ADDED Requirements

### Requirement: Only runtime dependencies in the one-line install
The one-line installers SHALL NOT install test tools into the tools' environment. When a runtime dependency lists a test tool as a requirement that its code does not import (`can-j1939` lists `pytest`), the installers SHALL drop it with a uv override, and the tools that use that dependency SHALL be tested without the dropped requirement. `iroh` SHALL stay a runtime dependency on the platforms it publishes wheels for, because the remote link of the configurator and `canworks-diag` needs it. `docs/install-pc.md` SHALL say which dependencies a `pip` install gets in addition and why.

#### Scenario: No pytest after the one-line install
- **WHEN** the user installs the tools with the one-line installer
- **THEN** the tools' environment has no `pytest`, `canworks-j1939-sim` starts, and the remote link works where `iroh` has a wheel

### Requirement: Installer output over a non-login shell
When uv's bin folder is not on PATH, the one-line installers SHALL print only their own hint (open a new terminal, or the folder to add to PATH), not uv's PATH warning as well.

#### Scenario: Install over SSH
- **WHEN** the user runs the one-line Linux installer through a non-login SSH command, with uv's bin folder not on PATH
- **THEN** the output has the installer's hint to open a new terminal once, and no "is not on your PATH" warning from uv
