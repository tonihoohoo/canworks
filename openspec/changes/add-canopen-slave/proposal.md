## Why

The plugin can only be the CANopen master. A common plant layout has a larger PLC as the NMT master and smaller controllers as CANopen devices under it, so today an OpenPLC controller cannot join such a bus at all. CiA 301 slave behaviour (NMT slave, heartbeat, SDO server, remappable PDOs, EMCY, store/restore, LSS) is already in Lely's slave stack, and the device simulator change runs Lely slaves from an EDS inside the plugin. Adding a slave role is mostly binding that device to the PLC image and giving users an EDS they can import into the other master's tool.

## What Changes

- **Slave network role**: in a version 2 config a network can have `"role": "slave"` with a `slave` object instead of `master` and `nodes`. On that network OpenPLC is one CANopen device under another NMT master. Master networks and slave networks can sit in the same file on different interfaces; master and slave on one interface is rejected.
- **The slave runs from an EDS**: the user's own EDS, or one the PC tools generate. Everything except the node ID and the PLC bindings comes from that file (PDO defaults, transmission types, timers, heartbeat, error behaviour), as on the master side.
- **Bindings to objects, not PDOs**: each `objects` entry binds one dictionary object to one PLC location. The direction comes from the EDS access type: objects the master writes (`rww`, or `rw` parameters) feed `%I` inputs; objects the master reads (`ro`, `rwr`) are written from `%Q` outputs. The data flows whatever PDO mapping the master sets, or over SDO.
- **Full CiA 301 slave behaviour**: NMT slave with boot-up, heartbeat producer and consumer, node and life guarding, SDO server, RPDO/TPDO with mapping changeable by the master, SYNC and TIME consumer, error behaviour (0x1029), store and restore (0x1010/0x1011) kept across uploads and restarts, configuration date (0x1020), and LSS slave (node ID assignment and store; bit rate change answered as not supported).
- **Status and EMCY for the program**: optional locations for the own NMT state, a communication OK bit, a SYNC counter, and an EMCY code plus error register that the program sets to send emergency messages.
- **EDS generator on the PC**: `openplc-canopen-deploy slave-eds` and the configurator build an EDS from an object list (name, data type, direction, default, limits) and identity, in a manufacturer-area layout (default) or a CiA 401 generic I/O layout, with default PDOs that carry every object. The configurator exports the same file for the other master's tool.
- **Tools**: configurator role switch and slave device page, deploy checks and bundle for slave networks, located variable declarations and editor project for slave bindings, slave status in the diagnostics channel and online view.

## Capabilities

### New Capabilities
- `canopen-slave-device`: the plugin's slave network at run time: start-up from the EDS, NMT/heartbeat/SDO/PDO/SYNC/EMCY/LSS behaviour, object bindings to the PLC image, status locations, stored parameters, and what happens on communication loss.
- `canopen-slave-eds`: generating a slave EDS on the PC from an object list, its layouts, default PDOs and identity, and exporting it.

### Modified Capabilities
- `canopen-config-contract`: `role` and `slave` in a version 2 network; simulated master and slave networks sharing one simulated bus; a config with a slave network is always written as version 2.
- `canopen-configurator`: network role switch, slave device page (objects, identity, status locations, EDS generate and export).
- `canopen-deploy`: checks and bundling for slave networks and their EDS.
- `canopen-editor-project`: declarations and project template for slave bindings.
- `canopen-online-diagnostics`: slave network status and its own dictionary in the online view.

## Impact

- `plugin/src`: config loader (role, slave object), a slave bus session next to the master one, a slave process image, state file for stored parameters and LSS node ID, diagnostics status. Builds on the device simulator change's slave device base (`plugin/sim/`), which this change shares rather than duplicates; that change lands first.
- `schema/canopen.v2.schema.json` (slave network), `schema/canopen.v1.schema.json` unchanged.
- `tools/deploy`: contract helpers, EDS generator (`slaveeds.py`), CLI `slave-eds`, bundle and checks, configurator page, declarations, editor project.
- Docs: `docs/slave.md`, config, configurator, deploy, README feature list.
- Tests: sim tests with the plugin's own master against the plugin's slave on a virtual bus, a vcan test, generator unit tests. Simulated master and slave networks can share one simulated bus, so the plugin's own master is the other side in tests and on the Pi (current setup, vcan pair and simulation), with no second master needed.
- Deploy tool minor version bump.
