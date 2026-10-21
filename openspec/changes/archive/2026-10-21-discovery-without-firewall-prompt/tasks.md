## 1. Check on Windows first

- [ ] 1.1 On the Windows PC, with a Python path the firewall has no rule for yet (for example a new `uv python install` patch version, or a copied interpreter folder), run a throwaway script that sends a QU PTR question for `_canworks._tcp.local` to 224.0.0.251:5353 from an unbound UDP socket per interface (`IP_MULTICAST_IF`) and prints the answers. Record: whether a firewall question appears (screenshot or "none"), whether the Pi answers, and the network profile (Private/Public). Try both profiles if possible. If a question appears, stop and update this proposal to the fallback in design.md (discovery on request).
- [ ] 1.2 With the same new Python, run `Zeroconf()` alone and confirm that it does make the question appear (baseline).

## 2. Discovery

- [x] 2.1 `link/discovery.py`: `parse_answers(data)` (several instances, SRV/TXT/PTR plus A/AAAA records). `query_host` uses it.
- [x] 2.2 `link/discovery.py`: new `browse(timeout)`. It lists interfaces with ifaddr (lazy import), opens one unbound socket per interface (IPv4 `IP_MULTICAST_IF`, IPv6 link-local `IPV6_MULTICAST_IF`), sends a QU PTR question twice (at 0 s and 1 s), and reads with `select` until the timeout. Addresses come from the answer source first, and a PTR-only answer is completed with a direct query. The entry shape is the same as today.
- [x] 2.3 Remove zeroconf. `available()` returns True, `NOT_AVAILABLE` and the "needs zeroconf" paths in `diag.py` and `configurator/online.py` go, and the module docstring is updated.
- [x] 2.4 `tools/deploy/pyproject.toml`: drop `zeroconf`, add `ifaddr>=0.2`, version 0.99.0. CI installs ifaddr instead of zeroconf (ci.yml, pc-tools.yml).

## 3. Tests

- [x] 3.1 Unit tests for `parse_answers`: one packet with a runtime plus an adapter server, a compressed-name Avahi answer, and a malformed packet.
- [x] 3.2 `browse` test against a fake legacy-unicast responder. Patch the multicast group/port to a loopback port, and assert that the answer source becomes the first address, that the entry shape is unchanged, and that no socket was bound to port 5353 (or bound explicitly at all).
- [x] 3.3 The fast-start import test asserts `ifaddr` instead of `zeroconf`. Adjust the existing discovery, connect box and Devices tests that mock `browse`.

## 4. Docs

- [x] 4.1 README.md, PC tools section: one line saying discovery needs no firewall rule, and that pairing for the remote link may ask once per Python, where Cancel is fine.
- [x] 4.2 docs/install-pc.md (Windows): explain the firewall question, why it can come back after a Python update, and what Cancel and Allow mean.
- [x] 4.3 docs/remote-access.md: replace the "Windows drops the answers on Public" paragraph.

## 5. Windows and hardware checks (after release)

- [ ] 5.1 Windows PC, new Python path, Toni's own PowerShell install: open the Devices view and the connect box. No firewall question appears, and the Pi is listed (Private profile, and Public if it can be switched).
- [ ] 5.2 Windows: connect to the Pi with the token (pairing). Note whether the firewall question appears, press Cancel, then confirm that online access works and that `canworks-diag --runtime link:<name> status` connects over the LAN.
- [ ] 5.3 Mac: the connect box lists the Pi, and `canworks-diag discover` lists it with its link ID.
- [ ] 5.4 Linux (container or Pi side, no PLC changes): `canworks-diag discover` finds an adapter server advertised through Avahi.
