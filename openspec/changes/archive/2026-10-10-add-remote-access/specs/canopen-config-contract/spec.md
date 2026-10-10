## ADDED Requirements

### Requirement: Remote link settings in the config
The schema and the config checks (plugin, bridge and PC tools) SHALL accept an optional `remote_link` object in the diagnostics settings (`diagnostics.remote_link` in version 2, `master.diagnostics.remote_link` in version 1) with `internet` (boolean, default false), `relays` (list of `https://` URLs, at most 8) and `pairing` (`"lan"`, `"anywhere"` or `"off"`, default `"lan"`). Other keys or values SHALL be rejected with the path of the bad field. The plugin and the bridge SHALL not otherwise act on it.

#### Scenario: Bad relay URL
- **WHEN** `remote_link.relays` contains `http://relay.example.com`
- **THEN** the config check fails naming `diagnostics.remote_link.relays[0]` and saying relay URLs must use https
