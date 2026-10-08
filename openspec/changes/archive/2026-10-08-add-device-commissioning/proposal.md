## Why

The tools can already find a device, give it a node ID and bit rate with LSS, browse and edit its object dictionary, back it up, compare it and save it to the device's memory, through the runtime or straight from a USB adapter on the PC. For a device that runs under the plugin's master that is enough, because the plugin writes the node's PDO mapping, communication settings and startup SDOs at every boot.

Commissioning a single device on the bench so that it keeps its own configuration still has gaps: a spare part prepared ahead, a device that goes to a bus run by another master, or a device that is checked before the machine exists.

1. **No way to write a configuration to the device.** The PDO mapping, PDO communication parameters, heartbeat and startup SDOs that a node's config or a DCF describes can only be written one SDO at a time by hand. `restore` deliberately never writes the PDO objects (0x1400-0x1BFF).
2. **The bit rate of a lone device cannot be found.** `detect-bitrate` listens without acknowledging. A device that is alone on the bus never gets an acknowledge, so none of its frames is valid and the sweep reports a silent bus. The bench hardware run of the bit rate change showed this, and its docs now ask for a second device.
3. **No PDO test from the PC.** The PC never sends SYNC, outputs can only be sent as raw frames with `force`, and inputs can only be read in a decoded trace.
4. Smaller: restoring the factory defaults (0x1011) is only a boot step of a configured node, and "Commission a device" is a set of separate panels with no order, no record of what was changed and no way to carry the device into a config.

Research: `research/single-slave-commissioning-2026-10-08.md` in the project files.

## What Changes

- **Write configuration** (`openplc-canopen-diag configure NODE`, configurator "Write configuration…"): writes a node's configuration to a live device over SDO and reads it back. The source is either a node of a `canopen.json` (exactly the writes the plugin makes at boot, from the same `plugin_downloads` code as the DCF export and `compare --with-config`) or a CiA 306 DCF (a node DCF from the export, a backup, or another master's tool). PDO objects are written in the CiA 301 order (switch the PDO off, clear the mapping count, write the entries, set the count, set the communication parameters, switch it on). The plan is shown first and the identity is checked, as for `restore`. The node is held in PRE-OPERATIONAL while writing and put back afterwards. Store (0x1010) and restore defaults (0x1011) in the source are never written as part of it; storing stays a separate tick or command. It works on a runtime and on a USB adapter. A node the runtime itself configures is refused there, because the master already writes it at every boot.
- **Restore defaults** (`restore-defaults NODE`, configurator "Restore defaults…"): writes "load" to 0x1011 after asking, with an optional NMT reset so it takes effect. It is never part of any other action.
- **Bit rate of a lone device** (`detect-bitrate --lone-device`, configurator "Only this device is on the bus"): a sweep on a USB adapter that joins the bus at each rate in normal mode, so it acknowledges the device's frames. An optional probe (`--probe lss`, or `--probe sdo:NODE`) makes a quiet device answer. It needs allow-changes and a confirmation, because at wrong rates the adapter's error frames reach the bus. It is refused when another master was seen. The existing listen-only sweep stays the default and the only mode on a runtime.
- **PDO test on a USB adapter** (`openplc-canopen-diag pdo-test NODE`, configurator node tab "PDO test"): reads the node's PDO layout from the device (or takes it from the config), shows TPDO values decoded with names and types, sends RPDO values set by name, and optionally sends SYNC at a chosen period. All of this needs allow-changes, stops when the connection closes, and is refused while another master is active unless forced. This is the one place where the PC sends SYNC, and only on the user's request.
- **Guided "Commission a device"**: the page gets a step list (bit rate, find the device, node ID and bit rate, identity and EDS, write configuration, test, store, verify after a power cycle, back up). Each step opens the existing panel and shows its result. It also keeps a commissioning log of every change made through the page (SDO writes, NMT, LSS, write configuration, restore defaults, store), which can be saved as a text file. "Add to a config…" carries the device (node ID, EDS, serial number) into a project or standalone config as an unsaved node.
- **Docs and README**: `docs/pc-adapter.md` (a commissioning walk-through, lone-device bit rate, PDO test), `docs/diagnostics.md` (`configure`, `restore-defaults`), `docs/configurator.md`, README feature lists.

## Capabilities

### New Capabilities
- `canopen-device-commissioning`: writing a configuration to a live device (sources, scope, order, checks, hold, read-back, result), restore defaults, verifying after a power cycle, and the CLI commands, on a runtime and on a USB adapter.

### Modified Capabilities
- `canopen-local-bus`: new operations for the PDO test and SYNC, the guest rule's one exception (SYNC the user starts), and the lone-device bit rate sweep. The listen-only sweep's lone-device scenario is corrected: it needs a second device that acknowledges.
- `canopen-configurator`: guided "Commission a device" with log and "Add to a config…", the Write configuration and Restore defaults dialogs, the PDO test tab, and "Only this device is on the bus" in Detect.

## Non-goals

- Firmware download (0x1F50-0x1F57) and reading a device's own EDS (0x1021) from the PC.
- Editing a PDO mapping without a config. The source for a device that goes to another master is a DCF from that master's tool, or a standalone config whose node is mapped there.
- A lone-device sweep on the runtime. The plugin's sweep stays listen-only, and the runtime normally runs a configured bus.
- Plugin-as-slave gaps (LSS bit rate change, SDO client on a slave network).

## Impact

- `tools/deploy`: a new `commissioning.py` (configure plan and write, DCF and config sources, PDO sequence, read-back, restore defaults), `diag.py` commands `configure`, `restore-defaults`, `pdo-test` and `detect-bitrate --lone-device/--probe`, and `localbus/` ops `pdo_test_start`, `pdo_test_set`, `pdo_test_status`, `pdo_test_stop`, `sync_start`, `sync_stop`, plus the lone-device mode in `sweep.py`. The configurator's `server.py`, `params.py` and `app.js` get the dialogs, the PDO test tab, the guided page and the log.
- No plugin (C++) change, no config schema change, and no change to the diagnostics protocol of the runtime: `configure` and `restore-defaults` run on the PC over `sdo_write` and `nmt`, like `restore`.
- Tests: unit tests with the virtual bus and fake devices, and a vcan CI step against `openplc-canopen-sim` (configure from a config node and from a DCF, then compare against the source with no difference, restore defaults, PDO test round trip). The lone-device sweep's normal-mode behaviour is checked with the adapter opener mocked. On vcan every frame is "acknowledged", so the real effect needs hardware.
- PC tools version: the next free minor when applied.
