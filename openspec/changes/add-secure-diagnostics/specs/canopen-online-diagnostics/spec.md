## MODIFIED Requirements

### Requirement: Diagnostics channel is opt-in
The `master` object (or the top-level `diagnostics` of a version 2 file) MAY give a `diagnostics` object with exactly one of `token_verifier` (a SCRAM-SHA-256 verifier of the access token in the form `SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>`, base64 fields, iterations 4096 to 1000000, salt at least 16 bytes) and `token_sha256` (64 hexadecimal characters, the SHA-256 of the access token; legacy plain mode), plus `port` (1024 to 65535, default 7531), `bind` (an IPv4 address, default `0.0.0.0`) and `allow_changes` (boolean, default false). Without `diagnostics` the plugin SHALL open no network listener. With it, the plugin SHALL listen on `bind`:`port` from the start of the CANopen session until the PLC stops, and SHALL log the address, whether changes are allowed and whether the channel is encrypted. A listener that cannot be opened (port in use, address not on the host) SHALL be logged as a warning and SHALL NOT stop CANopen or the PLC; the plugin SHALL retry opening it every 10 seconds. An invalid `diagnostics` object, or one with both or neither token field, SHALL reject the configuration, naming the field.

#### Scenario: Not configured
- **WHEN** `canopen.json` has no `master.diagnostics`
- **THEN** the plugin opens no TCP port

#### Scenario: Enabled read-only
- **WHEN** `master.diagnostics` is `{"token_verifier": "SCRAM-SHA-256$4096:..."}`
- **THEN** the plugin logs that diagnostics listen on `0.0.0.0:7531`, read-only, encrypted, and a client with the token can read status and scan

#### Scenario: Port in use
- **WHEN** another process already listens on port 7531
- **THEN** the plugin logs a warning naming the port, CANopen runs normally, and the listener opens once the port is free

#### Scenario: Bad token hash
- **WHEN** `token_sha256` is not 64 hexadecimal characters
- **THEN** the plugin rejects the configuration and names `master.diagnostics.token_sha256`

#### Scenario: Bad verifier
- **WHEN** `token_verifier` does not start with `SCRAM-SHA-256$` or its salt is shorter than 16 bytes
- **THEN** the plugin rejects the configuration and names `master.diagnostics.token_verifier`

#### Scenario: Both token fields
- **WHEN** `master.diagnostics` has both `token_verifier` and `token_sha256`
- **THEN** the plugin rejects the configuration and names `master.diagnostics`

### Requirement: Access control
With `token_verifier`, every connection SHALL be TLS 1.2 or newer, with a key and self-signed certificate the plugin generates in memory each time it opens the listener and never writes to disk. Inside TLS the client SHALL log in with SCRAM-SHA-256 bound to the server certificate (`tls-server-end-point`): the plugin SHALL accept a login only when the client's proof matches the verifier and the certificate this connection uses, compared in constant time, and SHALL then return its server signature with the hello information. A failed login SHALL close the connection without answering any request. The token itself SHALL never be sent. Failed attempts SHALL be logged at most once per minute per peer address, and a peer address whose login failed SHALL wait at least 1 second before its next login is answered. The plugin SHALL serve at most 4 connections at a time and refuse more. Without `allow_changes`, SDO writes and NMT commands SHALL be refused with the reason "changes not allowed" and nothing SHALL be sent on the bus. Every SDO write and NMT command carried out SHALL be logged with the peer address, the node and the object or command.

#### Scenario: Wrong token
- **WHEN** a client logs in with a token that does not match `token_verifier`
- **THEN** the connection is closed, no status is returned, and one warning naming the peer address is logged

#### Scenario: Token never on the wire
- **WHEN** a client logs in and the whole exchange is captured, including the TLS keys of that connection
- **THEN** the capture does not contain the token, and replaying the client's login on a new connection fails

#### Scenario: Machine in the middle
- **WHEN** a proxy terminates the client's TLS with its own certificate and opens its own TLS connection to the plugin, forwarding the login
- **THEN** the plugin rejects the login and the client reports that the runtime could not prove it knows the token, and no request is served

#### Scenario: Write refused when read-only
- **WHEN** `allow_changes` is false and an authenticated client asks to write 0x2000 subindex 1 of node 5
- **THEN** the request is refused with "changes not allowed" and no SDO is sent

#### Scenario: Fifth client
- **WHEN** four authenticated clients are connected and a fifth connects
- **THEN** the fifth connection is refused and the four keep working

## ADDED Requirements

### Requirement: Legacy plain mode
The plugin SHALL tell TLS connections from plain ones by their first byte on the same port. With `token_sha256`, the plugin SHALL serve plain connections with protocol 1 as before (token in the hello, compared by SHA-256 in constant time), SHALL log at every listener start a warning that the token crosses the network unencrypted, and `status` SHALL report `"encrypted": false`.

#### Scenario: Old project after a plugin update
- **WHEN** the plugin is updated and the deployed config still has `token_sha256`
- **THEN** an older `openplc-canopen-diag` still connects, and the runtime log warns that the token is sent unencrypted

### Requirement: Plain connections refused with a verifier
With `token_verifier`, a plain connection SHALL get one error line, "this runtime needs an encrypted connection; update openplc-canopen-diag", and be closed without serving any request.

#### Scenario: Old client against an upgraded project
- **WHEN** the config has `token_verifier` and an older `openplc-canopen-diag` sends a plain hello
- **THEN** it receives "this runtime needs an encrypted connection; update openplc-canopen-diag" and the connection closes

### Requirement: Encrypted clients
`openplc-canopen-diag`, the configurator and `openplc-canopen-sim` SHALL connect with TLS, log in with SCRAM-SHA-256 bound to the certificate they received, and check the plugin's server signature before using any answer; a wrong signature SHALL drop the connection with "the runtime could not prove it knows this project's token". They SHALL NOT validate the certificate chain or pin a certificate. `status` SHALL say whether the connection is encrypted.

#### Scenario: Encrypted status
- **WHEN** a user runs `openplc-canopen-diag --runtime plc.local status` against a plugin whose config has `token_verifier`
- **THEN** the status prints and says the connection is encrypted

### Requirement: Clients against an older plugin
Against a plugin that does not complete a TLS handshake, `openplc-canopen-diag` SHALL stop with a message saying the plugin is too old for encrypted diagnostics and naming `--plain`. `--plain` SHALL print a warning and use protocol 1.

#### Scenario: Client against an older plugin
- **WHEN** a user runs `openplc-canopen-diag --runtime plc.local status` against a plugin without TLS
- **THEN** the command exits 1 saying the runtime's plugin does not speak encrypted diagnostics and that `--plain` sends the token unencrypted

### Requirement: Token verifier from the CLI
`openplc-canopen-diag hash-token` SHALL print a `token_verifier` with a fresh random salt and 4096 iterations; `hash-token --sha256` SHALL print the legacy `token_sha256`.

#### Scenario: New verifier
- **WHEN** a user runs `openplc-canopen-diag hash-token` twice with the same token
- **THEN** it prints two different `SCRAM-SHA-256$4096:...` verifiers, and either one in the config accepts the token
