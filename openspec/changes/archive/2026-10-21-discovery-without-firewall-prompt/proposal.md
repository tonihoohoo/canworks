## Why

On Windows, Defender Firewall asks "Windows Defender Firewall has blocked some features of Python" while the configurator is in use. The configurator's web server is not the cause (it listens on 127.0.0.1 only). Two background features open sockets that can receive from the network:

- **Discovery.** `link/discovery.py` browses `_canworks._tcp` with python-zeroconf, whose `Zeroconf()` binds a listen socket to UDP port 5353 on every interface. It runs for the connect box's runtime list, the remote adapter list and the Devices view, which searches as soon as it opens.
- **Remote link pairing.** After a token login over the LAN, the PC pairs with (or refreshes) the runtime over iroh, which binds a UDP port on every address.

The question returns after a Python update, because Windows keeps the answer per program path and uv's managed Python lives in a folder named after its full version.

Pressing Cancel saves a block rule for that Python. Outgoing connections still work, but the zeroconf browse then finds nothing, which is also what happens on a network set to Public today.

## What Changes

- **Discovery without a listen socket.** The PC tools' multicast browse becomes a one-shot mDNS question sent from an unbound UDP socket on each local interface, using an ephemeral source port. Responders answer with legacy unicast (RFC 6762 section 6.7) straight back to that socket, the way the existing direct query (`query_host`) already works. Windows lets unicast answers to a multicast question in on every network profile, so no firewall rule is needed. As a side effect, the network list also works on a Public network.
- **BREAKING (internal):** the PC tools no longer depend on `zeroconf`. Interface addresses come from `ifaddr`, a small pure-Python package that zeroconf already pulled in. `canworks-diag discover` and the lists in the configurator no longer say "discovery needs the zeroconf package".
- **Remote link unchanged.** Pairing over iroh still binds a UDP port and may still prompt once per Python. The docs say what the prompt is and that Cancel is safe. A Windows check confirms that the LAN link and online access keep working after Cancel.
- **Docs.** The README PC tools section, `docs/install-pc.md` and `docs/remote-access.md` explain the prompt. The "Public network drops the answers" note in remote-access.md goes away.
- PC tools minor version bump (0.99.0).

## Capabilities

### New Capabilities

### Modified Capabilities
- `runtime-discovery`: browsing uses the tools' own one-shot query with unicast answers and needs no listen socket; a firewall-prompt requirement is added.
- `canopen-pc-install`: zeroconf leaves the dependency list (dependency floors, fast start).

## Impact

- `tools/deploy/canworks/link/discovery.py` (new `browse`, a multi-answer parser, `available()` always true), `configurator/online.py`, `diag.py` (`discover`), `tools/deploy/pyproject.toml` (drop zeroconf, add ifaddr), the fast-start import test, and the discovery tests (a fake responder on loopback).
- The device side is unchanged: Avahi already answers legacy unicast questions. An adapter server advertises through Avahi too.
- Docs: README.md, docs/install-pc.md, docs/remote-access.md.
- Hardware/desktop checks on the Windows PC (needs a Python path the firewall has not seen yet).
