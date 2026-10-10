## ADDED Requirements

### Requirement: Runtime advertisement
The install SHALL place an Avahi service file that advertises `_canworks._tcp` on the diagnostics port with TXT records `name` (the device's host name unless configured), `diag`, `runtime`, `v=1`, and `id` (the link ID) when the link is installed. `--without-discovery` SHALL skip it. The advertisement SHALL not depend on the PLC running.

#### Scenario: PLC stopped
- **WHEN** the PLC is stopped
- **THEN** the device is still advertised, and a PC that connects gets the usual "diagnostics not listening" answer

### Requirement: Discovery in the PC tools
`canworks-diag discover [--timeout S]` and the configurator's connect box SHALL browse `_canworks._tcp` with the PC tools' own mDNS client (not the operating system's name lookup) and list each runtime with its name, addresses and ports, and its link ID when advertised. Typing an address SHALL keep working.

#### Scenario: Direct Ethernet cable
- **WHEN** the PC and the device are joined by one Ethernet cable with no DHCP server and both use link-local addresses
- **THEN** `canworks-diag discover` lists the device with its 169.254.x.x address and the configurator can connect to it

#### Scenario: Nothing found
- **WHEN** no runtime answers within the timeout
- **THEN** the tools say none was found and that discovery does not cross routers, and offer to type an address
