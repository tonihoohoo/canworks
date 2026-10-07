## Context

The diagnostics channel is a non-blocking TCP server in `plugin/src/diag.cpp` (poll loop on its own thread, one JSON object per line, at most 4 clients, 10 s to send the hello). The hello carries the token in the clear and the plugin compares `sha256(token)` with `token_sha256`. Clients are:

- `openplc-canopen-diag` and everything built on `diag.Client` in Python: the configurator's online, scan, LSS, parameter, OD browser, trace and simulator views (`configurator/server.py`, `simclient.py`);
- the C++ `ControlClient` in `tools/sim/control.cpp`, used by `openplc-canopen-sim test --runtime` and the `sim` subcommands against a standalone simulator;
- the standalone simulator's own control server (port 7532), which takes a plain token, not a hash, and needs one only off loopback.

The runtime runs on a Pi (stock install, or the managed Docker install) and in the local simulator runtime container on the PC. The runtime's own HTTPS certificate (port 8443) changes every time its container is recreated, so anything that pins a certificate breaks in practice.

## Goals / Non-Goals

**Goals:**
- Nobody watching or sitting in the network path learns the token or can read, inject or change requests and answers.
- No certificate management for the user: nothing to install, copy, back up or re-pin when a container is recreated.
- What is stored in `canopen.json` (which travels with the project) is not enough to log in.
- Existing projects keep working after the plugin is updated; the configurator upgrades them with one click.
- No new Python dependency on the PC (works with Python 3.8 and the uv-installed tools on Windows, macOS and Linux).

**Non-Goals:**
- User accounts or roles (one token per config, as today; read-only versus changes stays `allow_changes`).
- Protecting against someone who already has the token, or root on the PLC.
- Encrypting the runtime's own API or the editor upload; that is the runtime's business.
- Changing the default `bind` (0.0.0.0): the local simulator runtime needs it inside its container and existing Pi setups rely on it. The docs keep recommending a specific `bind` or a firewall.

## Decisions

### 1. TLS with an ephemeral self-signed certificate, authenticated by the login, not by the certificate

The plugin generates an ECDSA P-256 key and a self-signed certificate (SHA-256 signature, CN `openplc-canopen-diag`) in memory each time it opens the listener, and never writes them to disk. Clients do not validate the certificate chain. Instead, the login binds itself to the certificate the client actually saw (decision 2), so a machine in the middle with its own certificate is caught at login.

Alternatives considered:
- **TLS with a persistent certificate pinned by fingerprint** (stored in the project or trusted on first use): needs a key file that survives container recreation and a re-pin step whenever it is lost; the 8443 experience shows that this goes wrong. Rejected.
- **Challenge-response over plain TCP** (HMAC of a server nonce): hides the token but leaves every request and answer readable and changeable after login, which matters when `allow_changes` is on. Rejected as the only measure; it lives on inside TLS as decision 2.
- **TLS-PSK keyed by the token**: no certificate at all, but Python's `ssl` supports PSK only from 3.13 and the key would be a password equivalent stored in the config. Rejected.
- **SSH tunnel**: works today without code, but needs SSH access to the PLC (none inside the managed Docker install) and does not help the configurator. Documented as an extra option only.

### 2. SCRAM-SHA-256 with `tls-server-end-point` channel binding

The SCRAM math of RFC 5802/7677 with JSON framing instead of SCRAM's comma strings:

```
SaltedPassword = PBKDF2-HMAC-SHA-256(token, salt, iterations)
ClientKey = HMAC(SaltedPassword, "Client Key")   StoredKey = SHA-256(ClientKey)
ServerKey = HMAC(SaltedPassword, "Server Key")
cbind     = SHA-256(DER of the server certificate as the client received it)
AuthMessage = "openplc-canopen-diag/2," + cnonce + "," + snonce + "," + salt_b64 + "," + iterations + "," + b64(cbind)
ClientProof = ClientKey XOR HMAC(StoredKey, AuthMessage)
ServerSignature = HMAC(ServerKey, AuthMessage)
```

Exchange inside TLS:

1. Client: `{"op": "hello", "mech": "SCRAM-SHA-256-PLUS", "nonce": cnonce}` (cnonce 18 random bytes, base64).
2. Plugin: `{"ok": true, "result": {"nonce": snonce, "salt": ..., "iterations": N}}`.
3. Client: `{"op": "login", "proof": ClientProof}`.
4. Plugin checks the proof (constant time, `SHA-256(ClientProof XOR HMAC(StoredKey, AuthMessage)) == StoredKey`, with `cbind` computed from its own certificate). On success: `{"ok": true, "result": {"signature": ServerSignature, "protocol": 2, "version": ..., "allow_changes": ..., "master_node_id": ..., "networks": [...]}}`. On failure the connection closes with no answer, as a wrong token does today.
5. The client checks `signature` before it uses anything from the plugin. A wrong signature is reported as "the runtime could not prove it knows this project's token" and the connection is dropped.

A machine in the middle sees a different certificate on each side, so `cbind` differs, the plugin rejects the forwarded proof and the client rejects any signature the middle machine makes up. Only the plugin computes nothing expensive (no PBKDF2 on the Pi); the client runs PBKDF2 once per connection (4096 iterations by default, milliseconds). Python has everything in the standard library (`ssl`, `hashlib.pbkdf2_hmac`, `hmac`); the C++ side uses OpenSSL's `PKCS5_PBKDF2_HMAC` and `HMAC`.

### 3. `token_verifier` in the config, PostgreSQL format

`"token_verifier": "SCRAM-SHA-256$4096:<salt b64>$<StoredKey b64>:<ServerKey b64>"`. Iterations 4096 to 1000000, salt 16 bytes or more. Exactly one of `token_verifier` and `token_sha256` is allowed; both or neither rejects the config naming the field. The verifier lets someone who copies the project impersonate the plugin to a client but not log in to the plugin, which is the property `token_sha256` has today. A weak hand-typed token can still be guessed offline from a verifier (as from a SHA-256); the configurator's 192-bit tokens make that moot, and the docs keep saying so.

The standalone simulator gets its token on the command line, so it computes a verifier with a fresh salt at start and uses the same server code.

### 4. One port, first-byte sniff, legacy plain mode

The plugin reads the first byte of each connection: 0x16 (TLS handshake record) starts TLS; anything else is the plain protocol 1. Plain is served only when the config has `token_sha256` (legacy mode, logged as a warning at every listener start: "diagnostics: plain TCP, the token crosses the network unencrypted; upgrade the token in the configurator"). With `token_verifier`, a plain connection gets one error line, `this runtime needs an encrypted connection; update openplc-canopen-diag`, and is closed.

Legacy status is reported to clients (`"encrypted": false` in `status`), shown by `openplc-canopen-diag status` and as a warning line in the configurator's online view.

### 5. Clients against an older plugin

A new client always starts with TLS. An older plugin either answers the ClientHello with a plain JSON error line (seen by the client as a non-TLS record) or says nothing until its 10 s hello timeout. In both cases the client stops with "the runtime's plugin does not speak encrypted diagnostics (older than <version>); update it, or use --plain to send the token unencrypted". `--plain` (CLI) prints a warning and uses protocol 1. The configurator offers **Connect unencrypted** only when the project's config still has `token_sha256`; with a `token_verifier` there is nothing an old plugin could check, so it is never offered. That also stops a machine in the middle from talking an upgraded project down to plain.

### 6. Non-blocking TLS in the existing poll loop

`SSL_set_fd` on the existing non-blocking socket; reads and writes handle `SSL_ERROR_WANT_READ`/`WANT_WRITE` by adjusting the poll events. The per-client output cap that cuts off slow readers applies to plaintext queued for `SSL_write`, so a stalled client is still cut off and never waited for. The handshake counts toward the 10 s hello deadline. Trace fetches keep running on the diagnostics thread; TLS adds a few percent of CPU at 8000 frames per second on a Pi 5. Failed logins are logged as today (once a minute per address), and an address whose login failed waits 1 s before its next attempt is answered, to slow online guessing.

### 7. Build dependency

CMake `find_package(OpenSSL 3 REQUIRED COMPONENTS SSL Crypto)` for the plugin and `openplc-canopen-sim`; dynamic linking against the system libssl3. The stock install, Docker install, local runtime image and CI install `libssl-dev`. The runtime images already contain libssl3 (their Python serves HTTPS), so nothing new is needed at run time; the install script checks it anyway and says what is missing.

## Risks / Trade-offs

- [The plugin has a new security-relevant code path] → Unit tests with fixed SCRAM vectors (RFC 7677 test vector for the math), a Python-client-to-plugin integration test over vcan, and a man-in-the-middle test that proxies TLS with its own certificate and must fail on both sides.
- [Legacy plain mode keeps the old weakness alive] → Warning everywhere it applies and a one-click upgrade; dropping plain mode is a later change once Toni says so.
- [Users run `--plain` by habit] → It is never needed with an upgraded config, and the configurator never offers it then.
- [OpenSSL API differences between distributions] → Require OpenSSL 3 (Debian bookworm/trixie, Raspberry Pi OS, Ubuntu 22.04+); the install script says so on older systems.

## Migration Plan

1. Update the plugin (redeploy). Existing configs with `token_sha256` keep working in plain mode with a warning.
2. Update the PC tools. The configurator offers **Upgrade to encrypted** for a project whose token it knows; save and upload. From then on only TLS is accepted.
3. `openplc-canopen-diag hash-token` users put the new `token_verifier` in their config by hand.

Rollback: an older plugin rejects `token_verifier` as an unknown field, so going back means restoring `token_sha256` (the configurator keeps the token, so **New token** or re-entering it does that).

## Open Questions

- Should the legacy plain mode be dropped right away instead (simpler, but every existing project needs the upgrade before the next upload)? Default in this proposal: keep it, with warnings.
