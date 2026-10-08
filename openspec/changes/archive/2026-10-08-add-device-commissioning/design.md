# Design

## Context

PC-direct commissioning (`canopen-local-bus`) gave the PC tools a guest backend on a USB adapter with the diagnostics operations, and device parameters (`canopen-device-parameters`) built backup, compare, restore and store on top of `sdo_read`/`sdo_write` on the PC side. `dcfexport.plugin_downloads()` already computes, per configured node, the exact ordered SDO writes the plugin makes at boot. The node DCF export and `compare --with-config` use it.

What a single device still lacks on the bench is: writing those settings to it, finding its bit rate when it is alone, trying its PDOs, and a guided path through the steps. This change adds them on the PC side only.

## Goals / Non-Goals

Goals:
- One command or dialog writes a node's whole configuration (PDO mapping included) to a device, from a config node or a DCF, with the same safety rules as restore.
- Find the bit rate of a device that is the only node on the bus.
- Try a device's PDOs from the PC without a PLC.
- Make "Commission a device" a guided flow that records what it changed.

Non-goals: see the proposal (firmware and 0x1021 upload, mapping editor without a config, lone-device sweep on the runtime, slave-side gaps).

## Decisions

### D1. `configure` runs on the PC over `sdo_write`, like `restore`

There is no new plugin op. It works on any target that serves `sdo_read`, `sdo_write` and `nmt`: the runtime and a local adapter. On a runtime, a node in the running config is refused ("the master writes this node's configuration at every boot; reset the node to apply the config"). This is known from `status`. `--force` does not override it: writing there would race the master's own boot download.

### D2. Two sources, one plan

- **Config node** (`--config canopen.json [--network NAME] --from-node N`): `plugin_downloads()` for that node. The command objects in it are dropped and listed with their reason: 0x1010 "save" (from `store_configuration`), 0x1011 (`restore_configuration`) and the program download. They are covered by the user's own Store and Restore-defaults ticks. The 0x1020 configuration stamp is kept, so the plugin's configuration check skips the download later if the device is then used under the plugin.
- **DCF** (`--dcf FILE`): every `ParameterValue` (or `DefaultValue` when the DCF says `[DeviceComissioning]` and has none) of an entry with access `rw`, `rwr` or `rww`. `$NODEID` is resolved with the target node ID. DOMAIN entries, 0x1010, 0x1011 and 0x1F50-0x1F57 are left out and listed. A backup DCF works as a source too. That differs from `restore`, which leaves out communication and PDO objects on purpose because the runtime's master owns them. Here the user asked for the whole configuration.

The plan holds the writes in order, the current device value (read first), and per write "differs" or "same". Only differing writes are sent, except inside a PDO sequence (D3), which is sent whole when any of its values differs.

**Node ID**: the source's node ID (config node, or the DCF's `[DeviceComissioning] NodeID`) must equal the target. Otherwise the request is refused naming both IDs, because absolute COB-IDs would point at the wrong node. A DCF without a node ID is resolved with the target.

### D3. PDO sequence

For each PDO in the plan, the order is the CiA 301 one and the one dcfgen uses:
1. COB-ID (sub 1) with bit 31 set (PDO off);
2. mapping sub 0 = 0;
3. mapping entries 1..n;
4. mapping sub 0 = n;
5. transmission type, inhibit time, event timer, SYNC start (whatever the source has);
6. COB-ID without bit 31 (or with it, if the source switches the PDO off).

Read-only communication sub-entries are skipped, as the plugin does. A device whose mapping is fixed (sub 0 or entries `ro`/`const`) gets no mapping writes and a note. A config node's download already has this order. A DCF source is sorted into it.

### D4. Checks, hold and read-back

- **Identity**: the device's 0x1018 vendor ID and product code against the source (the config node's EDS, or the DCF's `[DeviceInfo]`). A mismatch refuses the request unless `--ignore-identity` is given. A different revision is a warning, as in `restore`.
- **Hold**: on by default (`--no-hold` turns it off). Before the first write, NMT pre-operational is sent (an operator hold on a runtime, a plain command on an adapter). After the last write, the node goes back to OPERATIONAL only if it was there before (from its heartbeat, or `status` on a runtime). This also happens after a failure or Cancel. PDO mapping changes are refused by many devices while OPERATIONAL.
- **Failures**: a failed write inside a PDO sequence skips the rest of that sequence but still switches the PDO off. The rest of the plan goes on. The result lists written, same, skipped and failed entries with abort codes, and the exit status is non-zero if any write failed.
- **Read-back**: after writing, every planned entry is read again and compared. The result says "verified" or lists the differences (a device that rounds or ignores a value).

### D5. Store and restore defaults stay separate actions

`configure --store [--store-subindex N]` (configurator: "Store on device afterwards", unticked every time the dialog opens) runs the existing `store` after a fully successful write. It is not run when any write failed. `--restore-defaults` (configurator: "Restore defaults first", unticked each time) writes 0x1011 "load" and resets the node before the plan is read. `restore-defaults NODE [--subindex N] [--reset] [--yes]` is the stand-alone command. Both are offered only when the EDS lists the object. This follows the project rule that non-volatile memory is never written on its own.

### D6. Verify after a power cycle

`configure --verify-only` (configurator step "Verify") reads the device and compares it with the same source and the same plan, writing nothing. This is `compare` with the configure scope, so communication and PDO objects are included. The guided page asks the user to power-cycle the device, waits for its boot-up message (on an adapter, or the node's boot on a runtime), and then verifies. Differences after a power cycle mean the values were not stored.

### D7. Lone-device bit rate sweep (adapter only)

`detect_bitrate` on a local adapter gets `lone_device: true` and an optional `probe` (`"lss"` or `{"sdo": NODE}`).

- At each rate the adapter is opened in **normal** mode, so it acknowledges. A lone device keeps resending an unacknowledged frame (boot-up, heartbeat, EMCY, TPDO). At the right rate the adapter acknowledges it and counts a valid frame. At a wrong rate the adapter sees errors and sends error frames.
- If no valid frame arrives in the first half of `per_rate_ms`, the probe is sent once. LSS: "switch state global" to configuration, "inquire node ID", then "switch state global" back to waiting. This works for a device without a node ID and does not depend on one. SDO: an upload request of 0x1000:00 to the given node. At a wrong rate the probe is not received. At the right one the answer counts as a valid frame.
- The verdict uses the same `bitrate.decide()` rules.
- **Guards**: needs allow-changes, and in the configurator a confirmation ("only this device is on the bus; at wrong rates the adapter's error frames reach it"). It is refused when the connection has seen another master or more than one node ID in the last 30 s. If the detected rate shows more than one node ID, the result warns that the bus is not a lone device. There is no `disturb_bus` question: the mode joins the bus on purpose.
- On a runtime, `lone_device` is answered "only on a USB adapter". The plugin's sweep stays listen-only.
- The order of rates is the existing default. The sweep stops at the first `detected`.

The listen-only sweep's spec scenario that claims a lone device is detected is corrected. That held on vcan only. On hardware it needs a second device that acknowledges, as the docs already say.

### D8. PDO test (adapter only)

New local ops, all gated by allow-changes:
- `pdo_test_start {node, layout}`: the layout lists TPDOs and RPDOs with COB-ID, transmission type, event timer and entries (index, sub, bit length, type, name). The PC builds it either from `--config` (that node's PDOs) or by reading 0x1400-0x15FF/0x1600-0x17FF/0x1800-0x19FF/0x1A00-0x1BFF over SDO, with names and types from the EDS. Only valid PDOs are included (bit 31 clear). One test per node per connection.
- `pdo_test_status`: per TPDO the last frame time, count, period estimate and decoded values; per RPDO the values in force and the sent count.
- `pdo_test_set {rpdo, values}`: sets entry values by name or index:sub. An event-driven RPDO (254/255) is sent on each set and then every `repeat_ms` (default: the RPDO's event timer if set, else none). A synchronous RPDO (0-240) is sent after each SYNC the PC sends.
- `pdo_test_stop`: stops sending.
- `sync_start {period_ms (1-10000), counter (0 or 2-240)}` / `sync_stop`: the PC's SYNC producer on 0x080 (or the device's 0x1005 COB-ID if read).

Guards: refused while another master is active unless `force`. RPDO sending is refused while a foreign SYNC or NMT is seen, unless `force`. Everything stops when the connection closes, on `pdo_test_stop`/`sync_stop`, or when another master appears (the result says why). There is no time limit, unlike raw cyclic jobs. The test is something a user watches, and closing the page stops it. All frames go through the single transmit path, so they show in a trace as Tx. NMT start of the node stays a separate user action. The test page offers it.

This is the one exception to the guest rule "never sends SYNC". The requirement is modified to say SYNC is sent only while a SYNC the user started runs.

### D9. Guided "Commission a device"

The page gets a "Steps" side panel: 1 Bit rate, 2 Find the device, 3 Node ID and bit rate, 4 Identity and EDS, 5 Write configuration, 6 PDO test, 7 Store, 8 Verify after power cycle, 9 Back up. Each step opens the existing panel and shows a done/skipped mark with its result in one line. Steps can be done in any order or skipped. Nothing runs by itself.

The commissioning log is kept in the configurator's memory for the page session. It records every change made through it (SDO write, NMT, LSS set ID/bit rate/store, configure, restore defaults, store) with UTC time, node, what and result. "Save log" downloads `node<N>-commissioning-<time>.txt`, with the device identity and the EDS name at the top. It holds no host names or tokens.

"Add to a config…" picks a project or standalone config folder and opens it with the device added as an unsaved node, as "Add as node" on the scan page does (node ID, EDS imported, serial number with LSS assignment ticked if LSS was used).

## Risks / Trade-offs

- **Writing comm objects can take a device off the bus** (a wrong COB-ID or heartbeat). The preview shows these writes marked as communication, and the node ID check prevents the commonest mistake. Restore defaults is the way back.
- **Lone-device sweep on a shared bus** would send error frames into a running machine. This is mitigated by the guards (another master, several node IDs, confirmation). The residual risk is a silent second device. The docs say to use it only on a bench.
- **DCF quality** from other tools varies (missing access types, wrong `$NODEID` use). Entries without an access type are skipped with a note rather than written.
- **SYNC from the PC** conflicts with a master. The guard is the another-master detection, which only knows what it has heard. The docs repeat that the PDO test is for a bench.

## Migration Plan

Additive only. No schema, plugin or protocol change.

## Open Questions

None blocking. Defaults chosen: hold on by default for configure, LSS as the default probe in the configurator (CLI: no probe unless given), and no time limit for the PDO test.
