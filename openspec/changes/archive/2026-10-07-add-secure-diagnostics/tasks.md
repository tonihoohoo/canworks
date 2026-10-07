## 1. Plugin: TLS and login

- [x] 1.1 CMake: `find_package(OpenSSL 3 REQUIRED COMPONENTS SSL Crypto)` for `canopen_core` and `openplc-canopen-sim`; keep `--exclude-libs` so OpenSSL symbols stay private to the plugin
- [x] 1.2 `plugin/src/secure_channel.cpp`/`.h` (TLS): in-memory ECDSA P-256 key and self-signed SHA-256 certificate per listener open, server `SSL_CTX` (TLS 1.2 minimum), DER of the certificate for channel binding
- [x] 1.3 `plugin/src/secure_channel.cpp`/`.h` (SCRAM): verifier parse and build, AuthMessage, proof check in constant time, server signature; unit tests with the RFC 7677 vector for the math and our own vectors for the JSON exchange
- [x] 1.4 Config: `token_verifier` required (format, iterations 4096-1000000, salt >= 16 bytes); `token_sha256` rejected with the set-the-token-again message; schema updated
- [x] 1.5 `diag.cpp`: first-byte sniff; TLS over memory BIOs on the non-blocking poll loop (handshake inside the 10 s hello deadline, output cap on plaintext plus unsent bytes); `hello` + `login` states; hello information moves into the login answer; protocol 2
- [x] 1.6 A plain connection gets the "needs an encrypted connection" line and is closed; a client over the limit is told "too many clients" in its own mode
- [x] 1.7 1 s delay before answering the next login from an address whose login failed; existing once-a-minute log kept
- [x] 1.8 Unit tests against the real server: login, wrong token, back-off, replayed login, a client bound to another certificate (man in the middle), plain client refused; existing diag tests log in over TLS
- [x] 1.9 Integration tests (trace, parameters, local runtime) use `token_verifier`, so the Python client runs against the plugin over TLS

## 2. Standalone simulator

- [x] 2.1 `tools/sim/control.cpp` server: with a token, verifier with a fresh salt at start, same TLS and login code; plain connections refused; without a token unchanged
- [x] 2.2 `ControlClient`: TLS and SCRAM client, server signature check; used by `sim` subcommands and `openplc-canopen-sim test --runtime`
- [x] 2.3 Tests: the control server and client with a token over TLS (login, wrong token, plain client refused) and without one; `test --runtime` against a TLS plugin

## 3. PC tools

- [x] 3.1 `diag.Client`: TLS with `ssl` (no chain check), SCRAM with `hashlib.pbkdf2_hmac`, server signature check, error kinds for "could not prove the token" and "plugin too old"; plain only towards a standalone simulator without a token
- [x] 3.2 CLI: `hash-token` prints a verifier; the deploy tool's config check rejects `token_sha256` with the same message as the plugin
- [x] 3.3 `simclient.py` and every configurator view built on `diag.Client` pass through the new client (online, scan, LSS, parameters, OD browser, trace, simulator)
- [x] 3.4 `tests/fake_diag.py` and `fake_sim.py` speak TLS + SCRAM (test certificate in `tests/data`); existing diag and configurator tests pass unchanged above the transport
- [x] 3.5 Deploy tool version 0.33.0

## 4. Configurator

- [x] 4.1 Online access writes `token_verifier`; **Enter token…** checks against it; **New token** writes a verifier
- [x] 4.2 Old projects: "set the token again" note and **Upgrade** when this PC holds the token
- [x] 4.3 Online view: new failure reasons (runtime could not prove the token, plugin too old)
- [x] 4.4 Tests for enable, upgrade and enter token

## 5. Install and build

- [x] 5.1 `install-stock.sh` installs `libssl-dev`, checks OpenSSL 3 and says what is missing on older systems
- [x] 5.2 Docker install path and `docker/local-runtime/Dockerfile` build with OpenSSL; image still runs (`--runtime local status` encrypted)
- [x] 5.3 CI build images install `libssl-dev`

## 6. Docs

- [x] 6.1 `docs/diagnostics.md`: security section rewritten (encrypted, token never sent, upgrade of old configs); protocol section gets the TLS + login exchange and protocol 2
- [x] 6.2 `docs/config.md` (`token_verifier`), `docs/configurator.md` (upgrade), `docs/simulator.md` (TLS with a token), `docs/local-runtime.md` (nothing to set up)
- [x] 6.3 README: online diagnostics described as encrypted and token protected

## 7. Hardware (Pi via Remote Control)

- [x] 7.1 Pi: install the updated plugin; the template project with `token_sha256` is rejected with the set-the-token-again message (passed 2026-10-07: the deploy tool refuses it before upload with the plugin's message)
- [x] 7.2 Upgrade the project's token, upload; online view connects, SDO read and NMT work, an old CLI is refused with the update message (passed 2026-10-07 on a copy with a new token: status, SDO read 0x1018:1, NMT reset; 0.32.0 CLI and a wrong token refused)
- [x] 7.3 Trace at full bus load for 60 s over TLS: no lost frames, PLC scan unchanged (passed 2026-10-07: about 7900 frames/s seen by the plugin, 0 lost, scan avg 1-2 us and max 6 us as before)
- [x] 7.4 Put Toni's template project back on the Pi (main plugin reinstalled, original project redeployed, node 23 operational)
