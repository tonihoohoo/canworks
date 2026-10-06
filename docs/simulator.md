# Simulated devices

The simulator runs CANopen devices built from their EDS (or DCF) files, so a configuration, the configurator's online views and a PLC program can be tried without the real devices. A simulated device is a full CANopen node: it boots, answers SDO, takes its configuration from the master, sends and receives PDOs, produces heartbeats, sends EMCY and stores parameters, all as its EDS describes. On top of that its values can move by themselves, follow formulas, play recorded data, and show faults on command or on a timeline.

A simulated device is what its EDS promises. A real device can behave differently where its EDS is incomplete or wrong; start a simulated device from a [parameter backup](diagnostics.md#replacing-a-device) to get a real device's values.

## Two switches

Which devices are simulated, and where, is set in `canopen.json` with two switches:

| Field | Meaning |
|---|---|
| `adapter.simulate` | `true`: the network is simulated. The master runs on an in-process virtual bus inside the plugin: no CAN interface or serial device is opened, no link is changed, no privileges are needed (it works in the Docker install and on a host without any CAN hardware). The other adapter fields are kept and checked, so switching back needs only this field. Default `false`: the real adapter, as always. |
| `simulate` (per node) | `true`: this node is a simulated device run by the plugin, built from the node's EDS, node ID, identity and LSS settings. Default: `true` on a simulated network, `false` on a real one. |

That gives four combinations:

| Network | Nodes | Result |
|---|---|---|
| simulated | all (no node sets `simulate`) | Every node is simulated. The easy way to try a project. |
| simulated | some (`"simulate": false` on the others) | The others are absent, as unplugged devices: their status bit stays FALSE and the master retries their boot. |
| real | some (`"simulate": true` on them) | The simulated devices run inside the plugin on the real interface, next to the real devices. Real devices on the wire and the master see them as any other node. |
| real | all | Every node is simulated, and their frames go out on the real interface. |

A config with anything simulated is announced everywhere: a warning at every PLC start naming what is simulated, `simulated_network` and per-node `simulated` in the diagnostics status, a banner in the configurator, and a question before the deploy tool uploads it. Outputs to a simulated device go nowhere, so never leave a machine's config simulated.

### Simulated devices on a real network

Before a simulated device starts on a real interface, the plugin listens for 1 second. A node ID that sends heartbeats, boot-up messages, EMCY or SDO answers there belongs to a real device: its simulated device is not started, the log names the conflict, the node's boot error says so, and the master goes on with the real device. While a simulated device runs, a heartbeat, boot-up or EMCY with its node ID that it did not send makes it power off at once, with a log line. A real device that stays silent during that first second and never sends a heartbeat can still go unnoticed; give real devices a heartbeat.

The simulated devices run in the plugin's bus thread on their own sockets on the same interface. The kernel's local loopback hands their frames to the master and puts them on the wire, so the bus trace shows them too.

## Default behaviour

Without any setting, each device chooses its behaviour from its device profile (the low 16 bits of object 0x1000):

| Profile | Behaviour |
|---|---|
| CiA 401 (generic I/O) | Outputs loop back to inputs at the same subindex: 0x6200 to 0x6000, 0x6220 to 0x6020, 0x6250 to 0x6050 (digital), 0x6411 to 0x6401 (analogue), where both objects exist. |
| CiA 404 (measuring) | Every object the EDS maps by default into a TPDO moves slowly: a sine with a 60 s period between 25 % and 75 % of its EDS limits (or of its data type's range). |
| CiA 402 (drives) | The [drive model](#cia-402-drive-model). |
| anything else | Nothing moves by itself; only the master and you change values. |

`"default_behaviour": false` on a node in the simulation file switches this off.

## `openplc-canopen-sim`

The standalone simulator runs devices on a SocketCAN interface: for a plugin on the same host, for another CANopen master, or on a second adapter on a test bench. It is installed with the plugin (see [install-stock.md](install-stock.md)).

```sh
openplc-canopen-sim canopen/canopen.json             # every node of the config on vcan0
openplc-canopen-sim canopen/canopen.json --nodes 5,7 # only nodes 5 and 7
openplc-canopen-sim --eds drive.eds --node 4         # one device
openplc-canopen-sim canopen/canopen.json --iface vcan1 --sim my-sim.json
sudo openplc-canopen-sim --setup-vcan canopen/canopen.json   # creates vcan0 if missing
```

With a config, `simulation.json` next to it is used when it exists (`--sim FILE` names another; `--no-sim-file` ignores it). Options:

| Option | Meaning |
|---|---|
| `--iface NAME` | The SocketCAN interface, default `vcan0`. |
| `--setup-vcan` | Create and bring up a missing vcan interface (needs root). |
| `--real-bus` | Allow an interface that is not vcan. The free node ID check and the conflict guard above apply. |
| `--nodes LIST` | Only these nodes of the config (comma separated). |
| `--eds FILE --node ID` | A device that is not in a config (may repeat; `--name NAME` names it). `--node 0` starts it without a node ID, waiting for LSS. |
| `--sim FILE`, `--no-sim-file` | The simulation file. |
| `--no-defaults` | No default behaviour for any device. |
| `--state-dir DIR` | Keep stored parameters (0x1010) and LSS-stored node IDs in DIR, so they survive a restart of the simulator. Without it they live as long as the process. |
| `--scenario NAME` | Start this scenario once the devices are up (may repeat). |
| `--port N`, `--bind ADDR` | The control channel, default `127.0.0.1:7532`. Any address other than loopback needs a token. |
| `--token T`, `--token-file F` | The control channel's token. |
| `--quiet` | Only errors and scenario results. |

Without `--real-bus`, an interface that is not vcan is refused, because simulated devices on a real bus can collide with real ones. The simulator prints a line per device at start, and one for every NMT state change, power change, fault and scenario result. SIGINT or SIGTERM stop every device.

### Control subcommands

While a simulator runs, these talk to it over its control channel (default `127.0.0.1:7532`; `--sim HOST[:PORT]` and `--token`/`--token-file` for another one). `openplc-canopen-diag sim ...` has the same subcommands for the plugin's simulated devices (`--runtime HOST`) and for a standalone simulator (`--sim HOST[:PORT]`).

```sh
openplc-canopen-sim status
openplc-canopen-sim get 5 0x7130:1
openplc-canopen-sim set 5 0x7130:1 450                 # once; a source moves it again
openplc-canopen-sim override 5 0x7130:1 1500           # held until released
openplc-canopen-sim release 5 0x7130:1                 # or: release 5 (all of node 5)
openplc-canopen-sim source 5 0x7130:2 '{"sine": {"min": 200, "max": 260, "period_s": 10}}'
openplc-canopen-sim source 5 0x7130:2 none
openplc-canopen-sim fault 5 emcy 0x5000 --register 1 --msef 0100000000
openplc-canopen-sim fault 5 power off                  # power on | power cycle --off-ms 2000
openplc-canopen-sim fault 5 sdo-abort 0x2000:1 0x08000020 --on write --count 1
openplc-canopen-sim clear 5 emcy                       # or: clear 5 all
openplc-canopen-sim scenario list
openplc-canopen-sim scenario start sensor-break
openplc-canopen-sim scenario stop sensor-break
```

The `fault` kinds are those of [Faults](#faults), written with dashes (`heartbeat-stop`, `sdo-delay`, `refuse-write-operational`, `tpdo-stop`, `forget-node-id`, ...); `fault 5 json '{...}'` takes the JSON form.

### Test mode

`openplc-canopen-sim test` runs scenarios as tests of a PLC program:

```sh
openplc-canopen-sim test canopen/canopen.json --scenario alarm --junit results.xml
openplc-canopen-sim test --runtime plc.local --token-file token --scenario alarm
```

With a config it starts the devices as the run mode does, waits until every simulated node is OPERATIONAL (or `--start-timeout` seconds), runs the named scenarios (default: every scenario with `"test": true`) one after another (`--parallel` runs them together), and stops after the last one or after `--timeout` seconds. With `--runtime` it runs the scenarios in the plugin's simulated devices through the diagnostics channel instead. It prints one line per scenario, writes a JUnit XML report with `--junit FILE`, and exits 0 only when every scenario passed (1: a scenario failed, 2: usage or start-up error).

## The simulation file

Behaviour is set in `canopen/simulation.json`, next to `canopen.json`. It travels with the project like the config: the editor's Build and upload and the deploy tool carry it to the runtime. The file is optional. [`schema/canopen-sim.v1.schema.json`](../schema/canopen-sim.v1.schema.json) describes it; unknown keys are errors.

```json
{
  "schema_version": 1,
  "tick_ms": 10,
  "nodes": {
    "5": {
      "sources": {
        "0x7130:1": { "sine": { "min": 200, "max": 260, "period_s": 10 } },
        "0x7130:2": { "expr": "20 + lag(if(bit([7/0x6200:1], 0), 80, 0), 30)" },
        "0x7130:3": { "csv": { "file": "data/temp.csv", "interpolate": "linear", "loop": true } }
      },
      "faults": [ { "sdo_abort": { "object": "0x2000:1", "on": "write", "code": "0x08000020", "count": 1 } } ]
    },
    "4": { "drive": { "max_velocity": 50000, "max_acceleration": 200000, "lag_ms": 5 } }
  },
  "extra_devices": [
    { "node": 40, "name": "spare", "eds": "eds/pingpong.eds" },
    { "node": 0, "name": "new-module", "eds": "eds/lss-slave.eds", "identity": { "serial_number": 1234 } }
  ],
  "scenarios": {
    "sensor-break": {
      "test": true,
      "steps": [
        { "node": 5, "set": { "0x7130:1": 900 } },
        { "expect": { "node": 7, "object": "0x6200:1", "bit": 2, "eq": 1 }, "within_ms": 500 },
        { "after_ms": 2000, "node": 5, "fault": { "emcy": { "code": "0x5000", "register": 1 } } },
        { "wait": { "node": 7, "object": "0x6200:1", "bit": 3, "eq": 1 }, "timeout_ms": 1000 },
        { "node": 5, "clear": "emcy" }
      ]
    }
  }
}
```

| Field | Meaning |
|---|---|
| `schema_version` | 1 (default). A higher version is refused with both versions named. |
| `tick_ms` | How often value sources and models run, 1-60000 ms, default 10. A node or a source can set its own. |
| `nodes` | Behaviour per node ID (as a string key, `"5"`). Entries for nodes that are not simulated in this config are kept and do nothing, so a node can be switched between real and simulated without editing the file. An entry for a node ID that is neither in the config nor an extra device is an error. |
| `extra_devices` | Devices that are simulated without being in the config: to try a bus scan, LSS commissioning or an identity check. Each has `node` (1-127, or 0: no node ID, waits for LSS), `eds` (an EDS or DCF, relative to this file), and optionally `name` (required with node 0; a device is addressed by its name then), `identity` and the node fields below. |
| `scenarios` | Named [scenarios](#scenarios). |

A node (or extra device) can have:

| Field | Meaning |
|---|---|
| `default_behaviour` | `false` switches off the [default behaviour](#default-behaviour). |
| `tick_ms` | Overrides the file's `tick_ms` for this device. |
| `sources` | Object → [value source](#value-sources). Objects are written `"0xIIII:S"` (`"0xIIII"` is subindex 0). |
| `drive` | Settings of the [drive model](#cia-402-drive-model). |
| `faults` | [Faults](#faults) in force from the start. |
| `identity` | Overrides 0x1018: `vendor_id`, `product_code`, `revision_number`, `serial_number`. |
| `device_type` | Overrides 0x1000. |

Paths in the file (EDS, DCF, CSV) are relative to the file. The deploy tool copies them into the upload with it.

## Value sources

A value source writes one object of a simulated device every tick. Each source is an object with one type key, optionally `noise` (a random value between -noise and +noise added each tick) and `tick_ms`:

| Type | Fields | Value |
|---|---|---|
| `constant` | the value | That value (a number, or a string for VISIBLE_STRING objects, the only type a string object takes). |
| `sine`, `triangle`, `sawtooth` | `min`, `max`, `period_s`, `phase_deg` (0) | The waveform between min and max. |
| `square` | the same and `duty` (0.5) | `max` for `duty` of the period, then `min`. |
| `ramp` | `from`, `to`, `duration_s`, `then`: `hold` (default), `repeat` or `reverse` | A straight line. |
| `steps` | `values`: list of `[value, duration_s]`, `repeat` (true) | A step sequence. |
| `random_walk` | `min`, `max`, `max_step`, `start` (midpoint) | Moves by up to `max_step` each tick, inside min-max. |
| `counter` | `start` (0), `step` (1), `min`, `max` | Adds `step` each tick, wrapping from max to min (or min to max for a negative step). |
| `csv` | `file`, `column` (1), `interpolate`: `linear` (default) or `step`, `loop` (false), `time_scale` (1) | A time series: column 0 is the time in seconds, `column` the value; a first line that is not numeric is a header. After the last row the value holds, or the series starts again with `loop`. |
| `expr` | the text | An [expression](#expressions). |

Time counts from when the source was given, or from the device's power-on for sources in the file. Values are converted to the object's data type: rounded for integer types, clamped to the type's range, BOOLEAN is `value != 0`. A source on an object the master writes (an RPDO entry, or an object the configuration or an SDO variable writes) is refused, naming the RPDO or the writer; use an override to make a device ignore its master.

Who wins, per object and tick: an override; else a value set once (`set`) until the next change of the source; else the value source; else the drive model; else the default behaviour. Writes from the master always land in the object dictionary (and are then overwritten by whichever of those is active). A change of an object mapped into an event-driven TPDO makes the device send that PDO, within its inhibit time, as device firmware does.

## Expressions

An expression computes a value every tick. It has numbers (`12`, `-3.5`, `0x1F`, `1e3`), `true`/`false`, the names `t` (seconds since the device's power-on), `dt` (seconds since the last tick), `pi` and `prev` (the object's own value before this tick), object values, operators and functions.

| Object value | Means |
|---|---|
| `[0x6200:1]` | Object 0x6200 subindex 1 of the same device (`[0x6200]` is subindex 0). |
| `[7/0x6200:1]` | The same object of simulated node 7 (or of the extra device named `spare`: `[spare/0x6200:1]`). |

Operators, from lowest to highest precedence: `||`, `&&`, `|`, `^`, `&`, `==` `!=`, `<` `<=` `>` `>=`, `<<` `>>`, `+` `-`, `*` `/` `%`, `**` (power, right to left), unary `-` `!` `~`. Bit operators work on the integer part. Comparisons and `!` give 1 or 0.

| Function | Value |
|---|---|
| `abs(x)`, `floor(x)`, `ceil(x)`, `round(x)`, `sqrt(x)`, `exp(x)`, `log(x)`, `sin(x)`, `cos(x)` | As usual (radians). |
| `min(a, b, ...)`, `max(a, b, ...)`, `clamp(x, lo, hi)` | Limits. |
| `if(c, a, b)` | `a` when `c` is not 0, else `b`. |
| `bit(x, n)`, `setbit(x, n, v)` | Bit `n` of `x`; `x` with bit `n` set to `v`. |
| `noise(a)` | A new random value between -a and a every tick. |
| `lag(x, tau)` | First-order lag of `x` with time constant `tau` seconds (a temperature following its heater). |
| `delay(x, s)` | `x` as it was `s` seconds ago (dead time, at most 600 s). |
| `rate_limit(x, r)` | Follows `x`, changing by at most `r` per second. |
| `integrate(x)` | The integral of `x` over time since power-on. |
| `hold(x, c)` | Takes `x` when `c` rises, keeps it otherwise. |
| `edge(c)` | 1 in the tick `c` rises, else 0. |

An expression is checked when it is loaded: an unknown name, function, object or device, a wrong number of arguments, or a reference cycle through objects whose sources are expressions without `lag`, `delay` or `integrate` on the way is refused with its position in the text. While running, a division by zero or a result that is not a finite number keeps the object's previous value; the device reports it once.

```text
20 + lag(if(bit([7/0x6200:1], 0), 80, 0), 30)    heater on node 7's output bit 0, 30 s time constant
[0x6411:1] * 0.5 + noise(2)                        analogue loopback, halved, with noise
if([4/0x6041] & 0x0400, 1, 0)                      1 once drive 4 reports target reached
integrate([0x6200:1] * 10)                         a tank filled by an output
```

## CiA 402 drive model

A device whose profile is CiA 402 runs a drive model on the objects its EDS has:

- the power drive state machine on the controlword 0x6040 and statusword 0x6041 (not ready to switch on, switch on disabled, ready to switch on, switched on, operation enabled, quick stop active, fault reaction active, fault), with fault reset, quick stop, "set-point acknowledge", "target reached", "following error" and "warning" bits;
- the modes in 0x6060 (shown in 0x6061) that 0x6502 lists, or all of these when the EDS has no 0x6502: profile position (1), profile velocity (3), homing (6), cyclic synchronous position (8) and cyclic synchronous velocity (9);
- profile position: trapezoidal moves with the profile velocity 0x6081 and accelerations 0x6083/0x6084, absolute or relative (controlword bit 6), the set-point handshake with "change set immediately" (bit 5);
- profile velocity: ramps to the target velocity 0x60FF;
- cyclic synchronous modes: follow the target position 0x607A or velocity 0x60FF at every SYNC (or every tick when there is no SYNC);
- homing methods 17, 18 (limit switches), 33, 34, 35 and 37 (current position), with the homing speed 0x6099 and offset 0x607C; any other method ends with the homing error bit;
- the actual position 0x6064 and velocity 0x606C follow the demand through a first-order lag, limited by `max_velocity` and `max_acceleration`;
- the software position limits 0x607D stop a move at the limit and set the warning bit; the following error window 0x6065 (and time 0x6066) faults the drive with EMCY 0x8611 when exceeded.

`drive` settings in the simulation file: `max_velocity` (counts/s, default 100000), `max_acceleration` (counts/s², default 1000000), `lag_ms` (default 5), `start_position` (0). Inputs, set as faults: `drive_input` with `blocked` (the axis does not move, which provokes a following error), `positive_limit`, `negative_limit` and `home_switch`.

## Faults

Faults are given in the simulation file (`faults`, in force from the start), by a scenario step, from the configurator's Simulation view, or with `fault`/`clear` on the command line. Each fault is an object with one key:

| Fault | Fields | Effect | `clear` |
|---|---|---|---|
| `emcy` | `code`, `register` (0), `msef` (5 bytes as hex, `"0000000000"`), `period_ms` (once) | Sends the EMCY, again every `period_ms` when given. | `emcy`: stops a periodic EMCY and sends the error reset (code 0x0000). |
| `heartbeat` | `"stop"` | The device stops its heartbeat but goes on working (a firmware hang the master notices). | `heartbeat` |
| `power` | `"off"`, `"on"` or `"cycle"` (with `off_ms`, default 1000) | Off: the device sends and answers nothing. On: it boots again with the values from its file and its stored values. | `power` (powers on) |
| `reset` | `"node"` or `"comm"` | The device resets itself and sends its boot-up. | - |
| `nmt_state` | `"stopped"`, `"preop"` or `"operational"` | The device changes its state by itself. | - |
| `sdo_abort` | `object`, `code`, `on`: `read`, `write` or `both` (default), `count` (until cleared) | Transfers of that object abort with the code. | `sdo_abort` (all), or with the object |
| `sdo_delay` | `ms`, `object` (all) | SDO answers come `ms` later. | `sdo_delay` |
| `refuse_write_operational` | `true` | Writes abort with 0x08000022 while the device is OPERATIONAL. | `refuse_write_operational` |
| `tpdo_stop` | the TPDO number (1-512) | The device stops sending that TPDO. | `tpdo_stop` (all), or with the number |
| `identity` | `vendor_id`, `product_code`, `revision_number`, `serial_number` | 0x1018 reads these values from now on, also after a reset. | `identity` |
| `device_type` | the value | 0x1000 reads it. | `device_type` |
| `forget_node_id` | `true` | The device loses its node ID and waits for LSS, like a new device without DIP switches. | - |
| `drive_input` | `blocked`, `positive_limit`, `negative_limit`, `home_switch` (booleans) | Inputs of the drive model. | `drive_input` |

`clear` with `all` removes every fault that can be cleared and powers the device on.

## Stored parameters

A device whose EDS has 0x1010 keeps what is saved with "save" (0x65766173) across power off/on, a reset and an NMT reset, per subindex range as CiA 301 defines (1: all, 2: communication, 3: application, 4 and up: manufacturer). "load" (0x64616F6C) to 0x1011 forgets them at the next reset. The configuration date and time in 0x1020 are kept with them, so the plugin's [configuration check](config.md#configuration-check) works. LSS "store configuration" keeps an LSS-assigned node ID the same way. The plugin keeps stored values as long as the runtime runs (across PLC stop and start); the standalone simulator as long as it runs, or in `--state-dir`.

## Scenarios

A scenario is a named list of steps, run in order. A step has one action, optionally `node` (the device it acts on), and optionally when it starts: `at_ms` (since the scenario started) or `after_ms` (since the previous step ended).

| Action | Fields | Does |
|---|---|---|
| `set` | object → value | Sets values once. |
| `override` | object → value | Holds values until released. |
| `release` | list of objects, or `"all"` | Ends overrides. |
| `source` | object → source, or `null` | Gives or removes value sources. |
| `fault` | a fault | Injects it. |
| `clear` | a fault name, or `"all"` | Clears it. |
| `wait` | a condition, and `timeout_ms` on the step | Waits until it holds; a timeout fails the scenario. |
| `expect` | a condition, and `within_ms` or `for_ms` on the step | Checks it: now, until it holds within the time, or that it holds the whole time. |
| `log` | text | Prints the text. |
| `repeat` | `count` (0: forever), `steps` | Runs the steps again and again. |

A condition is `{"node": 7, "object": "0x6200:1", "eq": 5}` with one of `eq`, `ne`, `lt`, `le`, `gt`, `ge` and optionally `bit` (compares that bit), or `{"expr": "[7/0x6200:1] > 5 && [5/0x7130:1] < 300"}`.

A scenario with `"autostart": true` starts with the simulation; one with `"test": true` is run by `openplc-canopen-sim test` by default. Several scenarios can run at the same time, and a running scenario can be stopped. A failed `expect` or a `wait` that times out ends the scenario as failed, naming the step, the condition and the value seen; the simulation goes on.

## Control protocol

The plugin's diagnostics channel ([diagnostics.md](diagnostics.md#protocol)) and the standalone simulator's control channel take the same requests: one JSON object per line each way, answers `{"id": ..., "ok": true, "result": {...}}` or `{"id": ..., "ok": false, "error": "..."}`. The standalone simulator listens on `127.0.0.1:7532` by default; it wants the hello line `{"op": "hello", "token": "..."}` first only when it has a token, and answers it with `protocol` (1), `version` and `simulator: true`.

Objects are `"0xIIII:S"`; `node` is a node ID or the name of an extra device. Values are JSON numbers, or strings for VISIBLE_STRING objects.

| `op` | Fields | Result |
|---|---|---|
| `sim_status` | | `simulated_network`, `interface`, `devices` (each: `node`, `name`, `eds`, `profile`, `power` on/off, `nmt` (bootup, stopped, operational, preop), `conflict`, `faults`, `sources`, `overrides`), `scenarios` (each: `name`, `state` idle/running/passed/failed/stopped, `step`, `message`) |
| `sim_get` | `items`: list of `{"node", "object"}`, or `node` with `pdo: true` (every object in the device's active PDOs) | `values`: list of `{"node", "object", "value", "type"}` or `{"node", "object", "error"}` |
| `sim_set` | `node`, `values`: object → value | |
| `sim_override` | `node`, `values` | |
| `sim_release` | `node`, `objects`: list or `"all"` | |
| `sim_source` | `node`, `object`, `source` (or `null` to remove) | |
| `sim_fault` | `node`, `fault` | |
| `sim_clear` | `node`, `fault`: a name or `"all"`, and `object` / `tpdo` for one rule | |
| `sim_scenario_list` | | `scenarios` as in `sim_status` |
| `sim_scenario_start` | `name`, or `scenario` (a scenario object, run once under `name`) | |
| `sim_scenario_stop` | `name` | |
| `sim_check_expr` | `node`, `expr` | `ok`, or `error` and `position` |

`sim_status`, `sim_get`, `sim_scenario_list` and `sim_check_expr` need only the token; the others need `allow_changes` on the plugin's diagnostics channel. Every change is logged with the client's address. On a runtime that simulates nothing, every `sim_` request answers `nothing simulated`; a request for a node the plugin does not simulate answers `node N is not simulated`.
