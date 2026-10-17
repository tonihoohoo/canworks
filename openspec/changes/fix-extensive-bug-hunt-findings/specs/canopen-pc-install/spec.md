## ADDED Requirements

### Requirement: Dependency floors without known vulnerabilities
The PC tools SHALL require Python 3.10 or newer and dependency versions without known advisories in the code paths they use, including `zeroconf>=0.149.16` and, on Windows, `libusb>=1.0.30`.

#### Scenario: Fresh install
- **WHEN** the PC tools are installed into an environment with zeroconf 0.148
- **THEN** zeroconf is upgraded to a fixed version
