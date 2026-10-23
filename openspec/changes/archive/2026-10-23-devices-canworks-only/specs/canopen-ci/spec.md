## MODIFIED Requirements

### Requirement: Device install tests in existing jobs
CI SHALL test the Devices workspace without a real device and without network access, inside the existing tools test job (no new job, CI time kept): the action plan from probe fixtures, the SSH layer and the install job against a local SSH server in the test process (host key trust and change, key and password login, key setup, sudo password on standard input, job start, log follow from an offset, reconnect, stop), password-free settings and logs, the probe script on fake roots, the script's step lines and `VERSION` files with the existing script tests, and the Devices page with the page tests (rows per target, main action, confirmation texts, job progress, entry points, the device list's summary line). The tests SHALL run only when files of these areas change, as the protocol-area selection does.

#### Scenario: Probe fixture with backup folders
- **WHEN** the probe runs on a fake root with the instances `line1` and `line1.bak-271`
- **THEN** the test expects one instance, `line1`, and the plan's bridge row and summary line name only `line1`

#### Scenario: Probe fixture for a moved runtime
- **WHEN** the plan is given a stored probe of the old shape (managed Docker runtime v4.3.2 under `runtime`) with an OpenPLC project open and its bridge current and running
- **THEN** the test expects "Up to date", no runtime row and no **Switch runtime** action

#### Scenario: No runtime actions
- **WHEN** the plan is given any probe fixture and target
- **THEN** no main action is `install_openplc_bridge` or `switch_runtime`, and no row is the OpenPLC runtime
