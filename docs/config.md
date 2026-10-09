# canopen_config.json

The canworks plugin reads one JSON file, the config path given for the `canworks` entry in the runtime's `plugins.conf`. It describes the CAN adapter, the master, and every slave node with its EDS file, PDO entries and startup SDOs; a version 2 file can also make the PLC itself a [slave](#slave-networks) or a [gateway](#gateway), or run a [J1939](j1939.md) network. Each PDO entry is bound to one explicit PLC address; nothing is assigned automatically.

The format is a versioned contract: [`schema/canworks.v1.schema.json`](../schema/canworks.v1.schema.json) (JSON Schema 2020-12) describes `schema_version` 1, the file with one CAN network, and [`schema/canworks.v2.schema.json`](../schema/canworks.v2.schema.json) describes `schema_version` 2, the file with [several networks](#several-networks-schema_version-2). The plugin, the deploy tool ([docs/deploy.md](deploy.md)) and any future editor GUI read and write the same file. The deploy tool and the editor hook deliver it with each upload as `conf/canworks.json`, and the runtime points `plugins.conf` at it.

At every PLC start the plugin validates the file, runs `dcfgen`'s EDS lint on each node's EDS ([EDS lint](#eds-lint)), checks each entry against the node's EDS, and runs Lely's `dcfgen` on the device to produce the master DCF and one concise DCF per slave. The output goes to a `.canworks/` directory next to the config file and is reused while the config and EDS files are unchanged.

## Example (the Lely tutorial ping-pong slave)

This is [`config/pingpong/canopen_config.json`](../config/pingpong/canopen_config.json):

```json
{
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 125000 },
  "master": { "node_id": 1, "sync_period_us": 100000 },
  "nodes": [
    {
      "node_id": 2,
      "name": "pingpong",
      "eds": "cpp-slave.eds",
      "heartbeat_ms": 100,
      "heartbeat_timeout_ms": 300,
      "status_location": "%IX10.0",
      "tx_pdos": [
        { "entries": [ { "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID100" } ] }
      ],
      "rx_pdos": [
        { "entries": [ { "index": "0x4000", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%QD100" } ] }
      ],
      "sdo": [
        { "index": "0x1017", "subindex": 0, "type": "UNSIGNED16", "value": 100 }
      ]
    }
  ]
}
```

With the PLC program `%QD100 := %ID100 + 1`, the slave echoes every value back and the counter keeps increasing.

Check a file without starting the PLC:

```sh
canopen_check /etc/canworks/canopen_config.json
```

`canopen_check` runs the same validation, EDS checks and `dcfgen` step as the plugin and prints every problem it finds. It is built from `tools/` by the development build (see the README).

`canopen_check --dump-writes` also lists each node's configuration download in the order the plugin sends it, one `write <node> 0x<index> <sub> <bytes>` line per SDO write, then the boot steps that are not object writes (`step <node> restore <sub>`, `step <node> firmware <file>`). To get the same configuration as a CiA 306 DCF per node, see [Export the nodes as DCF files](deploy.md#export-the-nodes-as-dcf-files).

## Top level

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | no | The format version, default 1. A file with a higher version than the plugin supports is rejected with both versions named. |
| `adapter` | yes | The CAN adapter (below). |
| `master` | yes | The master's settings (below). |
| `nodes` | yes | The slave nodes (below), at least one. An empty list is allowed only together with [`master.diagnostics`](#online-diagnostics), as a scan-only config for commissioning. |

## Several networks (`schema_version` 2)

One PLC can drive up to 8 CAN networks, each on its own adapter, with its own master, bit rate, SYNC and nodes. A network with `"protocol": "j1939"` is a J1939 ECU instead of a CANopen master or slave, with a `j1939` object in place of `master` and `nodes` ([j1939.md](j1939.md)). A network with `"protocol": "none"` is a plain CAN network that carries only raw CAN messages, and any network can have a `raw` object with plain frames received into `%I` and sent from `%Q` ([raw-can.md](raw-can.md)). Such a file has `"schema_version": 2` and a `networks` list instead of the top-level `adapter`, `master` and `nodes`; [`config/two-networks`](../config/two-networks/canopen_config.json) is an example:

```json
{
  "schema_version": 2,
  "diagnostics": { "token_verifier": "SCRAM-SHA-256$4096:..." },
  "networks": [
    { "name": "io", "adapter": { "type": "socketcan", "interface": "can0", "bitrate": 125000 },
      "master": { "node_id": 1, "sync_period_us": 10000 }, "nodes": [ ... ] },
    { "name": "drives", "adapter": { "type": "socketcan", "interface": "can1", "bitrate": 500000 },
      "master": { "node_id": 1, "sync_period_us": 2000 }, "nodes": [ ... ] }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `networks` | yes | 1 to 8 networks. Each has `adapter`, `master` and `nodes` exactly as a version 1 file has them at the top level, and an optional `name`; a [slave network](#slave-networks) has `"role": "slave"` and `slave` instead of `master` and `nodes`, and a J1939 network has `"protocol": "j1939"` and `j1939` instead ([j1939.md](j1939.md)). |
| `networks[].protocol` | no | `"canopen"` (default) or `"j1939"`. A J1939 network has no `role`, `master`, `nodes` or `slave`. |
| `networks[].role` | no | `"master"` (default) or `"slave"`. CANopen networks only. |
| `networks[].name` | no | A letter, then letters, digits and `_`, at most 16 characters; names differ, ignoring case. Default: the adapter's `interface`, which then must be usable as a name. |
| `diagnostics` | no | [Online diagnostics](#online-diagnostics) for all networks together: one port and one token. In version 2 it sits at the top level, not in a network's `master`. |
| `gateway` | no | Routes between a slave network and the master networks ([gateway](#gateway)). |

Each network is checked as a version 1 file is: node IDs and COB-IDs need only be unique inside their network, so node 2 can exist on two networks. Across networks, two networks may not use the same `interface` or the same `slcan` `device`, and no two locations may overlap: all networks share the PLC's one I/O image. Messages name the network: `networks[1]: nodes[0]: ...`, and an overlap names both sides with their networks.

An error in any network rejects the whole file and no interface is opened. Once running, each network has its own bus thread: a network whose adapter fails or whose node is lost does not stop the others. With several networks every log line starts with the network's name (`[CANWORKS] drives: node 2 (pingpong) is operational`). In a version 2 file the generated files go to `.canworks/<name>/` instead of `.canworks/`. A version 2 file with one network otherwise behaves as a version 1 file. The PLC program's SDO function blocks pick the network with their `NETWORK` input: 0 for the first network in the list, 1 for the second, and so on ([plc-sdo.md](plc-sdo.md)).

A version 2 file needs the plugin and the deploy tool from the same release or later; an older plugin rejects it as a newer `schema_version`. Version 1 files load unchanged, and the configurator saves a config with one network as version 1.

Files written before the contract have top-level `interface` and `bitrate` instead of `adapter`. They still load, with the same meaning as before: a `socketcan` adapter with `configure_link: false`, so the plugin leaves the link as it finds it. The plugin logs a deprecation warning. A file with both `adapter` and a top-level `interface` or `bitrate` is rejected.

## Slave networks

A network with `"role": "slave"` makes the PLC a node of a network another master runs ([slave.md](slave.md)); [`config/slave`](../config/slave/canopen_config.json) is an example. It has `adapter` as any network, and a `slave` object instead of `master` and `nodes`:

```json
{ "name": "line", "role": "slave",
  "adapter": { "type": "socketcan", "interface": "can1", "bitrate": 250000 },
  "slave": { "node_id": 10, "eds": "openplc-slave.eds",
             "objects": [ { "index": "0x2000", "subindex": 1, "iec_location": "%IW300", "name": "speed_setpoint" } ] } }
```

| Field | Required | Meaning |
|---|---|---|
| `node_id` | yes | The slave's own node ID, 1-127, or `null` to start without one and wait for an LSS master to assign it. |
| `eds` | yes | The slave's EDS, relative to the config file: written by `canworks-deploy slave-eds` ([deploy.md](deploy.md#the-slave-eds)) or by hand. The other master imports the same file. |
| `eds_lint` | no | As [`master.eds_lint`](#eds-lint), for this EDS. A generated EDS passes `"all"`. |
| `objects[]` | no | Bindings: `index`, `subindex` and `iec_location` of an object of the EDS, and an optional `name` for its variable. The direction comes from the object's `AccessType`: `rww` and `rw` (the master writes) need an `%I` location, `ro` and `rwr` (the program writes) a `%Q` location; `const` and `wo` objects cannot be bound. The location's size must fit the object's type, as for PDO entries. |
| `inputs_on_loss` | no | `"hold"` (default): inputs keep their last value while the slave is not OPERATIONAL or the master's heartbeat is lost. `"zero"`: they read 0 then. |
| `state_location` | no | `%IB`: own NMT state (0 not started, 4 stopped, 5 operational, 127 pre-operational). |
| `comm_ok_location` | no | `%IX`: TRUE while OPERATIONAL with no heartbeat consumer or life guarding error. |
| `sync_count_location` | no | `%IW`: SYNCs received, wrapping at 65535. |
| `emcy_code_location` | no | `%QW`: a change to a non-zero code sends an EMCY with it, a change to 0 the error reset. |
| `error_register_location` | no | `%QB`: the error register sent with that EMCY. |

Everything else (PDO mapping, heartbeat, guarding, SYNC consumer, error behaviour) comes from the EDS, and the other master may change it over SDO. A slave network needs `schema_version` 2; a version 1 file with `role`, `slave`, `gateway`, `protocol` or `j1939` is rejected with a message that says so. Slave networks follow the rules of every network: their own interface, a name, and locations that overlap no other network's. With the device simulator's `"simulate": true` adapters, one master network and one slave network may share a simulated bus (the same `interface`).

## Gateway

A top-level `gateway` connects a slave network (the upper network) with the master networks of the same file: each route copies one value between a slave object and a field node's PDO entry, in the plugin, without the PLC program. Field node states, EMCYs and SDO access can be passed up too. Every field and the runtime behaviour: [gateway.md](gateway.md); [`config/gateway`](../config/gateway/canopen_config.json) is an example.

```json
"gateway": {
  "upper": "upper",
  "routes": [ { "name": "ping", "slave": { "index": "0x2000", "subindex": 1 },
                "field": { "network": "field", "node": 2, "index": "0x4000", "subindex": 0 } } ],
  "status": {}, "emcy_forward": true, "on_upper_loss": "zero", "sdo_bridge": true
}
```

A PDO entry that a route writes (an RPDO entry fed from the upper master) may leave out `iec_location`; every other PDO entry needs one. A route's target may not also have an output location: one writer per object.

## `adapter`

| Field | Required | Meaning |
|---|---|---|
| `type` | yes | The adapter backend: `socketcan` (an interface the system already has: CAN HAT, candleLight/gs_usb, PEAK, vcan) or `slcan` (a serial-line adapter such as a CANable with slcan firmware; see [slcan](#slcan-canable-lawicel-canusb)). Any other type leaves the plugin inactive with an error naming it. |
| `interface` | yes | SocketCAN interface, e.g. `can0` or `vcan0`. With `slcan`, the name the plugin gives the interface it creates. |
| `bitrate` | yes | Bus bit rate in bit/s: 10000, 20000, 50000, 125000, 250000, 500000, 800000 or 1000000. |
| `configure_link` | no | `socketcan` only. Default `true`: at PLC start the plugin sets the interface to `bitrate` and brings it up. A link that is already up at that rate is used as is; one up at another rate is taken down, set and brought up again, with a warning. A `vcan` link is only brought up. `false` leaves the link to the system, with a warning if its rate differs. |
| `restart_ms` | no | `socketcan` only. Bus-off auto-restart delay in ms, set together with the bit rate (`ip link ... restart-ms`). |
| `device` | `slcan` | `slcan` only. Absolute path of the serial device, such as `/dev/serial/by-id/usb-Openlight_Labs_CANable2_...-if00` (preferred: `/dev/ttyACM0` can change number when the adapter is plugged in again). |
| `simulate` | no | Default `false`. `true`: the network is simulated. The master runs on an in-process virtual bus with simulated devices; no interface or serial device is opened and no link is changed, so it needs no CAN hardware and no privileges. The other fields are still checked, so switching back needs only this one. Not allowed on a J1939 network, which uses a `vcan` interface for simulation instead. See [simulator.md](simulator.md#two-switches). |
| `serial_baudrate` | no | `slcan` only. UART speed for adapters behind a real serial port, such as the FTDI-based Lawicel CANUSB. USB adapters such as the CANable ignore it; left out, the speed is not changed. |

A field of the other type (`device` with `socketcan`, `configure_link` with `slcan`, ...) is an error, not ignored.

Changing the link needs `CAP_NET_ADMIN`; the runtime runs as root and has it. Without it the plugin logs an error naming the interface and the missing permission, every node reports not operational, the PLC keeps scanning, and the plugin retries every second, as for a missing interface. Link setup runs in the plugin's bus thread before the master opens the interface, and again on every retry.

### slcan (CANable, Lawicel CANUSB)

```json
"adapter": { "type": "slcan", "device": "/dev/serial/by-id/usb-Openlight_Labs_CANable2_...-if00", "interface": "can0", "bitrate": 500000 }
```

At PLC start the plugin creates the interface itself, as `slcand` would: it opens `device` for exclusive use in raw mode, attaches the kernel's slcan driver, renames the new `slcanN` interface to `interface`, sets `bitrate`, sets the transmit queue to 1000 frames (the driver's 10 overflows on SDO and PDO bursts) and brings it up. No `slcand`, `can-utils` or systemd unit is needed; disable one you set up before. The log names the device, interface and bit rate.

- **PLC stop:** the plugin takes the interface down and closes the device, so the interface no longer exists and the device is free.
- **Unplugged adapter:** the kernel removes the interface; nodes report not operational, the log says the serial device is missing, and once the adapter is back the plugin creates the interface again and the nodes boot, with no restart.
- **Name already taken:** if an interface named `interface` exists that the plugin did not create (typically from an old `slcand` service), the plugin leaves it alone, logs an error naming it, and retries; stopping the service is enough.
- **Linux before 6.0:** the slcan driver there takes no bit rate over netlink. The plugin logs that and retries; on such a kernel create the interface with `slcand -o -c -s6 /dev/ttyACM0 can0` and use `socketcan` with `configure_link: false`.
- **Bus diagnostics:** slcan firmware does not report the CAN error state. The bus state input reads 1 while the link is up and 0 when it is not, the error counters read 0, and with any bus diagnostic location set the plugin logs this once per PLC start. Node state bytes still drop to 0 when a node is lost, so key on those.

A CANable runs one of two firmwares. Check with `lsusb`:

| `lsusb` shows | Firmware | Use | Bus error state and counters |
|---|---|---|---|
| `16d0:117e` | slcan (stock) | `type: slcan` on its `/dev/serial/by-id/...` device | no |
| `1d50:606f` | candleLight (gs_usb) | `type: socketcan` on `can0`, `configure_link` on | yes |

Flashing candleLight (CANable updater, https://canable.io/updater/) turns the CANable into a native SocketCAN interface with real error-passive and bus-off states.

## `master`

| Field | Required | Meaning |
|---|---|---|
| `node_id` | yes | The master's node ID, 1-127. |
| `sync_period_us` | no | SYNC period in microseconds, for the master's own SYNC timer. Synchronous PDOs are exchanged on every SYNC. Left out or 0 without `"sync_source": "plc_cycle"`: the master produces no SYNC, and every configured PDO must be event-driven: a PDO whose transmission type, from `transmission` or else from the EDS, is 0-240 or 252 is rejected (set `"transmission": 254` or `255`), and so are `sync_window_us`, `sync_counter_overflow` and `sync_start`. Outputs are then sent as soon as they change (see [At runtime](#at-runtime)). Not allowed with `"sync_source": "plc_cycle"`. |
| `sync_source` | no | `"timer"` (default): SYNC every `sync_period_us`. `"plc_cycle"`: SYNC from the PLC cycle ([SYNC from the PLC cycle](#sync-from-the-plc-cycle)). |
| `sync_cycles` | no | With `"sync_source": "plc_cycle"`: one SYNC every this many PLC cycles, 1-1000 (default 1). |
| `heartbeat_ms` | no | Heartbeat the master produces (default 0, off). |
| `eds_lint` | no | Which `dcfgen` EDS lint findings stop the load: `"communication"` (default), `"all"` or `"off"` ([EDS lint](#eds-lint)). |
| `strict_eds` | no | Deprecated: `true` reads as `eds_lint: "all"`, `false` as `"off"`. Not together with `eds_lint`. |
| `bus_state_location` | no | An input byte (`%IB...`) with the CAN bus state (below). |
| `tx_error_count_location` | no | An input byte (`%IB...`) with the controller's transmit error counter, clamped to 255. |
| `rx_error_count_location` | no | An input byte (`%IB...`) with the controller's receive error counter, clamped to 255. |
| `bus_off_count_location` | no | An input word (`%IW...`) counting bus-off events since the PLC started; wraps at 65535. |
| `state_location` | no | An input byte (`%IB...`) with the master's own NMT state: 5 OPERATIONAL, 127 PRE-OPERATIONAL, 4 STOPPED. The master stays PRE-OPERATIONAL while a mandatory node is missing or with `start: false`, and no node exchanges PDOs then. |
| `diagnostics` | no | Turns on the diagnostics channel for the configurator's online view, its bus scan and `canworks-diag` (below, [Online diagnostics](#online-diagnostics)). Left out: the plugin opens no port. |

The master also takes every option `dcfgen` offers for it (below, [Master options](#master-options)).

### EDS lint

Many vendor EDS files break CiA 306 in objects nothing reads, most often a signed limit written as unsigned hex (`HighLimit=0xFF` on an INTEGER8). `dcfgen`'s own lint stops on every such finding, so the plugin runs the lint itself (the deploy tool's `canworks.edslint` module on Lely's `dcf` package, installed into `<prefix>/venv` by `install-stock.sh`) and decides by `eds_lint`:

| `eds_lint` | What stops the load |
|---|---|
| `"communication"` (default) | A finding in an object 0x1000-0x1FFF, which `dcfgen` reads and writes, that is not limit-only. |
| `"all"` | Any finding (what `strict_eds: true` did). |
| `"off"` | Nothing. |

A finding is limit-only when it is about a `LowLimit` or `HighLimit`, or about a `DefaultValue` or `ParameterValue` outside the object's own limits but inside its data type's range. Neither `dcfgen` nor the master enforces EDS limits; values the plugin writes are range-checked against the data type. Findings that do not stop the load are logged as one warning per EDS with their count and the first three. A load the lint stops logs an error naming the node, the EDS, each finding with its object, and the setting that would accept it. PDO-mapped objects keep the plugin's data type, access type and mappability checks in every mode. `dcfgen` itself always runs with `--no-strict`.

Before the lint, the plugin makes a prepared copy of an EDS that needs one, `.canworks/eds/node_<id>.eds`, which its EDS checks and `dcfgen` then read. The original file is left unchanged. The corrections are lossless:

- a file that is not valid UTF-8 is converted from CP1252;
- `0x200+$NODEID` is rewritten `$NODEID+0x200` (the CiA 306 form, the only one `dcfgen` parses);
- a REAL32 or REAL64 value written as a decimal number (`12.345`) is rewritten as Lely's hexadecimal bit pattern (`0x4145851F`);
- an OCTET_STRING or DOMAIN `DefaultValue` or `ParameterValue` that does not start with a hex digit (`----`) is cleared, since Lely reads these as hex and refuses the file otherwise. The master never writes these values.

The plugin logs one line per node that needed corrections, with each kind and its count, and each cleared value with its object and old text. The configurator and the deploy tool run the same lint and corrections, so the PC refuses what the PLC would refuse.

### Bus diagnostics

The four bus fields let the program tell a bus fault (cable, termination, bit rate, a babbling device) from one missing node. Each is optional on its own. The plugin reads the interface's CAN state, error counters and bus-off statistics over rtnetlink every 100 ms while the master runs. It does not need `CAP_NET_ADMIN` for this.

| Bus state | Meaning |
|---|---|
| 0 | No bus: the interface is missing, down, stopped, or the master is not running on it. Also the value before the plugin first runs. |
| 1 | Error-active: normal operation. A `vcan` interface that is up always reads 1. |
| 2 | Error-warning: an error counter reached 96. |
| 3 | Error-passive: an error counter reached 128. |
| 4 | Bus-off: the controller has stopped sending. |

The codes go up with severity, so `bus_state >= 3` means trouble.

- **A pulled cable reads 3, not 4.** With no other node to acknowledge its frames, the master's transmit error counter climbs to 128 and stops there, because acknowledgement errors no longer count once the controller is error-passive. The nodes then drop out one by one through their own heartbeat or guarding timeouts.
- **Without `adapter.restart_ms`, bus-off can last until something restarts the interface.** Whether it does depends on the adapter: many controllers wait for the kernel, while some USB adapters (gs_usb/candleLight firmware, for example) leave bus-off by themselves within milliseconds, so a wrong bit rate shows as a fast bus-off/error-passive/error-active cycle and a rising bus-off count. The plugin logs this. Set `restart_ms` (for example 100) so the kernel restarts controllers that wait.
- **The bus-off count catches short bus-offs.** It comes from the kernel's statistics, so a bus-off the kernel recovers from between two readings or two scans is still counted. A short error-warning or error-passive spell can be missed by the state byte; the counters and the log show the trend.
- **Some drivers report no error counters**, for example some SPI CAN controllers. The counter inputs then read 0, and the plugin logs this once when a counter location is configured. The state byte works with every SocketCAN driver.
- The counters keep their last value while the interface is missing or down; the state byte reads 0.

The plugin logs every state change: a warning on entering error-warning, error-passive or bus-off (an error line for bus-off), an info line on returning to error-active, and an error line for a bus-off the controller recovered from between two readings. When the state changes more than 5 times within one second, the rest of that second goes into one summary line.

### Master options

Each is optional. A setting left out keeps the value the plugin always used, or `dcfgen`'s default where the plugin had none. Times counted by CiA in 100 µs units are given in microseconds and must be a multiple of 100 (at most 6553500). Numbers may be integers or decimal or `0x` hex strings.

| Field | Object | Meaning |
|---|---|---|
| `vendor_id`, `product_code`, `revision_number`, `serial_number` | 0x1018 | The master's own identity. |
| `sync_window_us` | 0x1007 | Synchronous window length. Needs SYNC (`sync_period_us` or `"sync_source": "plc_cycle"`). |
| `sync_counter_overflow` | 0x1019 | 0 (no counter) or 2-240: SYNC then carries a counter, which a PDO's `sync_start` needs. Needs SYNC (`sync_period_us` or `"sync_source": "plc_cycle"`). |
| `time_cob_id` | 0x1012 | COB-ID of the master's TIME message, default 0x100. With `time_period_ms` the master sets the producer bit (bit 30) itself. |
| `time_period_ms` | 0x1012 bit 30 | 100-3600000. The master produces TIME: a CiA 301 TIME_OF_DAY from the runtime host's clock (UTC) on `time_cob_id` (or 0x100), sent at once when the bus comes up, again at once after the bus recovers, and then every `time_period_ms`. Left out, the master sends no TIME. The start-up log names the COB-ID, the period and the host's time, so a host without NTP or a real-time clock shows up there. Nodes use TIME only when their own 0x1012 has the consumer bit: set the node's `time_cob_id` to `0x80000100` (or `0x80000000` plus your COB-ID); the plugin warns when no configured node does. |
| `emcy_inhibit_time_us` | 0x1015 | Inhibit time of the master's own EMCY, multiple of 100. |
| `heartbeat_consumer` | 0x1016 | Default `true`: the master watches the nodes' heartbeats. `false` leaves 0x1016 empty, so a lost node is noticed only through guarding. |
| `heartbeat_multiplier` | | 1-100, default 3. A node with `heartbeat_consumer: true` times out the master's heartbeat after `heartbeat_ms` × this. |
| `error_behavior` | 0x1029 | An object of sub-index (as a string key, 1-254) to value: 0 pre-operational, 1 no change, 2 stopped, others manufacturer-specific. `{"1": 0}` |
| `nmt_inhibit_time_us` | 0x102A | Minimum gap between two NMT commands, multiple of 100. |
| `start` | 0x1F80 | Default `true`. `false` keeps the master PRE-OPERATIONAL: no PDOs move until something starts it. The plugin warns about this at load. |
| `start_nodes` | 0x1F80 | Default `true`. `false`: nodes are configured but stay PRE-OPERATIONAL (state byte 127). |
| `start_all_nodes` | 0x1F80 | Default `false`. `true`: one broadcast NMT start once all mandatory nodes have booted, instead of one per node. |
| `reset_all_nodes` | 0x1F80 | Default `false`. `true`: when a mandatory node is lost, every node is reset, the master included. |
| `stop_all_nodes` | 0x1F80 | Default `false`. `true`: when a mandatory node is lost, every node is stopped (state 4), the master included. Takes precedence over `reset_all_nodes`. |
| `boot_time_ms` | 0x1F89 | Time allowed for all mandatory nodes to boot; 0 or left out: no limit. |
| `sdo_timeout_ms` | | 10-60000, default 1000. How long the master waits for each SDO answer while it boots and configures a node: identity and program version reads, PDO and startup SDO downloads, `restore_configuration` and program download. Raise it for a device that answers late, for example one that saves each parameter to flash first or erases flash for a program download; a timeout shows as error status B or J, or as abort code 0x05040000 with "no answer within ... ms" in the log. Before this setting the timeout was Lely's 100 ms. SDO variables and diagnostics requests have their own timeouts. |

### Online diagnostics

```json
"diagnostics": { "token_verifier": "SCRAM-SHA-256$4096:b3BlbnBsYy1jYW5vcGVuLQ==$SCwajLpaZodu1wAN8vyPszAhAZJB4cXO6Rk+MpacSlQ=:7p7OTxtK+R6omxv8Fdz+xdCpEf4bc82kbkxCL8w33kg=", "allow_changes": false }
```

| Field | Required | Meaning |
|---|---|---|
| `token_verifier` | yes | The access token's SCRAM-SHA-256 verifier, `SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>` (iterations 4096-1000000, a salt of at least 16 bytes). The token itself never goes in the file, and the verifier does not let anyone log in: the configurator generates the token and keeps it on the PC, and `canworks-diag hash-token` prints the verifier of a token you choose. The former `token_sha256` is refused: set the token again ([diagnostics.md](diagnostics.md#security)). |
| `port` | no | TCP port the plugin listens on, 1024-65535, default 7531. |
| `bind` | no | IPv4 address to listen on, default `0.0.0.0` (every interface). |
| `allow_changes` | no | Default `false`: read-only. `true` also allows SDO writes and NMT commands from a client with the token. |

The plugin listens while the PLC runs and closes the port when it stops. Everything a client sees and does is in [diagnostics.md](diagnostics.md), together with the security notes. With `"nodes": []` the plugin starts the master on the bus with no slaves, so the scan can find what is connected before any node is configured.

### Simulated network and devices

The two `simulate` switches give four combinations: everything simulated (`adapter.simulate: true`), a simulated network with some nodes absent (`"simulate": false` on them), some simulated devices next to real ones on a real network (`"simulate": true` on them), and every node simulated on a real interface. Behaviour of the simulated devices (moving values, faults, scenarios) comes from `simulation.json` next to the config. The plugin logs a warning naming what is simulated at every PLC start, and the diagnostics status reports `simulated_network` and each node's `simulated`. [simulator.md](simulator.md) has the details.

## `nodes[]`

| Field | Required | Meaning |
|---|---|---|
| `node_id` | yes | 1-127, unique, not the master's ID. |
| `name` | no | Used in log messages. |
| `eds` | yes | EDS file (CiA 306). A relative path is looked up next to the config file first, then in the runtime's `core/generated/conf/`, where a stock runtime extracts the uploaded `conf/` tree (the deploy tool puts EDS files under `conf/canworks/eds/`). The plugin logs the path it used. |
| `heartbeat_ms` | no | Heartbeat period the slave is configured to produce; 0 switches its heartbeat off. Left out, the slave keeps the period its EDS gives (object 0x1017) and nothing is written. The master reports the node lost when no heartbeat arrives within `heartbeat_timeout_ms`. |
| `heartbeat_timeout_ms` | no | Default 3 × `heartbeat_ms`, or 3 × the EDS heartbeat period when `heartbeat_ms` is left out. |
| `guard_time_ms`, `life_time_factor` | no | Node guarding instead of heartbeat. Give both, and not together with `heartbeat_ms`. |
| `status_location` | no | An input bit (`%IX...`) that is TRUE while the node and the master are both OPERATIONAL, which is when PDOs flow, and FALSE otherwise. |
| `state_location` | no | An input byte (`%IB...`) with the node's NMT state: 5 OPERATIONAL, 127 PRE-OPERATIONAL, 4 STOPPED, 0 no contact (never heard from, lost, being reset, or not answering the master's boot retries). It follows heartbeat or node-guarding messages, so without supervision it only changes at boot and when the node is lost. |
| `boot_error_location` | no | An input byte (`%IB...`) with the reason the node's last boot failed (below), 0 once it is OPERATIONAL. |
| `emcy_code_location` | no | An input word (`%IW...`) with the error code of the node's latest emergency message (see [Emergency messages](#emergency-messages)). |
| `error_register_location` | no | An input byte (`%IB...`) with the error register from the node's latest emergency message. |
| `nmt_command_location` | no | An output byte (`%QB...`) through which the program sends NMT commands to the node (see [NMT commands from the program](#nmt-commands-from-the-program)). |
| `tx_pdos` | no* | PDOs the slave transmits (its TPDOs). Their entries land in inputs (`%I...`). |
| `rx_pdos` | no* | PDOs the slave receives (its RPDOs). Their entries are fed from outputs (`%Q...`). |
| `sdo` | no | Startup SDOs (below). |
| `sdo_variables` | no | Objects read or written over SDO while the network runs (see [SDO variables](#sdo-variables)). |
| `simulate` | no | `true`: the plugin runs a simulated device for this node, built from its EDS, node ID, identity and LSS settings. Default: `adapter.simulate`. With `true` on a real network the simulated device runs next to the real devices on the same interface; with `false` on a simulated network the node is absent. See [simulator.md](simulator.md#two-switches). |

\* Both may be left out: a node with no PDOs is still booted, supervised and sent its startup SDOs, and all its PDOs are switched off. `tx_pdos` and `rx_pdos` are named from the slave's point of view, as in its EDS.

At boot the master writes the node's PDO communication and mapping parameters over SDO so that they match this file. The slave's own PDOs that the file does not list are switched off.

### Node options

Each is optional. The first group lives only in the master (0x1F81 and the expected identity) and keeps the plugin's earlier behaviour when left out. The second group is written to the node, and a field left out writes nothing, so the node keeps its EDS value.

| Field | Where | Meaning |
|---|---|---|
| `mandatory` | master 0x1F81 | Default `false`. `true`: the master stays PRE-OPERATIONAL until this node has booted (see [Mandatory nodes](#mandatory-nodes)). |
| `boot` | master 0x1F81 | Default `true`. `false`: the master neither configures nor starts the node and does not retry it; it only watches its heartbeat or guarding. Its PDOs still move while the node is OPERATIONAL. |
| `reset_communication` | master 0x1F81 | Default `true`: the master sends NMT reset communication before booting the node. |
| `retry_factor` | master 0x1F81 | Node guarding retries. Default `life_time_factor` (0 without guarding). |
| `revision_number` | master 0x1F87 | Expected revision (0x1018 sub 3). Default: the EDS value. `0` switches the check off. |
| `serial_number` | master 0x1F88 | Expected serial number (0x1018 sub 4), to pin one physical device. Left out: not checked. |
| `software_file`, `software_version` | master 0x1F58, 0x1F55 | Program download, see [Program download](#program-download). |
| `axis` | PLC program | Marks the node as a CiA 402 drive used as a PLCopen axis; see [CiA 402 axis](#cia-402-axis). The plugin itself does nothing different. |
| `lss` | master (LSS) | `{"assign": true}` gives the device its node ID over the bus by its serial number, `"store": true` also saves it in the device; see [LSS](#lss). Left out: no LSS. |
| `heartbeat_consumer` | node 0x1016 | `true`: the node watches the master's heartbeat with timeout `master.heartbeat_ms` × `master.heartbeat_multiplier`; needs `master.heartbeat_ms` above 0. `false`: the node's entry is cleared. Left out: the EDS entries stay. |
| `time_cob_id` | node 0x1012 | COB-ID of TIME; bit 31 (`0x80000000`) set makes the node consume TIME. Written only when it differs from the EDS value. |
| `error_behavior` | node 0x1029 | As the master's `error_behavior`. |
| `restore_configuration` | node 0x1011 | Sub-index the master restores before configuring the node (1 all, 2 communication, 3 application, as the device supports). |
| `config_check` | node 0x1020, master 0x1F26, 0x1F27 | Default `false`. `true`: skip the configuration download when the node already has this configuration, see [Configuration check](#configuration-check). |
| `store_configuration` | node 0x1010 | Sub-index of 0x1010 (1-127; 1 is usually all parameters) the master writes "save" to after a download. Needs `config_check`. Left out: the master never writes 0x1010. |

Vendor ID and product code are always checked against the EDS; `dcfgen` has no switch for them.

These fields write the same objects a startup SDO could. A startup SDO runs last and wins; the plugin and the deploy tool warn about the overlap.

**Change from earlier releases:** `dcfgen` cleared a node's 0x1016 entry that watched the master when the config said nothing about it. The plugin now drops that write, so a node whose EDS watches the master keeps doing so. Set `heartbeat_consumer: false` to clear it.

`dcfgen` 2.4.2 never writes a node's `time_cob_id` (a typo in its code compares against a fixed 0x100), so the plugin writes 0x1012 itself after the configuration `dcfgen` generated, and warns when the EDS has no 0x1012. `dcfgen`'s own warnings are logged as warnings with the node named.

### Configuration check

Without `config_check` the master downloads a node's whole configuration (PDO parameters, heartbeat, startup SDOs and the rest) at every boot. With `"config_check": true` it does that once:

1. After the last configuration write, the master writes a stamp of the configuration to the node's 0x1020 sub 1 (configuration date) and sub 2 (configuration time).
2. At every later boot it reads 0x1020 first. When both values equal the stamp, it downloads nothing (no `restore_configuration` either) and starts the node; the log says `node 2 (pingpong): configuration unchanged (0x1020 matches), nothing downloaded`. A node that is already OPERATIONAL with the stamp (the PLC runtime restarted while the device kept running) counts as configured and running and is not reset.
3. When they differ, the master downloads as usual and writes the new stamp.

The stamp is a hash of what is downloaded to that node, not a real date: 0x1020 shows values that look like nonsense dates in vendor tools. It changes when anything downloaded to the node changes (a PDO, a heartbeat, a startup SDO, `store_configuration`), and stays the same for edits that only concern other nodes or the master. A plugin update that changes how the configuration is written causes one extra download per node.

The node keeps 0x1020 only as long as it keeps its other parameters. With `store_configuration` the master writes the CiA 301 signature "save" (0x65766173) to that 0x1010 sub-index after the stamp, so the device saves the parameters and 0x1020 together to its non-volatile memory. It saves only after a download, never at a boot that skipped one, so the memory is written only when the configuration changed; that is also why `store_configuration` is rejected without `config_check`. Saving is never automatic: without `store_configuration` the master does not write 0x1010, and a power-cycled device comes back with its EDS defaults and 0x1020 = 0, so it is configured again. A device that aborts the save fails its boot with error status J, like any refused download.

Caveats:

- A device that saves 0x1020 but not all the parameters it was sent (check its manual for what 0x1010 sub 1 covers) comes back from a power cycle with a matching stamp but other settings; the master cannot see that. Try a power cycle once per device type before relying on it.
- Changes made on the device by hand (a vendor tool, an SDO from the diagnostics channel) are not noticed. To force a download at the next boot, write 0 to the node's 0x1020 sub 1, or turn `config_check` off for one start.
- Saving to flash can take longer than the boot SDO timeout; raise [`master.sdo_timeout_ms`](#master-options) if the save aborts with 0x05040000.

The node's EDS must define 0x1020 sub 1 and sub 2 as writable UNSIGNED32, and the `store_configuration` sub-index of 0x1010 as writable; the plugin and the deploy tool reject the config otherwise.

### LSS

Devices without DIP switches or a display get their node ID over the bus with LSS (CiA 305), addressed by their identity: vendor ID, product code, revision and serial number (0x1018 sub 1-4). With

```json
{ "node_id": 12, "name": "valve", "eds": "valve.eds", "serial_number": "0x00001234", "lss": { "assign": true } }
```

the master gives the device with that serial number node ID 12 every time it starts, before any node boots:

1. It addresses the device with the node's vendor ID and product code (from the EDS), its `revision_number` and its `serial_number`. With `revision_number` left out it tries the EDS revision first and then searches all revisions with LSS slowscan, so a firmware update does not stop the assignment; that search adds up to a second or so.
2. It asks the device for its node ID. When it is already 12 nothing is written, and the log says `node 12 (valve): LSS: the device already has node ID 12`.
3. Otherwise it sets node ID 12 and logs `node 12 (valve): LSS assigned node ID 12 (previous: none)`, then the network starts as usual: the communication reset the master sends to all nodes makes the new ID active, and the identity check of the boot confirms the device.
4. A device that does not answer is logged (`node 12 (valve): no device with vendor ID ..., product code ..., serial number 0x00001234 answered LSS`); the other nodes start, and node 12 fails its boot and is retried like any missing node.

`lss.store` (default `false`) also saves the node ID in the device's non-volatile memory with LSS "store configuration", so the device keeps it across power cycles even without the master. As with `store_configuration`, saving is never automatic: without `store` nothing is saved, and with it the master saves only when it had to change the ID, so a normal restart writes nothing to the device's memory. A device that refuses to save is logged as a warning and still runs with the new ID until it is powered off.

**Boot retries.** When a node with `lss.assign` is lost or missing (for example a device that power-cycled and came back without a node ID, or a replaced device), the master searches for it again before each boot retry, one node at a time, at most as often as the retry backoff allows (1 to 16 seconds). A device that comes back without a node ID starts with the assigned one at once. A device that answers with **another** valid node ID gets the new ID pending, but keeps its old one until it is reset or power-cycled: the master sends no NMT command to the old ID, which may belong to another device, and logs `node 12 (valve): LSS assigned node ID 12; the device keeps node ID 5 until it is reset or power-cycled`. Power-cycle the device to finish.

Rules, checked by the plugin and the deploy tool:

- `lss.assign` needs `serial_number`; vendor ID and product code always come from the EDS.
- `lss.store` needs `lss.assign`.
- `lss.assign` cannot go with `reset_communication: false`: the new node ID becomes active only at a communication reset.
- Two nodes cannot have the same LSS address (same EDS vendor ID and product code and the same serial number, unless both set different `revision_number` values).
- An EDS that does not say `LSS_Supported=1` gives a warning, not an error: many EDS files leave it out although the device supports LSS.

Without any node with `lss` and without diagnostics changes the master sends no LSS frame at all. To set the node ID or bit rate of a device by hand (commissioning, or a device that is not in the config yet), use the configurator's online view or `canworks-diag lss-...` ([diagnostics.md](diagnostics.md#what-it-offers)). Changing one device's bit rate takes effect at its next power cycle; set `adapter.bitrate` to match once all devices are set.

### CiA 402 axis

`axis` makes the node a PLCopen axis for the editor's motion blocks (`MC_Power`, `MC_MoveAbsolute`, ...), named after the node. The project generator declares the axis and calls the editor's CiA 402 drive bridge with the node's mapped standard objects (0x6040, 0x6041, 0x6060, 0x6061, 0x6064, 0x606C, 0x607A, 0x6081, 0x60FF, 0x6071, 0x6077); the plugin only accepts the field.

```json
"axis": { "scale_numerator": 1, "scale_denominator": 1, "scale_factor": 1.0 }
```

| Field | Meaning |
|---|---|
| `scale_numerator` | Drive increments for `scale_denominator` position units, -2147483648 to 2147483647 except 0. Default 1. |
| `scale_denominator` | 1 to 4294967295. Default 1. |
| `scale_factor` | The library's extra factor, any number but 0. Default 1.0. |
| `cyclic` | `true`: the program drives the axis in the cyclic synchronous modes (CSP 8, CSV 9, CST 10) with the `CO402_Cyclic*` blocks. Default `false`. |
| `interpolation_period_us` | With `cyclic`: the interpolation time period the plugin writes to the drive's 0x60C2 instead of the SYNC period, 100 to 255000. It must be 1-255 times 1 ms, 100 us, 10 us or 1 us. |

An axis node needs `status_location` and 0x6040 in an RPDO and 0x6041 in a TPDO, each with a location; the deploy tool and the configurator check this and the other standard objects' directions and types. See [cia402.md](cia402.md).

A **cyclic** axis also needs SYNC from the PLC cycle with one SYNC per cycle (`"sync_source": "plc_cycle"`, `sync_cycles` 1), 0x6060 and at least one set-point (0x607A, 0x60FF or 0x6071) mapped, and synchronous RPDOs (transmission type 0-240, the config's or else the EDS's) for the controlword, the mode and the set-points. The checks warn when the position or velocity feedback comes in a TPDO that is not synchronous, when the EDS has no 0x60C2 or 0x6065, and when its 0x6502 does not list the mode a mapped set-point needs. During node configuration the plugin writes 0x60C2 (sub 1 the value, sub 2 the exponent) from `interpolation_period_us` or the SYNC period, unless a startup SDO writes 0x60C2 or the EDS has none. See [cia402.md](cia402.md#cyclic-synchronous-modes).

### Mandatory nodes

With `mandatory: true` on any node the master does not go OPERATIONAL until every mandatory node has booted, so **no node exchanges PDOs** before that, also the optional ones that are up. The plugin logs a missing mandatory node as an error naming it as the reason the network is held, the master state byte reads 127, and every status bit is FALSE. The PLC keeps scanning. Once the last mandatory node boots, the plugin starts the master and logs "all mandatory nodes have booted: starting the master".

When a mandatory node is lost later, the master resets that node (default), stops every node including itself (`stop_all_nodes`), or resets every node including itself (`reset_all_nodes`). An optional node that is lost is always reset on its own.

### Identity check and boot error byte

When a node's identity does not match, the plugin reads the node's 0x1018 and logs one line per wrong device, for example `node 5 (rtd): wrong device: product code 1029 (0x00000405), expected 1028 (0x00000404) from rtd8.eds`. It keeps retrying quietly, without resetting the node, and logs again only when another device answers. The right device then boots normally.

`boot_error_location` holds the CiA 302 error status letter as its ASCII code:

| Byte | Letter | Meaning |
|---|---|---|
| 0 | | Booted, or not tried yet. |
| 66 | B | No answer. |
| 68 | D | Wrong vendor ID. |
| 74 | J | A configuration download was refused. |
| 77 | M | Wrong product code. |
| 78 | N | Wrong revision. |
| 79 | O | Wrong serial number. |

Other letters come as Lely reports them; the log uses the same letters.

### Program download

With `software_file` and `software_version`, the master compares the node's program version (0x1F56 sub 1) with `software_version` at boot. When they differ it stops the node's program (0x1F51), downloads the file into 0x1F50 by SDO block transfer, starts the program again and checks the version once more. A node that still reports another version fails its boot. Without `software_version` the master never downloads, and the plugin warns.

`software_file` is resolved like `eds`: next to the config file, then in the runtime's `core/generated/conf/`. The deploy tool ships it under `conf/canworks/fw/`. The editor's project upload sends project files as text and would corrupt a binary file, so the deploy tool refuses to copy a binary program into an editor project and the editor-upload hook refuses one that arrived corrupted: deploy a program file with `canworks-deploy --runtime`.

## PDOs

A field left out keeps the slave's own value from its EDS: the master only writes what the config sets, plus the PDO mapping and COB-IDs. Before this, a left-out transmission type meant 1 and a left-out `heartbeat_ms` meant 0; set them explicitly to keep that behaviour.

Each communication field that is set (`cob_id`, `transmission`, `inhibit_time_us`, `event_timer_ms`, `sync_start`) is checked against the node's EDS: its sub-index of the PDO's communication object (0x1800+*n*-1 or 0x1400+*n*-1) must exist and be writable. A read-only sub-index is accepted only when the value equals the EDS value, because then nothing is written. A device that fixes its RPDO transmission type at 255, for example, is refused `"transmission": 1` when the config is loaded or saved, instead of failing boot with error status J.

| Field | Required | Meaning |
|---|---|---|
| `number` | no | PDO number on the slave, 1-512 (TPDO *n* is object 0x1800+*n*-1, RPDO *n* is 0x1400+*n*-1). Defaults to the position in the list. |
| `cob_id` | no | 11-bit COB-ID, or `"auto"`. Defaults to the CiA 301 value for PDOs 1-4 (TPDO: 0x180/0x280/0x380/0x480 + node ID, RPDO: 0x200/0x300/0x400/0x500 + node ID). Higher numbers need a COB-ID or `"auto"`, which picks the highest COB-ID in 0x181-0x57F that is outside every configured node's predefined set and not used by another PDO, in file order; the plugin logs the one it picked. |
| `transmission` | no | Transmission type, 0-240 (synchronous) or 254/255 (event-driven). Left out, the slave keeps the transmission type its EDS gives and nothing is written, so a device whose transmission type is fixed still boots. Given, it is always written, also when it equals the EDS default, because a device can run with another value than its EDS says. The same holds for `inhibit_time_us`, `event_timer_ms` and `sync_start`. |
| `inhibit_time_us` | no | TPDOs only. Minimum time between two sends of the PDO, in µs, a multiple of 100 (sub-index 3, which counts 100 µs). |
| `event_timer_ms` | no | Sub-index 5. On a TPDO, the event timer: with an event-driven type the slave sends at least this often. On an RPDO, the deadline: the slave signals an error (usually an EMCY) when the PDO has not arrived within this time. 0 switches it off. |
| `sync_start` | no | TPDOs only, with a synchronous transmission type (1-240, set here or in the EDS). The SYNC counter value at which the slave sends the PDO the first time (sub-index 6); it needs a SYNC counter on the master. |
| `timeout_ms` | no | TPDOs only. Receive timeout in ms, 1-65535, or `"auto"` (two times the PDO's event timer). The master flags the PDO when none has arrived for this long while its node is up; see [Receive timeout](#receive-timeout). Left out: no timeout. |
| `on_timeout` | no | TPDOs with `timeout_ms` only. What the PDO's inputs read while it is timed out: `"hold"` (default) keeps the last values, `"zero"` sets them to 0 until the PDO arrives again. |
| `timeout_location` | no | TPDOs with `timeout_ms` only. An `%IX` input bit, TRUE while the PDO is timed out. |
| `mapping` | no | Who sets the PDO's mapping: `"config"`, the master writes it from `entries`; or `"device"`, nothing is written and the node keeps the default mapping from its EDS (see below). Left out: `"device"` when the EDS makes the mapping read-only, else `"config"`. |
| `entries` | yes | The mapped objects, in PDO order, at most 64 bits in total. With the device mapping: the objects of it the PLC uses, in any order. |

### Receive timeout

A node can stay operational, with a working heartbeat, while one of its input PDOs stops coming: a sensor fault, a remapped COB-ID, a node that only sends on change and has gone quiet. The node status bit does not show this. `timeout_ms` on a TPDO makes the master watch it: the plugin writes the time as the deadline (sub-index 5) of the master's own RPDO for that COB-ID in the master DCF, and Lely reports when it expires.

- A PDO counts as timed out when, while its node is up, no PDO has arrived for `timeout_ms`, also when none arrived at all after the node came up. The next PDO ends the timeout. While the node is down nothing times out and the timeout bit is FALSE; the node status bit covers that case.
- Each timeout logs one warning (`node 2 TPDO 1: no PDO for 200 ms (timeout_ms); its inputs keep their last values`) and is counted; when the PDO is back, one line says how long it was missing.
- A timeout does not change the node's status bit, state byte, outputs or boot.
- `"auto"` uses `event_timer_ms` when the config sets it, else the event timer from the EDS (0x1800+*n*-1 sub-index 5), so the slave sends at least once per event timer and the master waits for two. It is rejected when that event timer is 0 or missing; give milliseconds then.
- Pick a value above the longest normal gap between two PDOs: two or three times the event timer, or for a synchronous PDO a few SYNC periods. The deploy tool warns when a number is below the event timer, because then the PDO times out between two sends.
- A PDO shorter than its mapping is logged once (until a PDO of the right length arrives) and does not change the inputs.

```json
"tx_pdos": [
  {
    "event_timer_ms": 100,
    "timeout_ms": "auto",
    "on_timeout": "zero",
    "timeout_location": "%IX20.0",
    "entries": [{ "index": "0x6401", "subindex": 1, "type": "INTEGER16", "iec_location": "%IW100" }]
  }
]
```

Here the slave sends TPDO 1 at least every 100 ms; after 200 ms without it `%IX20.0` goes TRUE and `%IW100` reads 0 until the PDO is back. `canworks-diag status` and the configurator's online view show the timed-out PDOs and their counts (see [diagnostics](diagnostics.md)).

### Devices with a fixed PDO mapping

Many simple I/O modules, and some drives, cannot change their PDO mapping: their EDS marks the mapping object (0x1600+*n*-1 or 0x1A00+*n*-1) `ro` or `const`. The plugin then uses the device mapping by itself: it writes no mapping, and the master packs and unpacks the PDO with the default mapping the EDS gives (`DefaultValue` of sub-index 0 and of each mapped sub-index). `"mapping": "device"` does the same for a PDO whose mapping the EDS lets the master write, for a device that refuses the change anyway or to keep its mapping as it is.

With the device mapping, `entries` lists only the objects of that mapping the PLC uses, each with its location; order does not matter. Objects the config leaves out, dummy gaps included, still travel in the PDO but are not exchanged with the PLC. In an RPDO (PLC to node) they go out as 0, and the plugin warns about them at load. The plugin logs each device-mapped PDO with its mapping when it loads.

The config is refused at load when `"mapping": "config"` is set on a fixed mapping, when an entry is not in the default mapping (the error lists it) or its type has another size there, or when the EDS gives no default mapping for a device-mapped PDO.

Such devices usually fix the COB-ID and transmission type too. The plugin never writes a PDO communication sub-index the EDS marks read-only: dcfgen's switch-off and switch-on of the COB-ID while configuring a PDO is left out for them. The COB-ID the plugin uses, set in `cob_id` or the CiA 301 default when left out, must then equal the EDS value; a device with TPDO 2 on 0x380 + node ID, for example, needs `"cob_id"` set to that. A PDO the config does not use and whose COB-ID is read-only is not switched off but left as the device has it (the plugin logs this); the master ignores its frames.

```json
"tx_pdos": [ { "entries": [ { "index": "0x6000", "subindex": 2, "type": "UNSIGNED8", "iec_location": "%IB40" } ] } ],
"rx_pdos": [ { "entries": [ { "index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB40" } ] } ]
```

For a module whose TPDO 1 maps 0x6000:1 and 0x6000:2 and whose RPDO 1 maps 0x6200:1 and 0x6200:2, all read-only, this uses the second input byte and the first output byte; the second output byte goes out as 0.

## PDO entries

| Field | Required | Meaning |
|---|---|---|
| `index` | yes | Object index, as a number or a string (`"0x6000"`). |
| `subindex` | no | Default 0. |
| `type` | yes | `BOOLEAN`, `INTEGER8`, `INTEGER16`, `INTEGER32`, `INTEGER64`, `UNSIGNED8`, `UNSIGNED16`, `UNSIGNED32`, `UNSIGNED64`, `REAL32` or `REAL64`. It must equal the object's `DataType` in the EDS. |
| `iec_location` | yes | The PLC address. |

The type must fit the location exactly:

| Location | Types |
|---|---|
| `%IX` / `%QX` (bit, e.g. `%IX2.3`) | `BOOLEAN` |
| `%IB` / `%QB` | `INTEGER8`, `UNSIGNED8` |
| `%IW` / `%QW` | `INTEGER16`, `UNSIGNED16` |
| `%ID` / `%QD` | `INTEGER32`, `UNSIGNED32`, `REAL32` |
| `%IL` / `%QL` | `INTEGER64`, `UNSIGNED64`, `REAL64` |

Values are copied bit for bit. Signed and floating-point objects therefore keep their bit pattern in the unsigned PLC location, and the program interprets them.

The object's `AccessType` in the EDS must allow the direction: a `tx_pdos` entry (the slave sends it) needs `ro`, `rw`, `rwr` or `const`; an `rx_pdos` entry (the master writes it) needs `wo`, `rw` or `rww`.

## Startup SDOs

Each node may list object writes the master sends while it configures the node: after the PDO communication and mapping parameters, before NMT start, in list order.

| Field | Required | Meaning |
|---|---|---|
| `index` | yes | Object index, as a number or a string (`"0x1017"`). |
| `subindex` | no | Default 0. |
| `type` | yes | One of the PDO entry types. It must equal the object's `DataType` in the EDS, and the object's `AccessType` must be writable (`wo`, `rw`, `rwr` or `rww`). |
| `value` | yes | A JSON number (`true`/`false` also work for `BOOLEAN`), or an integer as a decimal or `0x` hex string, which keeps 64-bit values exact. It must fit the type: `UNSIGNED8` takes 0-255, `INTEGER8` -128-127, and so on. |

A startup SDO runs after everything the plugin writes from the node's settings, so one that writes a PDO parameter (0x1400-0x1BFF), the heartbeat time (0x1017, with `heartbeat_ms` set to another value) or the guarding parameters (0x100C/0x100D) overrides that setting. The plugin and the deploy tool warn about it but accept the file.

A slave that aborts a startup SDO is handled like any configuration SDO: the plugin logs the node ID, index, subindex and abort code, and that node stays not operational while the others run.

Many devices only accept some settings while PRE-OPERATIONAL. A node that comes back after a pulled cable or a lost heartbeat is often still OPERATIONAL, so when a configuration download fails (CiA 302 error status J) the master resets the node (NMT reset node) before the next retry and configures it again from PRE-OPERATIONAL. The retries back off up to 16 s, so a download that the device always refuses resets it at most that often. After the master starts a node, the node's heartbeat must say OPERATIONAL within two of the master's heartbeat consumer periods for it (plus 100 ms). A node that falls back to PRE-OPERATIONAL before its first heartbeat after the start is otherwise never noticed, because its heartbeat state does not change, so the master logs `node 10 (openplc) did not report OPERATIONAL in its heartbeat after the start command; booting it again` and boots it again.

## SDO variables

An SDO variable ties one object of a node to one PLC location while the network runs, so the program can read or change parameters that are not in a PDO.

```json
"sdo_variables": [
  { "name": "serial", "index": "0x1018", "subindex": 4, "type": "UNSIGNED32",
    "direction": "read", "iec_location": "%ID200" },
  { "name": "setpoint", "index": "0x2020", "subindex": 1, "type": "UNSIGNED16",
    "direction": "write", "iec_location": "%QW200",
    "status_location": "%IB200", "abort_code_location": "%ID201" }
]
```

| Field | Required | Meaning |
|---|---|---|
| `name` | no | Used in log messages and by the configurator for variable names. |
| `index`, `subindex` | yes, no | The object, as for startup SDOs. `subindex` defaults to 0. |
| `type` | yes | One of the PDO entry types; must equal the object's `DataType` in the EDS. |
| `direction` | yes | `read` (node to PLC, an input location) or `write` (PLC to node, an output location). A read needs an `AccessType` of `ro`, `rw`, `rwr`, `rww` or `const`; a write needs `wo`, `rw`, `rwr` or `rww`. |
| `iec_location` | yes | The value, sized for the type by the same rules as PDO entries. |
| `period_ms` | no | Read entries only, 10 or more: also read the object this often while the node is available. |
| `trigger_location` | no | An output bit (`%QX...`). Each rising edge sends one transfer. |
| `status_location` | no | An input byte (`%IB...`) with the state of the latest transfer (below). |
| `abort_code_location` | no | An input double word (`%ID...`) with the CiA 301 abort code of the latest aborted transfer, 0 after a successful one. |
| `timeout_ms` | no | 10-60000, default 1000. A transfer without an answer by then is aborted with 0x05040000. |

**Reads** happen once after each boot of the node, every `period_ms` when it is given, and once on each rising edge of the trigger. The value appears by the next scan. The location reads 0 until the first successful read and keeps its value when a read fails or the node is lost.

**Writes** come in two kinds:

- *Owned* (no `trigger_location`): the program owns the object. The master writes the location's value after each boot of the node, and again whenever it differs from the last value written in that boot. When the value changes several times while a write is running, only the newest is written next. A value the node refuses is not retried until it changes or the node boots again.
- *Triggered* (with `trigger_location`): the value of the scan in which the trigger rises is written once; nothing else is written.

Nothing is written before the program's first scan, but an owned write sends whatever the location holds after that scan. An output the program has not set yet reads 0, so give an owned value its initial value in the declaration (`setpoint AT %QW200 : UINT := 500;`), or use a trigger when 0 is not a safe value for the device.

The **status byte** reads:

| Value | Meaning |
|---|---|
| 0 | no transfer yet |
| 1 | transfer running |
| 2 | done |
| 3 | aborted; the abort code says why (0x06090030 value range exceeded, 0x06010002 read-only, 0x05040000 timeout, ...) |
| 4 | node not available |

A node is available when the master has booted it and it is OPERATIONAL or PRE-OPERATIONAL. While it is not (not booted yet, lost, booting, or STOPPED), nothing is sent: owned writes and reads wait and go out once the node is back, with the status at 4 meanwhile, and a trigger edge is dropped with the status at 4. Each abort is logged once per entry and code, until a transfer of that entry succeeds:

```
node 23 (valve): SDO variable 0x2020:1 (setpoint): write aborted, abort code 0x06090030 (Value range of parameter exceeded)
```

Transfers do not change the node's NMT state, status bit or state byte.

Writing an object the plugin configures itself (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80) is accepted with a warning, because the program can then override that setting until the node boots again.

**Bus load.** The master runs one SDO transfer per node at a time, picking a triggered transfer first, then an owned write, then a read after boot, then a periodic read. Each transfer is two CAN frames for up to 4 bytes. A few periodic reads per node at 100 ms or slower hardly load a 500 kbit/s bus; for values that change every scan, map them in a PDO instead. Requests are picked up every 10 ms and at each SYNC (when the master produces SYNC).

## NMT commands from the program

With `nmt_command_location` the program commands the node through an output byte, using the CiA 301 command codes:

| Value | Effect |
|---|---|
| 0 or 1 | Run: the master starts the node and keeps it OPERATIONAL as usual. Going from a hold back to 0 or 1 sends NMT START. For a node with `boot: false`, a change to 1 sends NMT START. |
| 2 | Keep the node STOPPED: the master sends NMT STOP, and sends it again after every boot of the node. |
| 128 | Keep the node PRE-OPERATIONAL: the master sends NMT ENTER PRE-OPERATIONAL, again after every boot. PDOs stop, SDO variables still work. |
| 129 | Reset the node once when the byte changes to 129. |
| 130 | Reset the node's communication once when the byte changes to 130. |

A held node (2 or 128) is not rebooted by the master when it leaves OPERATIONAL, and a node that starts by itself is sent the hold again. A reset (129, 130) clears the hold, the node boots again, and the byte must change away and back to reset it again. The plugin logs each command it sends (`NMT STOP (held by the program)`, `NMT RESET NODE (from the program)`). Other values are ignored with a warning. The byte reads 0 at start, so a program that never writes it leaves the node to the master.

## Compatibility rules

Within one `schema_version`, a later release of the plugin accepts every file an earlier release accepted, with the same meaning. New optional fields may be added within a version. Removing a field, making an optional field required, or changing a field's meaning needs a new `schema_version`. Unknown fields are ignored with a warning that names the field and its JSON path (`nodes[0].colour`), so a file written for a newer release of the same version still loads.

The schema describes every field, its type and whether it is required. It cannot express these checks, which the plugin (and the deploy tool, before upload) run as well:

- node IDs are unique and differ from the master's;
- each entry's type fits its location's size (SDO variables too), and a PDO carries at most 64 bits;
- PDO numbers are unique per direction, PDOs above 4 have a `cob_id`, and no two PDOs share a COB-ID;
- `heartbeat_timeout_ms` is not shorter than `heartbeat_ms`, and heartbeat and node guarding are not combined;
- locations do not overlap and lie inside the runtime's I/O image;
- a startup SDO value fits its type, and numbers given as strings are in range;
- everything against the EDS: the file parses, PDO numbers exist, objects exist, are PDO-mappable, have the configured `DataType` and an `AccessType` that allows the direction.

The shared fixtures in [`test/fixtures/config/cases.json`](../test/fixtures/config/cases.json) and, for several networks and J1939, [`cases-v2.json`](../test/fixtures/config/cases-v2.json) and [`cases-j1939.json`](../test/fixtures/config/cases-j1939.json) run through the schema, the plugin and the deploy tool, and CI checks that they agree.

## Emergency messages

The master listens for the emergency (EMCY) messages of every node ID and logs each one from a configured node with the node, the error code, its CiA 301 class, the error register and the five manufacturer-specific bytes:

```
node 5 (rtd): EMCY 0x5000 (device hardware), error register 0x01, manufacturer bytes 01 00 00 00 00
node 5 (rtd): EMCY error reset (error register 0x00)
```

When a node sends more than 5 EMCY messages within one second, the rest of that second goes into one summary line with how many were not logged one by one and the latest code and error register (as the [bus state](#bus-diagnostics) log does):

```
node 5 (rtd): 46 more EMCY in the last second, latest 0x5000 (device hardware), error register 0x89
```

An EMCY from a node ID that is not in the configuration gives one warning, and later ones from it are ignored. EMCY messages do not change the node's state or status bit.

With `emcy_code_location` and `error_register_location` the program sees the latest EMCY:

- both read 0 until the node sends an EMCY;
- an EMCY sets the word to its error code and the byte to its error register;
- an error reset (code 0x0000), which the device sends when it has no errors left, sets the word to 0 and the byte to the register it carries (normally 0);
- a boot-up message (the node restarted) sets both to 0;
- while the node is lost, both keep their value.

Only the latest EMCY is visible: a fault that is reset within one scan, or the same code twice in a row, shows only in the log. The pre-defined error field (0x1003, the device's error history) is not read.

The master expects a slave's EMCY on the COB-ID its EDS gives as the default of 0x1014 (normally 0x80 + node ID); for node IDs without such an entry (a node whose EDS lacks 0x1014, or one not in the configuration) it uses 0x80 + node ID. If the COB-ID was changed on the device itself, its EMCY messages are not seen.

A device that sends EMCY messages too often can be slowed down with a startup SDO to its EMCY inhibit time, 0x1015 (`UNSIGNED16`, in 100 µs), if its EDS has that object; `dcfgen` has no option for it.

The EMCY code and the [boot error byte](#identity-check-and-boot-error-byte) are separate: the boot error byte says why the master could not boot the node, the EMCY code what the device itself reports while it runs.

## What is rejected

If the file does not exist, the plugin logs a warning with the expected path and stays inactive. Otherwise it stays inactive, opens no CAN interface, and logs every problem with the file and the field, node, object or location it concerns, when:

- the file is not valid JSON, or lacks a required field;
- a node ID is outside 1-127, is used twice, or is the master's;
- an EDS file is missing or cannot be parsed;
- the file's `schema_version` is newer than the plugin's, or it has both `adapter` and the old top-level keys, or an unknown adapter type, or a field of the other adapter type, or an `slcan` adapter without an absolute `device`;
- an entry names an object that the node's EDS does not define as PDO-mappable, whose `DataType` differs from the entry's type, or whose `AccessType` does not allow the direction;
- a startup SDO names an object the EDS does not define, is not writable, has another `DataType`, or its value does not fit the type;
- an SDO variable names an object the EDS does not define, has another `DataType`, does not allow its direction, has a location of the wrong area or size, gives `period_ms` on a write or below 10, or a `timeout_ms` outside 10-60000; or its trigger is not `%QX`, its status not `%IB` or its abort code not `%ID`;
- a node's `nmt_command_location` is not `%QB`;
- a PDO number does not exist on the slave, or two PDOs share a COB-ID;
- a PDO's `mapping` is `"config"` on a mapping the EDS makes read-only; a device-mapped PDO has no default mapping in the EDS, or an entry that is not in it or has another size there;
- a PDO communication field names a sub-index the EDS does not define, or one it marks read-only with another value (a read-only COB-ID also when `cob_id` is left out and the CiA 301 default differs); `inhibit_time_us` or `sync_start` is on an RPDO; `inhibit_time_us` is not a multiple of 100; or `sync_start` goes with an event-driven transmission type;
- `timeout_ms`, `on_timeout` or `timeout_location` is on an RPDO; `timeout_ms` is 0, above 65535 or `"auto"` without an event timer; `on_timeout` or `timeout_location` is given without `timeout_ms`; `on_timeout` is not `"hold"` or `"zero"`; or `timeout_location` is not an `%IX` bit;
- an entry received from a slave has an output location, an entry sent to a slave has an input location, or the type does not fit the location;
- two entries (or an entry and a node or master diagnostic location, `emcy_code_location`, `error_register_location`, `nmt_command_location`, `timeout_location` and every SDO variable location included) map to the same location;
- a master diagnostic location has the wrong type (`%IB` for the states and the counters, `%IW` for the bus-off count), a node's `state_location`, `boot_error_location` or `error_register_location` is not `%IB`, or its `emcy_code_location` is not `%IW`;
- a time in µs that CiA counts in 100 µs is not a multiple of 100, `sync_counter_overflow` is 1 or above 240, or an `error_behavior` sub-index is outside 1-254;
- a node sets `config_check` while its EDS has no writable 0x1020 sub 1 and sub 2, or `store_configuration` outside 1-127, without `config_check`, or on a 0x1010 sub-index its EDS does not define as writable;
- a node sets `lss.assign` without `serial_number` or with `reset_communication: false`, `lss.store` without `lss.assign`, or two nodes with `lss.assign` have the same LSS address;
- a node's `axis` is not an object, has an unknown field, a `scale_numerator` that is 0 or not an integer in the DINT range, a `scale_denominator` outside 1-4294967295 or a `scale_factor` of 0;
- a node sets `heartbeat_consumer: true` while `master.heartbeat_ms` is 0, sets `software_version` without `software_file`, or names a `software_file` that does not exist;
- a location lies outside the runtime's I/O image (index 1024 and up on a default runtime);
- in a version 2 file: `networks` is missing, empty or longer than 8, a network name is invalid or used twice, two networks use the same interface or serial device, a field of a network (`adapter`, `master`, `nodes`) sits at the top level, or `diagnostics` sits in a network's `master`;
- `nodes` is empty without `master.diagnostics` (in version 2, without the top-level `diagnostics`), or `master.diagnostics` has the former `token_sha256` or a `token_verifier` that is not a valid verifier, a `port` outside 1024-65535 or a `bind` that is not an IPv4 address;
- a network's `protocol` is not `"canopen"` or `"j1939"`, a J1939 network has `role`, `master`, `nodes` or `slave`, lacks `j1939` or sets `adapter.simulate`, or a CANopen network has `j1939`;
- a slave network has `master` or `nodes`, a master network has `slave`, a version 1 file has `role`, `slave`, `gateway`, `protocol` or `j1939`, or two master networks (or two slave networks) share a simulated bus;
- a slave's `node_id` is outside 1-127 and not `null`, its EDS is missing or fails the lint, or a binding names an object the EDS does not define, an object bound twice, a `const` or `wo` object, a location of the wrong area for the object's access type or of a size that does not fit its type; a slave status location has the wrong type (`%IB` state, `%IX` communication OK, `%IW` SYNC count, `%QW` EMCY code, `%QB` error register);
- a PDO entry has no `iec_location` and no gateway route writes it;
- the `gateway` names an `upper` network that is missing or not a slave network, there is no master network, a route names a network, node, PDO entry or slave object that does not exist, its direction does not fit the slave object's access type, its two ends differ in type, its target has a second writer, `status` covers more than 4 master networks, or `status` or `sdo_bridge` is set while the slave's EDS lacks their objects.

In every case the PLC starts and runs normally; fix the file and restart the PLC to activate the plugin.

## At runtime

- Inputs are copied to the PLC before every scan and hold their last received value; a node that never came up reads zero. A TPDO with `timeout_ms` is flagged when it stops coming while its node is up (see [Receive timeout](#receive-timeout)).
- Outputs are read after every scan and sent at the next SYNC, only to nodes that are operational. Without a SYNC period, the master looks for new outputs every millisecond and sends each event-driven PDO whose data changed (within its inhibit time); outputs that do not change send nothing.
- With the SYNC timer (`sync_period_us`) the SYNC and the PLC cycle run on separate clocks: output latency varies between almost nothing and one SYNC period, and a scan may now and then see no new inputs. Use `"sync_source": "plc_cycle"` when that matters.
- A node that is absent, rejects its configuration, or stops sending heartbeats does not stop the PLC or the other nodes. Its status bit goes FALSE, and the master keeps trying to boot and configure it in the background.

## SYNC from the PLC cycle

With `"sync_source": "plc_cycle"` the master sends SYNC at the start of the PLC cycle instead of from its own timer:

```json
"master": { "node_id": 1, "sync_source": "plc_cycle", "sync_cycles": 1 }
```

On every `sync_cycles`-th PLC cycle the plugin's `cycle_start()` first copies the newest inputs to the PLC and then asks the bus thread for a SYNC, which goes out with the outputs the previous scan wrote. For a node whose PDOs have transmission type 1, with cycle k starting at SYNC k:

```
cycle k:    SYNC k: nodes sample their inputs and send them    scan k runs and writes outputs
cycle k+1:  the inputs of SYNC k reach the PLC                 SYNC k+1, then the outputs of scan k
cycle k+2:  nodes apply the outputs of scan k at SYNC k+2
```

Inputs are one cycle old and outputs are applied two SYNCs after the scan that wrote them, every time. The SYNC period is the PLC task interval times `sync_cycles`; `sync_period_us` is not allowed with it, and the master's own 0x1006 stays 0. `sync_window_us` and `sync_counter_overflow` work as with the timer, and every PDO setting the config leaves out keeps its EDS value. The master takes synchronous inputs as they arrive (its own RPDOs become event-driven; the nodes keep their types), so they are ready for the next cycle.

- The runtime calls the plugin once per PLC *frame*: a base tick on which at least one task is due. With one task, or tasks whose intervals are all multiples of the fastest one, frames come at the fastest task's interval. Other mixes (10 ms and 15 ms) give uneven frames and an uneven SYNC.
- The bus thread runs at SCHED_FIFO priority 49 (the runtime's highest task level) so the SYNC follows the cycle closely. If the runtime may not set it, the plugin logs a warning and runs at normal priority.
- When the PLC stops, SYNC stops. A node that supervises SYNC (its own 0x1006, or a drive's interpolation watchdog) reports that as a fault. A long scan overrun does not stop SYNC, because the runtime keeps starting frames.
- A cycle below 1 ms is allowed, with a warning at start: the bus may not carry all PDOs in one period.
- The diagnostics status ([diagnostics.md](diagnostics.md)) and the configurator's online view show the SYNC interval (last, shortest, longest), cycles merged into one SYNC because the bus thread fell behind, and late PDOs: node TPDOs with a cyclic synchronous type that did not arrive before the next SYNC. Both are also logged, at most once per 10 seconds per PDO.
