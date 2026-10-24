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
`canworks-diag discover [--timeout S]` and the configurator's connect box SHALL browse `_canworks._tcp` with the PC tools' own mDNS client (not the operating system's name lookup) and list each runtime with its name, addresses and ports, and its link ID when advertised. Typing an address SHALL keep working. The browse SHALL be a one-shot question sent to the mDNS multicast group on each local interface from a socket that is not bound to a port (an ephemeral source port), so that responders answer by legacy unicast (RFC 6762 section 6.7) to that socket. It SHALL NOT bind a socket to port 5353 or listen on any port. A service's first address SHALL be the source address of its answer. An answer that names a service without its SRV record SHALL be completed by asking that host directly.

#### Scenario: Direct Ethernet cable
- **WHEN** the PC and the device are joined by one Ethernet cable with no DHCP server and both use link-local addresses
- **THEN** `canworks-diag discover` lists the device with its 169.254.x.x address and the configurator can connect to it

#### Scenario: Nothing found
- **WHEN** no runtime answers within the timeout
- **THEN** the tools say none was found and that discovery does not cross routers, and offer to type an address

#### Scenario: Windows on a Public network
- **WHEN** a Windows PC whose network profile is Public opens the configurator's connect box and a runtime on the same network advertises itself
- **THEN** the runtime is listed with its address, ports and link ID

#### Scenario: Two services on one host
- **WHEN** one machine advertises a runtime and an adapter server, and its answer carries both
- **THEN** the runtime appears in the runtime list and the adapter server in the adapter server list, both at that machine's address

### Requirement: Direct query to a known host
The PC tools SHALL be able to ask one host directly for `_canworks._tcp` with a legacy unicast mDNS query (RFC 6762 section 6.7) and read the runtime's name, ports and link ID from the answer, without the zeroconf package. Finding a runtime by host (`canworks-diag discover HOST`, and the remote link after a direct login) SHALL try the direct query first and browse by multicast only when it gets no answer.

#### Scenario: Windows on a Public network
- **WHEN** a Windows PC whose network profile is Public runs `canworks-diag discover line3.local` and the runtime advertises itself
- **THEN** the runtime is listed with its address, ports and remote link, although a multicast search finds nothing

### Requirement: No firewall question from discovery
Discovery in the PC tools (the connect box, the adapter server list, the Devices view and `canworks-diag discover`) SHALL NOT make Windows Defender Firewall ask to allow the PC tools' Python. The documentation of the PC tools SHALL explain that pairing for the remote link may still ask once for each Python the tools run on, and that Cancel leaves the configurator, online access and the remote link working.

#### Scenario: First discovery with a new Python
- **WHEN** the PC tools run on a Python that Windows Firewall has no rule for, and the user opens the Devices view and the connect box's runtime list
- **THEN** no firewall question appears, and runtimes on the local network are listed

#### Scenario: Cancel on the link question
- **WHEN** the user presses Cancel on the firewall question that appears while the PC pairs with a runtime
- **THEN** online access to that runtime works, and the remote link over the local network connects

### Requirement: Advertised port from the config
The local-network advertisement SHALL carry the config's `diagnostics.port` when `install-link.sh` is not given `--diag-port`.

#### Scenario: Port 7541
- **WHEN** discovery is installed for a config with `diagnostics.port` 7541
- **THEN** the advertisement says port 7541 and a PC lists the device with 7541
