## Why

The hardware test of `add-remote-access` (2026-10-10) found that a Windows PC on a network set to Public never sees the runtimes' mDNS answers: Windows' firewall drops answers to a multicast search. The runtime was advertised correctly (a direct query to it answered with its link ID), but the PC tools only browse by multicast. So on such a PC the configurator's list stays empty, and after connecting to a typed address the tools never learn the runtime's link ID, so the remote link never pairs.

## What Changes

- The PC tools ask a known host directly for `_canworks._tcp` (a legacy unicast mDNS query, RFC 6762 section 6.7, from an ordinary UDP socket to port 5353). The answer comes back to that socket, which firewalls let through. Browsing by multicast stays as the fallback, and works with or without zeroconf for the direct query.
- After a direct login, finding the runtime's link ID uses the direct query first, so automatic pairing works on Windows Public networks too.
- `canworks-diag discover HOST` asks one host directly.
- Docs: `docs/remote-access.md` says why the list can be empty on Windows and what works there.

## Capabilities

### Modified Capabilities
- `runtime-discovery`: a direct query to a known host.

## Impact

- `tools/deploy/canworks/link/discovery.py` (query and a small DNS answer parser), `link/pc.py`, `diag.py`.
- Tests: the answer parser; the direct query was run against the Pi.
