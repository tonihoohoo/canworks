# runtime-discovery Specification

## Purpose
Finding runtimes on the local network: the device's mDNS/DNS-SD advertisement and the PC tools' discovery list.

## Requirements

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

### Requirement: Direct query to a known host
The PC tools SHALL be able to ask one host directly for `_canworks._tcp` with a legacy unicast mDNS query (RFC 6762 section 6.7) and read the runtime's name, ports and link ID from the answer, without the zeroconf package. Finding a runtime by host (`canworks-diag discover HOST`, and the remote link after a direct login) SHALL try the direct query first and browse by multicast only when it gets no answer.

#### Scenario: Windows on a Public network
- **WHEN** a Windows PC whose network profile is Public runs `canworks-diag discover line3.local` and the runtime advertises itself
- **THEN** the runtime is listed with its address, ports and remote link, although a multicast search finds nothing
