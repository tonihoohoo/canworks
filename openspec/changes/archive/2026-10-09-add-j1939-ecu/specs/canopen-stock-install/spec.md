## ADDED Requirements

### Requirement: J1939 kernel module loaded
The install script SHALL load the `can-j1939` kernel module on the host and make it load at boot, in native and in Docker mode. When the module is not available in the running kernel, the install SHALL succeed and say that J1939 networks will not start on this device.

#### Scenario: Raspberry Pi install
- **WHEN** the script runs on a Raspberry Pi OS host
- **THEN** `lsmod` lists `can_j1939` and `/etc/modules-load.d/` holds an entry for it

#### Scenario: Kernel without J1939
- **WHEN** the script runs on a kernel without `can-j1939`
- **THEN** the install finishes, CANopen works, and the output says J1939 networks need a kernel with the can-j1939 module
