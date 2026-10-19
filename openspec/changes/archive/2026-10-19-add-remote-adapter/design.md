# Design: add-remote-adapter

## Server

`canworks/localbus/serve.py`, entry `canworks-diag adapter-serve`. A threaded TCP server (stdlib `socketserver`), one thread per connection, JSON lines as the plugin's diagnostics channel uses.

- **TLS:** a P-256 self-signed certificate made at start with the `openssl` command (present on every Linux distribution the tools support; the error names the package when it is missing), loaded with `ssl.SSLContext.load_cert_chain` from a 0700 temporary folder that is removed right after loading. No pinning, as with the plugin: SCRAM is bound to the certificate (`tls-server-end-point`), so a man in the middle cannot complete the login. Alternative: the `cryptography` package; not taken, to keep the dependency list as is.
- **Login:** the server half of the SCRAM-SHA-256 exchange the client in `diag.py` already speaks (`hello` with mech + nonce, then the proof), checked against the stored verifier with `diag.parse_verifier`. Server signature returned so the client verifies the server too. Protocol number as the plugin's (`diag.PROTOCOL`).
- **Operations:** after login each request goes to `LocalBus.request(op, **fields)` on one shared `LocalBus` (the existing `_Shared` core lets several handles use one adapter). The hello result is `LocalBus`'s (`local: true`, `adapter`, `bitrate`), plus `remote: "<host name>"`. Cyclic jobs, traces and PDO tests belong to the connection that started them and stop when it closes, as on a local adapter.
- **Opening:** the adapter opens at the first login with `--bitrate` and runs `core.check_bitrate`; a refused check is the login's error (the client sees the same message as with a local adapter). The last connection closing closes the adapter, so `canworks-diag --adapter` on the machine itself can use it again.
- **Changes:** server `--allow-changes` off means every operation in `localbus.client.CHANGES` answers refused with "the adapter server on HOST was started without --allow-changes". With it on, the session's own allow-changes (sent by the PC) still decides.
- **Limits:** 4 logged-in PCs, 8 connections not logged in (2 per address), 30 s to log in, idle connection closed after 10 minutes, failed logins 1 per second per address and 10 per minute in total, logged.
- **Bind:** all addresses by default (it is useless on loopback only), `--bind` for one address or `127.0.0.1` when it is only reached through SSH.

## Token

`adapter-serve.json` in the PC tools' settings folder (`userdirs`), mode 0600, holds `token_verifier` per port. First start without one: `diag.new_token()`, print `token: <token> (shown once; --new-token makes another)`, save the verifier. `--token-file PATH` uses a given token instead (for scripted installs). The plain token is never written on the server.

## Service

`--install-service` (needs root) writes `/etc/systemd/system/canworks-adapter-<channel>.service`: `User=$SUDO_USER`, `AmbientCapabilities=CAP_NET_ADMIN` (to bring a SocketCAN interface up at the bit rate, as `adapter._socketcan_up` does), `Restart=on-failure`, `ExecStart=<this canworks-diag> adapter-serve <same options>`, and an Avahi service file `_canworks._tcp` with TXT `kind=adapter`, `name`, `adapter`, `bitrate`, `v=1` when Avahi is installed. The token is made before the unit starts, as the user, and printed. `--remove-service` stops, disables and removes both files. `adapter-serve --status` shows whether the service runs and who is connected.

## PC side

- `diag.parse_runtime`-style target `remote:HOST[:PORT]` for `--adapter`: a `diag.Client` with the token (`--token`/`--token-file`/prompt) whose hello must say `local: true`, else "HOST is a runtime, not an adapter server: connect without remote:".
- Discovery lists `kind=adapter` answers separately ("adapter servers").
- Configurator: `online.RemoteAdapterTarget(host, port)` next to `AdapterTarget`, opened as a `diag.Client`; the connection stays open until Disconnect like an adapter connection. Tokens are kept in `online.json` per host, like runtime tokens. Recent connections get kind `remote_adapter` (no token).
- The bit rate field is not shown for a remote adapter: the server's bit rate is shown, and with a config a mismatch with the network's bit rate is a warning in the panel.

## Risks

- An SDO block transfer or scan is as fast as on a local adapter because it runs on the server; a trace over a slow link fetches in batches (`trace_fetch`) and may lag, not lose frames (the server keeps `TRACE_MAX`).
- Two PCs commissioning the same bus at once: allowed (as two tools on one local adapter today); the "another master" checks still apply per request.
