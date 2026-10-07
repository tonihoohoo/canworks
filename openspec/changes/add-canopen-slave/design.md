## Context

The plugin runs one Lely `BasicMaster` per network (`Bus` thread, Lely loop, `Network`, `ProcessImage`), with schema version 2 for several networks (merged). The device simulator change (branch `propose/add-device-simulator`, implemented, not on main yet) adds `plugin/sim/` with `SimDevice`, a Lely `BasicSlave` built from an EDS that already has the store image (0x1010/0x1011), LSS-stored node ID, SDO indications in front of Lely's, TPDO event signalling after a value change, a node ID conflict guard, and runs on the bus thread's loop on a virtual bus or a real interface.  

This change covers OpenPLC as a slave under another PLC. A master on one interface and a slave on another in the same file comes with it from the version 2 layout, but no gateway features are added.

## Goals / Non-Goals

**Goals:**
- A complete CiA 301 slave from an EDS, bound to the PLC image, with the master side free to remap PDOs.
- Defaults from the EDS, as on the master side: the config adds only the node ID and bindings.
- An EDS users can generate and hand to the other master's tool, identical to what runs.
- Reuse of the simulator's slave device code, not a second copy.

**Non-Goals:**
- Master and slave on one interface; flying master.
- LSS bit rate change; changing the adapter from a bus message.
- MPDO, SRDO, CANopen FD, program download (0x1F50) into OpenPLC, an SDO client on a slave network.
- Gateway helpers that copy values between networks (the PLC program does that).
- Strings and domains as bound objects (PLC locations are 1-64 bit).

## Decisions

### D1. A network role, not a separate config file
`role: "slave"` on a version 2 network with a `slave` object. The adapter definition and every per-network mechanism (name, work dir, log prefix, interface uniqueness, IEC overlap check across networks, diagnostics hub per network) are reused as they are. Version 1 gets no slave form: one more v1 shape would add a code path for a case version 2 already covers, and tools then write version 2 for any slave network.
*Alternative:* a top-level `slave` in version 1. Rejected for the reason above.

### D2. Shared slave device base
Extract from `SimDevice` a `SlaveDevice` base (`plugin/sim/` or `plugin/src/slave_device.*`) holding the parts both need: EDS load with node ID, store image with a pluggable backend, LSS hooks, SDO indication chain, `Changed()` for TPDO events, conflict guard. `SimDevice` keeps the fault and source layers on top; the new `PlcSlave` adds the PLC bindings and status. The simulator change lands first; this change does the extraction. If the order flips, this change adds the base and the simulator rebases on it.

### D3. Bindings per object, direction from access type
The external master owns the mapping, so a binding names an object, not a PDO entry. Direction from the EDS access type keeps the config free of a second source of truth (the defaults rule), and it gives a hard guarantee that the master can only reach `%I`.

| Access | Written by | PLC |
|---|---|---|
| `rww`, `rw` | master (RPDO or SDO) | `%I` |
| `ro`, `rwr` | PLC | `%Q` |
| `const`, `wo` | | rejected |

`wo` objects are rejected because the PLC could neither read them meaningfully nor publish them.

### D4. Data path
A `SlaveImage` with the same triple buffers as `ProcessImage`:
- Inputs: after each RPDO write and SDO download indication on a bound object, the loop thread copies the value into the input working copy and publishes; `cycle_start` copies the latest snapshot to `%I`.
- Outputs: `cycle_end` publishes `%Q`; the loop thread takes the newest snapshot every 1 ms tick (`kOutputPeriod`, as the master's no-SYNC path) and on each SYNC indication before Lely samples synchronous TPDOs, writes changed values with `co_sub_set_val` and calls the TPDO event for event-driven PDOs that map them (Lely honours inhibit time).
Latency PLC -> bus is at most one scan plus 1 ms. Nothing in the scan path waits, allocates or logs.

### D5. Status and EMCY
State byte from Lely's NMT state; communication OK from OPERATIONAL and the absence of an active heartbeat-consumer or life-guarding error (Lely's `OnHeartbeat`/`OnLifeGuarding` indications); SYNC count from `OnSync`. EMCY from the program: the loop compares the code and register locations with the last sent pair and calls Lely's `Error(eec, er)` / error reset, so 0x1003, 0x1001 and 0x1015 behave as Lely implements them.

### D6. State file outside the upload
Stored parameters (concise DCF per saved range), the LSS node ID and the EDS SHA-256 go to `<state dir>/<network>.json`, where the state dir is `<plugin prefix>/state` on a native install and a directory on the runtime container's persistent volume in Docker mode (install-stock.sh creates it; exact path fixed with the Docker task). Uploads replace the config directory, so a file there would lose what the master saved. A changed EDS hash ignores the file with a warning rather than applying values to a different dictionary. The file is written only on an explicit 0x1010 save or LSS store, never automatically.

### D7. LSS
The Lely slave is built with LSS. `node_id: null` starts with 0xFF; an LSS store writes the state file; bit timing requests are refused (error 1) because the plugin owns the adapter's bit rate.

### D8. EDS generator in the deploy tool
`tools/deploy/openplc_canopen_deploy/slaveeds.py`, used by the CLI and the configurator. Manufacturer layout: records 0x2000 + n (from master) and 0x2100 + n (to master), one per data type, subindex 0 = count; CiA 401: 0x6000/0x6200 (8-bit digital), 0x6401/0x6411 (INTEGER16 analog), device type 0x00000191 with the I/O bits set. Default PDOs packed in object order; COB-IDs `$NODEID+0x180`/`0x200`...; 0x1017 default from the description (default 1000 ms); 0x1010/0x1011/0x1020 present so store and configuration check work. The output is linted with the same `edslint` module before it is written.

### D9. Diagnostics
`DiagHub` per network gains a slave flavour: status fields from D5, the PDO mappings read from the local dictionary, local OD reads. Master-only ops answer `network is a slave`. Protocol stays 1; the new fields are optional.

### D10. Shared simulated bus for a master and a slave
The simulator change gives each simulated network its own in-process virtual bus. Here simulated networks with the same `interface` name share one `VirtualCanController`, at most one master and one slave, so one config can run the plugin's master against the plugin's slave with no adapter, vcan or privileges, including the Docker install. It is how the tests and the Pi check work without a second master. Real interfaces keep the one-network-per-interface rule.
*Alternative:* allow master and slave on one real interface (two sockets, kernel loopback). Rejected: on a real bus that is a second device of the same controller on the wire, which users would mistake for a supported layout; vcan plus `cangw` covers the socket path in tests.

## Risks / Trade-offs

- [The master writes inputs at bus speed while the scan reads them once per cycle] -> the newest value wins, as for master-side RPDOs; documented.
- [A user EDS with odd access types (e.g. everything `rw`)] -> every `rw` object is an input; the error message for an output on an `rw` object suggests `rwr`, and the generator never emits this.
- [State file applied to a different device after a node ID change] -> keyed by network name and EDS hash; the node ID is part of the file and a mismatch is logged.
- [Depends on the simulator branch for the base] -> D2 allows either order.
- [No second master on the bench] -> the plugin's own master is the other side: on a shared simulated bus (D10), on a vcan pair joined by `cangw`, and on the Pi next to the existing real network. A test against another vendor's master stays a user report, not a task.

## Migration Plan

Additive: no existing field changes meaning; `role` defaults to `"master"`. Rollback is removing the slave network from the config.

## Open Questions

- The Docker state directory path, settled when the Docker task is implemented.
