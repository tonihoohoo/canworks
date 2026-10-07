## Why

The diagnostics channel (port 7531) is plain TCP and the first line a client sends is `{"op": "hello", "token": "..."}`. Anyone who can watch the network between the engineering PC and the PLC reads the token, and anyone who can sit in the path can also change requests after the hello. With `allow_changes` on, that token writes any object of any node, stops and resets nodes, changes node IDs and bit rates over LSS and drives the simulator. `docs/diagnostics.md` says to use it only on a trusted network, but the repo is public now and users run the configurator across plant networks. This is the largest security gap left in the project.

## What Changes

- The diagnostics channel is encrypted with TLS (1.2 or newer, 1.3 preferred). The plugin makes a fresh self-signed key and certificate in memory each time it opens the listener, so there is no certificate file to install, copy, back up or pin.
- The token never crosses the wire. Login is SCRAM-SHA-256 with channel binding to the server's certificate (`tls-server-end-point`, RFC 5929): the client proves it knows the token and the plugin proves it knows the token's verifier, both bound to this TLS connection. A machine in the middle cannot finish either side, and a captured exchange cannot be replayed.
- Config: new `token_verifier` in `master.diagnostics` (and the top-level `diagnostics` of a version 2 file), in the familiar `SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>` form, replaces `token_sha256`. The verifier is not a password equivalent: knowing it does not let anyone log in.
- Compatibility: a config that still has only `token_sha256` keeps working in the old plain mode, with a warning in the runtime log, in `openplc-canopen-diag status` and in the configurator's online view. One port serves both: the plugin tells TLS from plain JSON by the first byte. A config with `token_verifier` refuses plain hellos and answers an old client with "this runtime needs an encrypted connection; update openplc-canopen-diag".
- `openplc-canopen-diag` connects with TLS. Against an older plugin it stops with a clear message, and `--plain` sends the token unencrypted after a warning. `hash-token` prints a `token_verifier`; the old output is kept as `hash-token --sha256`.
- Configurator: turning on Online access writes `token_verifier`. A project that has `token_sha256` and whose token this PC knows gets an **Upgrade to encrypted** button that rewrites it. **Enter token…** checks a typed token against either form. The online view says whether the connection is encrypted.
- Standalone simulator (`openplc-canopen-sim`, port 7532): with a token its control channel uses the same TLS and SCRAM login; without a token it stays plain and loopback-only as today. `openplc-canopen-sim test --runtime` uses TLS like the diag CLI.
- Build: the plugin and `openplc-canopen-sim` link OpenSSL (libssl 3). `install-stock.sh`, the Docker install and the local simulator runtime image install `libssl-dev` for the build; the runtime images already ship libssl for their own HTTPS.
- Protocol version 2 in the hello answer. Requests and answers after login are unchanged, so every existing op and every op the planned PC-direct backend and raw-frame changes add work over the new transport without changes of their own.
- Docs: `docs/diagnostics.md` (security section rewritten, protocol section gets the login exchange), `docs/config.md`, `docs/configurator.md`, `docs/simulator.md`, `docs/local-runtime.md`; README says the channel is encrypted.

## Capabilities

### New Capabilities

### Modified Capabilities
- `canopen-online-diagnostics`: opt-in fields gain `token_verifier`; access control becomes TLS plus SCRAM login; legacy plain mode for `token_sha256` configs; client behaviour against old plugins.
- `canopen-configurator`: Online access writes `token_verifier`, offers the upgrade for old projects and shows whether the connection is encrypted.
- `canopen-simulated-bus`: the standalone control channel uses TLS and SCRAM when it has a token.

## Impact

- Plugin: `plugin/src/diag.cpp`, `diag.h` (TLS on the non-blocking poll loop, SCRAM state per client, first-byte sniff), `config.cpp` (new field), new `plugin/src/tls.cpp`/`scram.cpp`; CMake finds OpenSSL.
- Simulator: `tools/sim/control.cpp` (server and client).
- PC tools: `tools/deploy/openplc_canopen_deploy/diag.py` (Python `ssl` and `hashlib.pbkdf2_hmac`, no new dependency), `simclient.py`, configurator `server.py` and online page.
- Schemas `canopen.v1.schema.json` and `canopen.v2.schema.json`: `token_verifier`, exactly one of the two token fields.
- Scripts: `install-stock.sh`, `docker/local-runtime/Dockerfile`, CI build images.
- Deploy tool minor version bump. Configs with `token_sha256` keep working, so nothing breaks on upgrade; the old mode can be dropped in a later change.
- Overlaps: the planned "PC-direct commissioning" change reuses the diag protocol as its interface but talks to a local bus, so it needs no transport; the "raw frames and bit rate detection" change only adds ops. Whichever lands later rebases on `diag.py` and `diag.cpp`; no behaviour conflicts.
