# Proposal

## Why

A new config or network in the configurator starts with SYNC every 10 ms and 250 kbit/s, whatever the protocol. Most CANopen buses run at 500 kbit/s and many have no synchronous PDOs, so the first thing a user does is change both; a J1939 network at 250 kbit/s is right, and a CANopen one is usually not. A SYNC the user never asked for also loads the bus and makes the PDO timing depend on a setting they did not choose.

Toni (2026-10-22): SYNC off by default, 500 kbit/s for CANopen and 250 kbit/s for J1939.

## What Changes

- **New CANopen networks** (New config…, Add network… → CANopen, a J1939 or plain CAN network switched to CANopen, a slave switched back to master, the page's fallback for a file with no network) start at **500 kbit/s** with **no SYNC**: `master` is `{"node_id": 1}` with no `sync_period_us`.
- **New J1939 networks** start at **250 kbit/s** (as today).
- **New plain CAN networks** start at **500 kbit/s** (today 250 kbit/s).
- **Add network…** gives the new network its protocol's default rate instead of copying the first network's rate.
- **Protocol switch** on an existing network: when the bit rate is still the old protocol's default, it moves to the new protocol's default; a rate the user changed is kept.
- **SYNC source** on the bus page gets a third choice, **Off** (the default), next to **Timer** and **PLC cycle**. Picking Timer fills 10 ms as a starting period; clearing the period goes back to Off. The config format does not change: Off is no `sync_period_us` and no `sync_source`.
- **Default PDOs without SYNC:** adding a node with **Map the EDS's default PDOs** on a network without SYNC sets transmission type 255 on each mapped PDO whose EDS type needs SYNC (0-240, 252), and the add message lists them. Without this, a new config with SYNC off would show "needs SYNC" errors for many I/O modules right after adding them.
- Hints and docs: the SYNC period hint drops "New configs start with 10 ms"; `docs/configurator.md` names the defaults.

Unchanged: the plugin, dcfgen, the CODESYS and Node-RED writers and the simulators. The plugin already treats a missing `sync_period_us` as no SYNC and requires `bitrate`, so it has no default of its own; `canworks-j1939-sim` already defaults to 250 kbit/s; the frame explainer's assumed rate stays 500 kbit/s. Commission's USB adapter connection keeps having no preset rate (a wrong rate disturbs the bus). Existing configs are not touched: the defaults only apply to what the configurator creates. Not in real use, so no migration.

## Capabilities

### Modified Capabilities

- `canopen-configurator`: defaults of new networks per protocol, SYNC Off choice, default PDOs on a network without SYNC.

## Impact

- `tools/deploy/canworks/configurator/server.py` (`empty_config`), `static/app.js` (model fallback, `addNetwork`, `switchRole`, SYNC source choice, add-node PDO defaults), `static/j1939.js` (`newJ1939Network`, protocol switch).
- Page and server tests that expect 10 ms or 250 kbit/s on a new network.
- `docs/configurator.md`, README if it names the defaults; PC tools minor version bump.
- No hardware test needed: nothing on the PLC changes. Bench configs are existing files and keep their settings.
