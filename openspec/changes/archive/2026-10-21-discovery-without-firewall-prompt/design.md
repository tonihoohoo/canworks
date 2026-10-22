## Context

`link/discovery.py` has two ways to find runtimes:
- `browse(timeout)`: python-zeroconf `Zeroconf()` + `ServiceBrowser`. zeroconf binds a socket to `('', 5353)` with multicast membership on every interface (`_utils/net.py`, `new_listen_socket`). On Windows, binding a receiving socket to a non-loopback address is what makes Defender Firewall prompt for the program (the base `python.exe` of uv's managed Python).
- `query_host(ip)`: a hand-built PTR question for `_canworks._tcp.local` sent by unicast to one host's port 5353 from an unbound UDP socket. The answer comes back to the ephemeral port. This one already works on a Windows Public network.

Callers of `browse`: `configurator/online.py` `runtimes_list` (connect box, Devices view "Found on this network") and `adapter_servers_list`, `diag.py` `discover`, and `link/pc.py` `find_address` as a fallback. Devices advertise through Avahi service files (runtime: install-link.sh / install-stock.sh; adapter server: `localbus/serve.py` writes one). Nothing on the PC side advertises with zeroconf.

## Goals / Non-Goals

**Goals:**
- No firewall question from discovery on Windows, on any network profile.
- Same results as today: runtimes and adapter servers, with name, addresses, ports, link ID and kind.
- Fewer dependencies (zeroconf goes), and no slower start.

**Non-Goals:**
- Avoiding the iroh bind. The remote link needs a UDP socket of its own, and pairing stays automatic after a LAN login. This change only documents the prompt and checks that Cancel is harmless.
- Adding firewall rules from the installer (needs admin, and the Python path changes with every patch release).
- Discovery across routers (unchanged).

## Decisions

**1. A one-shot legacy-unicast question instead of a browser.**
`browse(timeout)` does the following:
- Lists the local interface addresses with `ifaddr`: IPv4 addresses that are not loopback (169.254.x.x is included, for a direct cable), and IPv6 link-local addresses with their scope id.
- Opens one UDP socket per interface without calling `bind()`. It sets `IP_MULTICAST_IF` (or `IPV6_MULTICAST_IF`) and TTL 255. Multicast loop stays on, so a service advertised on this PC itself is listed, as it was with zeroconf.
- Sends the PTR question with the QU bit set to `224.0.0.251:5353` (or `ff02::fb`). It repeats the send once after 1 s, because UDP can drop a packet.
- Reads answers on all the sockets with `select` until the timeout.

The source port is not 5353, so RFC 6762 section 6.7 makes responders send their answer by unicast to that port, with the question echoed and the TTLs capped. Avahi does this. Windows Defender Firewall's default "allow unicast response to multicast" (on in every profile) lets such answers in for 3 s after the question. The sockets never listen on a fixed port and are never bound explicitly.

Alternatives considered:
- Keep zeroconf with `unicast=True`. It still binds a respond socket to each interface address explicitly, and it brings an asyncio engine for a 2 s question.
- Keep zeroconf and only document the prompt. Cancel would then leave every network list empty, which is the case to fix.
- Search only on request (a button). This keeps the prompt and only moves it. It stays as the fallback (see Risks).

**2. A parser that reads many instances per packet.**
`parse_answer` today returns one instance. A host with a runtime and an adapter server, or an Avahi answer that bundles several PTRs, carries several instances in one packet. A new `parse_answers(data)` returns `{instance: {port, txt, target}}` and the A/AAAA records it finds. `query_host` uses the same parser and takes its first instance. When an answer names an instance by PTR only, `browse` asks that host directly (`query_host`) for the rest.

**3. Addresses come from the answer's source.**
Each instance's `addresses` is the source address of the packet that carried its SRV record, followed by the A/AAAA records for the SRV target found in that packet. Instances are merged by name, and later packets add addresses. Taking the source address first keeps a host from listing a runtime at somebody else's address. This is the same rule `query_host` already applies ("only an answer from the asked host counts").

**4. Dependencies.**
zeroconf is removed from `pyproject.toml`. `ifaddr>=0.2` is added: a pure-Python package with no compiled parts, which zeroconf already pulled in, so the installed size goes down. `discovery.available()` stays, returns True, and is kept for callers. `NOT_AVAILABLE` and the "needs zeroconf" paths go. The fast-start test keeps asserting that `ifaddr` is not imported at start: it is imported inside `browse`.

## Risks / Trade-offs

- **[Windows might still prompt for an implicitly bound UDP socket]** → Task 1.1 checks this on the Windows PC first, with a throwaway script and a Python path the firewall has not seen yet, before any code is written. If it still prompts, we stop and switch to the fallback: discovery runs only when the user presses Find (connect box, Devices view), with a docs note, and the proposal is updated before applying.
- **[A responder that ignores legacy unicast]** → Avahi and python-zeroconf (both checked in the source) answer by unicast. We advertise only through Avahi. Other mDNS stacks may differ, but only our own service type is asked for.
- **[Several network adapters on Windows (VPN, WSL vEthernet, Docker)]** → The question goes out on every interface separately, so a runtime on the second NIC or on a direct cable is still found. Sending on a virtual adapter costs one datagram.
- **[IPv6-only links]** → Covered by ff02::fb on link-local addresses. If that fails on some systems, IPv4 still covers the bench and the direct cable.

## Migration Plan

Nothing to migrate: the change is in the PC tools only. Devices keep their Avahi files. A rule a user already allowed or blocked for an older Python stays in Windows and is harmless.
