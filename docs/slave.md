# OpenPLC as a CANopen slave

A network with `"role": "slave"` makes the PLC one node of a CANopen network that another master runs: a line controller, a robot cell's PLC or a building controller. That master configures the slave from an EDS, exchanges PDOs with it, and supervises it by heartbeat; the PLC program reads what the master writes from `%I` locations and answers through `%Q` locations. A slave network sits in a `schema_version` 2 file next to any master networks ([config.md](config.md#slave-networks)), and the same PLC can be a slave on one network and the master of others; with routes between them it is a [gateway](gateway.md).

[`config/slave`](../config/slave/README.md) is a complete example: node 10 with three objects from the master and three to it, the status locations and an EMCY from the program.

## Steps

1. Describe the objects the two sides exchange in a short JSON file, and generate the EDS from it with `canworks-deploy slave-eds` ([below](#the-eds)) or with **Build the EDS** in the configurator ([configurator.md](configurator.md#slave-networks)).
2. Add a network with `"role": "slave"`, its adapter, the node ID the other master expects, the EDS, and a PLC location for each object the program uses.
3. Deploy as usual: the deploy tool and the editor hook carry the EDS with the config, and the plugin runs that file.
4. Import the same EDS into the other master's configuration tool (**Export EDS** in the configurator gives it a name from the device name). The file the other master imports and the file the plugin runs are the same bytes.

## The config

```json
{
  "schema_version": 2,
  "networks": [
    {
      "name": "line",
      "role": "slave",
      "adapter": { "type": "socketcan", "interface": "can1", "bitrate": 250000 },
      "slave": {
        "node_id": 10,
        "eds": "openplc-slave.eds",
        "objects": [
          { "index": "0x2000", "subindex": 1, "iec_location": "%IW300", "name": "speed_setpoint" },
          { "index": "0x2100", "subindex": 1, "iec_location": "%QW300" }
        ],
        "inputs_on_loss": "zero",
        "comm_ok_location": "%IX300.1"
      }
    }
  ]
}
```

Every field is in [config.md](config.md#slave-networks). The config adds only the node ID and the bindings: PDO mapping, heartbeat, guarding, SYNC consumer and error behaviour all come from the EDS, and the other master changes them over SDO as CiA 301 allows.

## Direction

A binding names an object, not a PDO entry, because the other master owns the PDO mapping: a bound object keeps working whatever PDO carries it, or when the master only reads or writes it by SDO. Who writes the object comes from its `AccessType` in the EDS:

| AccessType | Written by | PLC location |
|---|---|---|
| `rww`, `rw` | the master (RPDO or SDO) | `%I` |
| `ro`, `rwr` | the PLC program | `%Q` |
| `const`, `wo` | | cannot be bound |

So the master can only ever reach `%I` locations. A location of the wrong area, a size that does not fit the object's type, an object the EDS does not define or an object bound twice is rejected, with the message naming the object, the access type and the area it needs. In an EDS that marks everything `rw` every object is an input; give the objects the program writes `rwr` (the generator never writes `rw`).

## At runtime

- At PLC start the plugin loads the EDS, runs the same lint and checks as for master networks, sets the node ID and sends its boot-up message. A config error opens no interface of any network.
- After boot-up the slave waits in PRE-OPERATIONAL for the master's NMT start, as CiA 301 asks. (Lely would start a device without an NMT startup object by itself, so an EDS without 0x1F80 gets a read-only 0x1F80 = 0x04, "do not start by itself"; an EDS with 0x1F80 keeps its own value.)
- The slave obeys NMT start, stop, pre-operational, reset node and reset communication, addressed to its node ID or broadcast; PDOs move only in OPERATIONAL. Its SDO server answers uploads and downloads (expedited, segmented and block) for every object the EDS allows.
- A value the master writes to a bound input, by RPDO or SDO, reaches the PLC at the next scan start; with several writes in one scan the newest wins. Inputs keep their last value while the node is not OPERATIONAL or the master's heartbeat is lost, unless `inputs_on_loss` is `"zero"`.
- At the end of each scan changed output values go into the dictionary: synchronous TPDOs carry them at the next SYNC, event-driven TPDOs that map them are sent (inhibit time applies), and an SDO upload returns them. From the program to the bus takes at most one scan plus 1 ms. On entering OPERATIONAL every event-driven TPDO is sent once, so the master has all values without waiting for a change.
- A "save" the master writes to 0x1010 stores the selected ranges in a state file outside the uploaded project, `<prefix>/state/<network>.json` (`/opt/canworks/state` on a native install and on the Docker install's bind-mounted prefix; the environment variable `CANOPEN_STATE_DIR` overrides the directory), so an upload does not lose them; a "load" to 0x1011 deletes them. Stored values (also 0x1020, so a master that checks the configuration date can skip its download) are applied after every start and reset node while the EDS is unchanged; with a changed EDS they are ignored with a warning.
- With `"node_id": null` the slave starts without a node ID and waits for an LSS master: it answers switch, identify and fastscan by its 0x1018 identity (fastscan only while it has no node ID, as CiA 305 has it) and keeps an ID stored by LSS in the state file. An LSS bit rate change is answered as not supported: the adapter's bit rate comes from the config.
- A frame from another device with the slave's own node ID is logged once per PLC start.

## Status and EMCY

| Field | Location | Meaning |
|---|---|---|
| `state_location` | `%IB` | Own NMT state: 0 not started, 4 stopped, 5 operational, 127 pre-operational. |
| `comm_ok_location` | `%IX` | TRUE while OPERATIONAL with no heartbeat consumer or life guarding error. |
| `sync_count_location` | `%IW` | SYNCs received, wrapping at 65535. |
| `emcy_code_location` | `%QW` | A change to a non-zero code sends one EMCY with it and sets 0x1001; a change to 0 sends the error reset. EMCY inhibit time (0x1015) applies. |
| `error_register_location` | `%QB` | The error register sent with that EMCY. |

## The EDS

`canworks-deploy slave-eds` writes a CiA 306 EDS from a JSON description ([deploy.md](deploy.md#the-slave-eds)):

```json
{
  "device_name": "OpenPLC slave example",
  "vendor_id": 0,
  "product_code": 1,
  "heartbeat_ms": 500,
  "layout": "manufacturer",
  "objects": [
    { "name": "speed_setpoint", "type": "UNSIGNED16", "direction": "from_master", "default": 0, "high": 3000 },
    { "name": "actual_speed", "type": "UNSIGNED16", "direction": "to_master" }
  ]
}
```

| Field | Default | Meaning |
|---|---|---|
| `device_name` | `OpenPLC slave` | `ProductName` and 0x1008. |
| `vendor_name` | `OpenPLC` | `VendorName`. |
| `vendor_id`, `product_code` | 0 | 0x1018:1 and :2. |
| `revision_number` | from the content | 0x1018:3. Left out: the low 32 bits of a SHA-256 of the layout and the objects, so a master that checks identity notices a changed dictionary that was not imported again. |
| `heartbeat_ms` | 1000 | Default producer heartbeat time (0x1017). |
| `layout` | `manufacturer` | `manufacturer`: objects from the master in ARRAYs from 0x2000, objects to the master from 0x2100, one ARRAY per data type in the order the types first appear, sub-index 0 the count. `cia401`: device type 401 with the generic I/O objects, digital inputs 0x6000 and outputs 0x6200 (UNSIGNED8), analog inputs 0x6401 and outputs 0x6411 (INTEGER16); CiA 401 inputs are what the master reads. |
| `objects[]` | | `name` (unique), `type` (a CANopen type: BOOLEAN, INTEGER8-64, UNSIGNED8-64, REAL32, REAL64), `direction` (`from_master`: AccessType `rww`, a PLC input; `to_master`: `ro`, a PLC output), and optional `default`, `low` and `high`. |

The file has default RPDOs carrying the objects from the master and TPDOs carrying those to the master, packed in object order, 8 bytes each, with transmission type 255. PDOs 1-4 always exist with the CiA 301 COB-IDs (`$NODEID` + 0x180, 0x200, ...; unused ones switched off), so the master can remap them; PDOs 5 and up start switched off and get their COB-ID from the master. The communication area has what a CiA 301 slave with store and restore, configuration date, heartbeat, guarding, EMCY and LSS needs. The output is deterministic (no dates in it) and passes the plugin's EDS lint with `eds_lint: "all"`; the generator checks that before it writes.

A vendor-style EDS written by hand works too: any objects with access types from the table above can be bound.

## Diagnostics

With the top-level `diagnostics` object a slave network is served like a master network ([diagnostics.md](diagnostics.md)): the hello lists it with `"role": "slave"` and its `node_id`, and `status` returns a `slave` object (node ID, NMT state, comm OK, SYNC count, EMCY code, error register and the PDO mappings in force, read from the dictionary). `sdo_read` and `sdo_write` with the slave's own node ID read and write its own dictionary (writes need `allow_changes`); every other operation answers that the network is a slave network.

## Simulated bus

With the adapter option `"simulate": true` ([simulator.md](simulator.md)), a slave network runs on the plugin's in-process simulated bus named by its `interface`, shared with a simulated master network of the same `interface` name. One config then runs the plugin's own master against its own slave, with no CAN adapter, vcan or privileges:

```json
{ "name": "plc", "adapter": { "type": "socketcan", "interface": "sim0", "bitrate": 250000, "simulate": true },
  "master": { "node_id": 1, "heartbeat_ms": 100 },
  "nodes": [ { "node_id": 10, "name": "openplc", "eds": "openplc-slave.eds", "simulate": false, ... } ] },
{ "name": "line", "role": "slave",
  "adapter": { "type": "socketcan", "interface": "sim0", "bitrate": 250000, "simulate": true },
  "slave": { "node_id": 10, "eds": "openplc-slave.eds", ... } }
```

A simulated bus takes at most one master network and one slave network. On the master, the node for the slave has `"simulate": false`: otherwise the simulator would run a simulated device with the same node ID next to the plugin's slave, and the check refuses it. Both networks log a warning that they are simulated. `test/slave/simulated.sh` runs this setup (a ctest).

## Limits

No master and slave on one real interface, no flying master, no MPDO or SRDO, no program download into OpenPLC, and no SDO client on a slave network. Strings and domains cannot be bound: PLC locations are 1 to 64 bits.
