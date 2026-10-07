## MODIFIED Requirements

### Requirement: Standalone control channel
The standalone simulator SHALL offer its live control on a TCP port (default 7532) with the same one-JSON-object-per-line framing as the diagnostics channel. It SHALL listen on 127.0.0.1 unless `--bind` names another address; on any other address it SHALL require a token (`--token` or `--token-file`). With a token, the channel SHALL use the same TLS and SCRAM-SHA-256 login as the plugin's diagnostics channel, with a verifier the simulator computes from the token at start, and SHALL refuse plain connections with "this simulator needs an encrypted connection". Without a token it SHALL stay plain. Its subcommands `status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list` SHALL use this channel.

#### Scenario: Local control
- **WHEN** a simulator runs with default options and a user runs `openplc-canopen-sim set 5 0x7130:1 450`
- **THEN** 0x7130:1 of node 5 reads 450

#### Scenario: Remote bind without token
- **WHEN** a user starts the simulator with `--bind 0.0.0.0` and no token
- **THEN** the simulator refuses to start and says a token is needed

#### Scenario: Remote control is encrypted
- **WHEN** a simulator runs with `--bind 0.0.0.0 --token-file token` and a user runs `openplc-canopen-diag sim --sim host status --token-file token`
- **THEN** the client connects over TLS, logs in without sending the token, and prints the status
