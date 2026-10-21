## ADDED Requirements

### Requirement: Device install tests in existing jobs
CI SHALL test the Devices workspace without a real device and without network access, inside the existing tools test job (no new job, CI time kept): the action plan from probe fixtures, the SSH layer and the install job against a local SSH server in the test process (host key trust and change, key and password login, key setup, sudo password on standard input, job start, log follow from an offset, reconnect, stop), password-free settings and logs, the probe script on fake roots, the scripts' step lines and `VERSION` files with the existing script tests, and the Devices page with the page tests (rows per target, main action, confirmation texts, job progress, entry points). The tests SHALL run only when files of these areas change, as the protocol-area selection does.

#### Scenario: Probe fixture for a moved runtime
- **WHEN** the plan is given a probe with runtime v4.2.5 and a plugin built for v4.2.4
- **THEN** the test expects the main action **Rebuild for runtime v4.2.5**
