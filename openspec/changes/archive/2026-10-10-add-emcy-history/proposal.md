## Why

The PLC program sees a node's emergency messages only through `emcy_code_location` and `error_register_location`, which hold the latest EMCY (docs/config.md, "Emergency messages"). An EMCY followed by its error reset within one scan, or the same code twice in a row, never reaches the program; only the log and the diagnostics history (the last 16 per node, `Network::HandleEmcy`, plugin/src/canopen/network.cpp:1418) keep them. The device's own error history, the pre-defined error field 0x1003 of CiA 301, is never read, so after a restart nobody can see what the device recorded before. And the master listens for a node's EMCY on the COB-ID its EDS gives as the default of 0x1014 (`add_emcy_consumers`, plugin/src/canopen/dcf_gen.cpp:536): a device whose EMCY COB-ID was changed on the device is not heard at all, without any warning.

## What Changes

- New function block `CO_RECV_EMCY` in the `canworks` editor library, in the spirit of the CiA 405 `RECV_EMCY` / `RECV_EMCY_DEV` blocks: while `ENABLE` is TRUE each call takes one EMCY of the selected network (all nodes, or one node with `NODE`), with node, error code, error register, the 5 manufacturer bytes and a UTC timestamp. It drains a per-network EMCY queue of 64 entries that the plugin fills from the start of the CANopen session; every reader has its own position in it, so two block instances never take each other's messages. Messages a reader missed because it fell behind are counted (`LOST`) and flagged (`OVERFLOW`).
- The plugin's C interface for the library gets version 2 (`CANOPEN_PLC_API_VERSION`), a superset of version 1 with the EMCY read functions. The SDO blocks keep asking for version 1, so they keep working with an older plugin; only `CO_RECV_EMCY` needs the new plugin.
- Device error history: `canworks-diag errors NODE` and an "Error history (0x1003)" panel in the configurator's online node page read 0x1003 sub-index 0 (count) and the entries, newest first, and decode each with its CiA 301 error class and the manufacturer-specific upper 16 bits. `errors NODE --clear` and the panel's Clear button write 0 to 0x1003 sub-index 0. Both go through the existing manual SDO read and write operations, so the clear needs `allow_changes` and, on an OPERATIONAL node, `force`, exactly like any other manual write; the panel asks before clearing. They work against a runtime and on a local adapter.
- EMCY COB-ID: new optional node field `emcy_cob_id`. Left out (or `"device"`), after each successful boot the master reads the node's 0x1014 sub-index 0 and listens on that COB-ID when it differs from the one it uses; `"eds"` keeps today's behaviour (no read); a number fixes the COB-ID in the master DCF. A startup SDO to 0x1014 sets the listened COB-ID too. A value with bit 31 set (EMCY not valid), a 29-bit value, a restricted CAN-ID or one another identifier of the network already uses is not taken: the master keeps its current COB-ID and logs one warning saying why. The status answer reports per node the COB-ID in use and where it came from.
- `emcy_code_location` and `error_register_location` keep their exact meaning; the queue is a separate path.
- JSON Schema (v1 and v2 share the node definition), `contract.py` and its parity fixtures, configurator node page field; README and docs/plc-sdo.md, docs/config.md, docs/diagnostics.md, docs/configurator.md.

## Capabilities

### New Capabilities

### Modified Capabilities
- `canopen-plc-sdo`: new `CO_RECV_EMCY` block, the per-network EMCY queue, API version 2; the library also holds the EMCY block.
- `canopen-node-supervision`: EMCY COB-ID from the device (0x1014) or the config, and what happens to an invalid or disabled one.
- `canopen-online-diagnostics`: device error history read and clear through the command-line client; status carries the EMCY COB-ID per node.
- `canopen-configurator`: error history panel and Clear in the online node page; `emcy_cob_id` field on the node page.
- `canopen-config-contract`: `emcy_cob_id` in the schema.

## Impact

- Plugin: new `plc_emcy.h`/`plc_emcy.cpp` (the queues), `canopen_plc_api.h` and `plc_api.cpp` (version 2 table), `network.cpp`/`network.h` (`HandleEmcy` feeds the queue; 0x1014 read after a boot in `HandleBoot`; master 0x1028 update), `dcf_gen.cpp` (`add_emcy_consumers` takes a configured COB-ID), `config.h`/`config.cpp` and `eds_check.cpp` (the field and its checks), `frame_tx.cpp` (raw-frame guard and frame names follow the COB-ID in use), `network_diag.cpp` (status).
- Library: `library/canworks/CO_RECV_EMCY.cpp`, `library/src/common.inc` (version 2 table), `library/generate.py`; `canworks.stlib` rebuilt.
- Tools: `diag.py` (`errors` command), a shared 0x1003 helper used by the CLI and the configurator (`configurator/server.py` routes, `static/app.js` panel and node field), JSON Schema, `contract.py`, test fixtures. Deploy tool minor version bump (the library version follows it).
- Config format: one new optional node field within `schema_version` 1 and 2. A config without it gets one extra SDO read (0x1014) per boot for nodes whose EDS has 0x1014; the master DCF is unchanged unless a number or a startup SDO to 0x1014 is given.
- Not affected: the latest-EMCY inputs, the EMCY log and its throttling, the 16-entry diagnostics history, gateway EMCY forwarding, slave networks (their own EMCY producer), J1939 and plain CAN networks.
- README: the "Status for the program" and "From the program" lines.
