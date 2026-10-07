## Why

The diagnostics channel (port 7531) is plain TCP and the first line a client sends is `{"op": "hello", "token": "..."}`. Anyone who can watch the network between the engineering PC and the PLC reads the token, and anyone who can sit in the path can also change requests after the hello. With `allow_changes` on, that token writes any object of any node, stops and resets nodes, changes node IDs and bit rates over LSS and drives the simulator. `docs/diagnostics.md` says to use it only on a trusted network, but the repo is public now and users run the configurator across plant networks. This is the largest security gap left in the project.

## What Changes

- The diagnostics channel is encrypted with TLS (1.2 or newer, 1.3 preferred). The plugin makes a fresh self-signed key and certificate in memory each time it opens the listener, so there is no certificate file to install, copy, back up or pin.
- The token never crosses the wire. Login is SCRAM-SHA-256 with channel binding to the server's certificate (`tls-server-end-point`, RFC 5929): the client proves it knows the token and the plugin proves it knows the token's verifier, both bound to this TLS connection. A machine in the middle cannot finish either side, and a captured exchange cannot be replayed.
- Config: new `token_verifier` in `master.diagnostics` (and the top-level `diagnostics` of a version 2 file), in the familiar `SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>` form, replaces `token_sha256`. The verifier is not a password equivalent: knowing it does not let anyone log in.
- No plain mode (Toni, 2026-10-07): the plugin accepts only TLS connections with the SCRAM login. A config that still has `token_sha256` is rejected with a message saying to set the token again; a plain connection (an older client) gets one line, "this runtime needs an encrypted connection; update openplc-canopen-diag", and is closed.
- `openplc-canopen-diag` connects only with TLS. Against an older plugin it stops saying the runtime's plugin must be updated. `hash-token` prints a `token_verifier`.
- Configurator: turning on Online access writes `token_verifier`. A project that still has `token_sha256` says the token must be set again; when this PC knows the token, **Upgrade** rewrites it for the same token, so copied tokens keep working.
- Standalone simulator (`openplc-canopen-sim`, port 7532): with a token its control channel uses the same TLS and SCRAM login; without a token it stays plain and loopback-only as today. `openplc-canopen-sim test --runtime` uses TLS like the diag CLI.
- Build: the plugin and `openplc-canopen-sim` link OpenSSL (libssl 3). `install-stock.sh`, the Docker install and the local simulator runtime image install `libssl-dev` for the build; the runtime images already ship libssl for their own HTTPS.
- Protocol version 2 in the hello answer. Requests and answers after login are unchanged, so every existing op and every op the planned PC-direct backend and raw-frame changes add work over the new transport without changes of their own.
- Docs: `docs/diagnostics.md` (security section rewritten, protocol section gets the login exchange), `docs/config.md`, `docs/configurator.md`, `docs/simulator.md`, `docs/local-runtime.md`; README says the channel is encrypted.

## Capabilities

### New Capabilities

### Modified Capabilities
- `canopen-online-diagnostics`: `token_verifier` replaces `token_sha256`; access control becomes TLS plus SCRAM login; plain connections refused; client behaviour against old plugins.
- `canopen-configurator`: Online access writes `token_verifier` and offers the upgrade for old projects.
- `canopen-simulated-bus`: the standalone control channel uses TLS and SCRAM when it has a token.

## Impact

- Plugin: `plugin/src/diag.cpp`, `diag.h` (TLS on the non-blocking poll loop, SCRAM state per client, first-byte sniff), `config.cpp` (new field), new `plugin/src/tls.cpp`/`scram.cpp`; CMake finds OpenSSL.
- Simulator: `tools/sim/control.cpp` (server and client).
- PC tools: `tools/deploy/openplc_canopen_deploy/diag.py` (Python `ssl` and `hashlib.pbkdf2_hmac`, no new dependency), `simclient.py`, configurator `server.py` and online page.
- Schema `canopen.v1.schema.json` (shared by version 2): `token_verifier` replaces `token_sha256`.
- Scripts: `install-stock.sh`, `docker/local-runtime/Dockerfile`, CI build images.
- Deploy tool version 0.33.0 (the 2026-10-07 apply chain). **Breaking:** a deployed config with `token_sha256` stops the CANopen start with a config error after the plugin update until the token is set again; older PC tools cannot connect to an updated plugin.
- Overlaps: the planned "PC-direct commissioning" change reuses the diag protocol as its interface but talks to a local bus, so it needs no transport; the "raw frames and bit rate detection" change only adds ops. Whichever lands later rebases on `diag.py` and `diag.cpp`; no behaviour conflicts.
