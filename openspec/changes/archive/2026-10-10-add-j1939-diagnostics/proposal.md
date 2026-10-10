## Why

J1939 machines report faults with the diagnostic messages of SAE J1939-73: every ECU broadcasts DM1 (active trouble codes and the warning lamps) once a second, service tools read DM2 (previously active codes) and clear codes with DM3 and DM11, and flashing tools silence the bus with DM13. A trouble code (DTC) is an SPN (what), an FMI (how it failed) and an occurrence count.

canworks has none of this today (`docs/j1939.md` "Limits", README):
- a PLC cannot see another ECU's faults except by mapping the first DTC of PGN 65226 by hand as raw bits, and never more than one code
- a PLC acting as an ECU cannot report its own faults the way every J1939 tool expects
- the PC tools cannot list, read or clear trouble codes, the trace shows DM1 as raw bytes, and the simulator cannot play a faulty ECU

The exploration of 2026-10-10 (project notes `research/j1939-diagnostics-2026-10-10.md`) settled the scope with Toni:
- **both directions** in one change: other ECUs' faults to the PLC, and the PLC's own faults on the bus
- received codes reach the program through **config mapping and function blocks**
- **DM13** is included
- the change comes after `add-multiplexed-signals`, which is merged

## What Changes

- **Config** (`j1939.diagnostics`, schema version 2, optional):
  - `rx`: ECUs whose DM1 the program sees through `%I` locations: lamps, DTC count, the first N DTCs (one `UDINT` each), and a status bit
  - `dtcs`: the PLC's own trouble codes (SPN, FMI, lamps), each switched on by one `%Q` bit; `lamps_location` to set lamps directly
  - `clear_location`, `accept_clear`, `dm13`
- **Runtime plugin** (J1939 network):
  - always collects every ECU's DM1 (any length, the kernel reassembles BAM) for diagnostics and the blocks
  - sends the PLC's own DM1 every second and once on a change; counts occurrences; keeps previously active codes in RAM (never on disk)
  - answers requests for DM1 and DM2, clears with DM3 and DM11 and acknowledges them, tells the program through `clear_location`, or refuses with a NACK when `accept_clear` is false
  - honours DM13: stops its broadcasts while a tool says so, and resumes on "start" or after 6 s without a hold
- **PLC library** (`canworks`): blocks `J1939_DM_READ` (latest DM1 of an ECU, or DM2 by request) and `J1939_DM_CLEAR` (DM3 or DM11 to an ECU), functions `J1939_DTC_SPLIT` and `J1939_DTC_MAKE`, through a new plugin interface `canworks_j1939_api(1)`
- **Online diagnostics**: the status answer carries every ECU's lamps and DTCs and the PLC's own DTC state; new operations read DM2 and send DM3/DM11 through the PLC's address (clears need `force`)
- **PC tools**:
  - `canworks-diag dm list | read | clear`, through the PLC or straight through a USB adapter (claims service tool address 249)
  - configurator: a Faults panel in the J1939 online view; the PLC's DTC table and the `diagnostics.rx` mapping in the J1939 network page; DBC import skips DM PGNs
  - located variable declarations for every diagnostics location
- **Trace and frame inspector**: DM1, DM2, DM3, DM11, DM13 and DM22 decoded (lamps, every DTC with FMI text, SPN name when the DBC gives one), Component and Software ID as text
- **Simulator**: `canworks-j1939-sim` scenario `dtcs` (codes that come and go), answers DM2, DM3 and DM11
- **Docs**: `docs/j1939.md` "Diagnostic messages", README limits and features

## Capabilities

### New Capabilities
- `j1939-diagnostics`: the `diagnostics` config and the J1939 network's DM behaviour: receiving DM1 into the PLC, sending its own DM1, DM2/DM3/DM11 answers, DM13.
- `j1939-plc-diagnostics`: the PLC function blocks and ST functions for trouble codes and the plugin interface behind them.

### Modified Capabilities
- `j1939-config`: `diagnostics` is a key of the `j1939` object; its locations join the clash checks.
- `j1939-pc-tools`: DBC import skips DM PGNs; declarations, configurator editing and the online Faults panel; `canworks-diag dm`.
- `j1939-trace`: DM decoding.
- `j1939-simulator`: trouble codes in scenarios and DM requests answered.
- `canopen-online-diagnostics`: J1939 status carries diagnostics; DM read and clear operations.
- `canopen-plc-sdo`: the library also holds the J1939 diagnostics blocks.

## Impact

- **Plugin**: new `plugin/src/j1939/dm.*` (DM codec, per-source store, own DTC table, DM13 state), `j1939_config.*`, `j1939_network.*`, new `plugin/src/j1939/j1939_plc_api.*` and `can/plugin.cpp` export. No new dependency.
- **Library**: `library/canworks/J1939_DM_READ.cpp`, `J1939_DM_CLEAR.cpp`, `J1939_DTC_SPLIT.st`, `J1939_DTC_MAKE.st`, `library/src/j1939_common.inc`.
- **PC tools**: new `canworks/j1939/dm.py` (codec, FMI texts) shared by trace, diag, sim and configurator; `diag.py`, `bustrace/j1939.py`, `j1939/dbc.py`, `j1939/sim.py`, configurator J1939 page and online view, editor declarations; minor version bump. can-j1939 is already a dependency.
- **Schemas**: `canworks.v2.schema.json` (new optional object; existing configs unchanged).
- **CI**: all new code is in the j1939 area, so CANopen-only changes do not run it; tests run in the existing jobs (unit, vcan J1939 group).
- **Hardware**: no real J1939 ECU on the bench. The hardware check uses the PC adapter running `canworks-j1939-sim` as a faulty ECU beside the PLC on the Pi.
- **Not in this change**: freeze frames (DM4, DM25), emissions DMs (DM5, DM6, DM12, DM20, DM23, DM24), memory access (DM14-16), sending DM22, persistent fault history, SPN names from SAE J1939DA (not shipped; names only from the user's DBC).
