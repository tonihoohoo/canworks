## 1. Plugin: TLS and login

- [ ] 1.1 CMake: `find_package(OpenSSL 3 REQUIRED COMPONENTS SSL Crypto)` for `canopen_core` and `openplc-canopen-sim`; keep `--exclude-libs` so OpenSSL symbols stay private to the plugin
- [ ] 1.2 `plugin/src/tls.cpp`/`.h`: in-memory ECDSA P-256 key and self-signed SHA-256 certificate per listener open, server `SSL_CTX` (TLS 1.2 minimum), DER of the certificate for channel binding
- [ ] 1.3 `plugin/src/scram.cpp`/`.h`: verifier parse and build, AuthMessage, proof check in constant time, server signature; unit tests with the RFC 7677 vector for the math and our own vectors for the JSON exchange
- [ ] 1.4 Config: `token_verifier` (format, iterations 4096-1000000, salt >= 16 bytes), exactly one of `token_verifier`/`token_sha256`, errors naming the field; v1 and v2 schemas updated
- [ ] 1.5 `diag.cpp`: first-byte sniff; TLS on the non-blocking poll loop (WANT_READ/WANT_WRITE, handshake inside the 10 s hello deadline, output cap on plaintext); `hello` + `login` states; hello information moves into the login answer; protocol 2
- [ ] 1.6 Legacy mode: plain protocol 1 only with `token_sha256`, warning at listener start, `"encrypted"` in `status`; plain connection with `token_verifier` gets the "needs an encrypted connection" line and is closed
- [ ] 1.7 1 s delay before answering the next login from an address whose login failed; existing once-a-minute log kept
- [ ] 1.8 Integration test over vcan: Python client logs in, reads status, writes an SDO with `allow_changes`; wrong token closes; replayed login fails
- [ ] 1.9 Man-in-the-middle test: a TLS proxy with its own certificate between client and plugin; both sides refuse

## 2. Standalone simulator

- [ ] 2.1 `tools/sim/control.cpp` server: with a token, verifier with a fresh salt at start, same TLS and login code; plain connections refused; without a token unchanged
- [ ] 2.2 `ControlClient`: TLS and SCRAM client, server signature check; used by `sim` subcommands and `openplc-canopen-sim test --runtime`
- [ ] 2.3 Tests: remote-bind simulator with a token over TLS; `test --runtime` against a TLS plugin

## 3. PC tools

- [ ] 3.1 `diag.Client`: TLS with `ssl` (no chain check), SCRAM with `hashlib.pbkdf2_hmac`, server signature check, error kinds for "could not prove the token" and "plugin too old"; `plain=True` for protocol 1
- [ ] 3.2 CLI: `--plain` with a warning; `hash-token` prints a verifier, `hash-token --sha256` the old hash; `status` says encrypted or not
- [ ] 3.3 `simclient.py` and every configurator view built on `diag.Client` pass through the new client (online, scan, LSS, parameters, OD browser, trace, simulator)
- [ ] 3.4 `tests/fake_diag.py` and `fake_sim.py` speak TLS + SCRAM (and plain for legacy tests); existing diag and configurator tests pass unchanged above the transport
- [ ] 3.5 Bump the deploy tool's minor version (next free at apply time)

## 4. Configurator

- [ ] 4.1 Online access writes `token_verifier`; **Enter token…** checks against either form; **New token** writes a verifier
- [ ] 4.2 Old projects: "unencrypted" note and **Upgrade to encrypted** when this PC holds the token
- [ ] 4.3 Online view connection line says encrypted or not; new failure reasons; **Connect unencrypted** only for `token_sha256` projects against a plugin without TLS
- [ ] 4.4 Tests for enable, upgrade, enter token and the no-downgrade rule

## 5. Install and build

- [ ] 5.1 `install-stock.sh` installs `libssl-dev`, checks OpenSSL 3 and says what is missing on older systems
- [ ] 5.2 Docker install path and `docker/local-runtime/Dockerfile` build with OpenSSL; image still runs (`--runtime local status` encrypted)
- [ ] 5.3 CI build images install `libssl-dev`

## 6. Docs

- [ ] 6.1 `docs/diagnostics.md`: security section rewritten (encrypted, token never sent, legacy mode, SSH tunnel as an extra option); protocol section gets the TLS + login exchange and protocol 2
- [ ] 6.2 `docs/config.md` (`token_verifier`), `docs/configurator.md` (upgrade, encrypted line), `docs/simulator.md` (TLS with a token), `docs/local-runtime.md` (nothing to set up)
- [ ] 6.3 README: online diagnostics described as encrypted and token protected

## 7. Hardware (Pi via Remote Control)

- [ ] 7.1 Pi: redeploy with the existing `token_sha256` project; old and new CLI both connect, warning logged
- [ ] 7.2 Upgrade the project in the configurator, upload; online view says encrypted, SDO read and NMT work, an old CLI is refused with the update message
- [ ] 7.3 Trace at full bus load for 60 s over TLS: no lost frames, PLC scan unchanged
- [ ] 7.4 Put Toni's template project back on the Pi
