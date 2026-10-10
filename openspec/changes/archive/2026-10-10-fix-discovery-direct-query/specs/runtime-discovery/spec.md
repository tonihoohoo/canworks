## ADDED Requirements

### Requirement: Direct query to a known host
The PC tools SHALL be able to ask one host directly for `_canworks._tcp` with a legacy unicast mDNS query (RFC 6762 section 6.7) and read the runtime's name, ports and link ID from the answer, without the zeroconf package. Finding a runtime by host (`canworks-diag discover HOST`, and the remote link after a direct login) SHALL try the direct query first and browse by multicast only when it gets no answer.

#### Scenario: Windows on a Public network
- **WHEN** a Windows PC whose network profile is Public runs `canworks-diag discover line3.local` and the runtime advertises itself
- **THEN** the runtime is listed with its address, ports and remote link, although a multicast search finds nothing
