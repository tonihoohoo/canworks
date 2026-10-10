# Simulator

The simulator has two parts. [Simulated devices](#simulated-devices) are CANopen nodes built from their EDS files, so a configuration, the configurator's online views and a PLC program can be tried without the real devices. A [simulated machine](#simulated-machine) can sit on top of a simulated network's devices: a gantry, conveyors, sensors and a pallet that the program's outputs move. The configurator's **Simulation** view drives both; its **Machine** tab shows the machine in 3D.

Both are for CANopen networks. A J1939 network does not run on the simulated bus (`adapter.simulate` is refused there); `canworks-j1939-sim` plays its other ECUs from a DBC file instead ([j1939.md](j1939.md#simulator)).

## Simulated devices
The simulator runs CANopen devices built from their EDS (or DCF) files, so a configuration, the configurator's online views and a PLC program can be tried without the real devices. A simulated device is a full CANopen node: it boots, answers SDO, takes its configuration from the master, sends and receives PDOs, produces heartbeats, sends EMCY and stores parameters, all as its EDS describes. On top of that its values can move by themselves, follow formulas, play recorded data, and show faults on command or on a timeline.

A simulated device is what its EDS promises. A real device can behave differently where its EDS is incomplete or wrong; start a simulated device from a [parameter backup](diagnostics.md#replacing-a-device) to get a real device's values.

### Two switches

Which devices are simulated, and where, is set in `canworks.json` with two switches:

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

#### Forced by the runtime: `CANWORKS_FORCE_SIMULATE`

A runtime started with the environment variable `CANWORKS_FORCE_SIMULATE=1` runs every network simulated, master and slave networks alike, whatever its `adapter.simulate` and adapter settings say: no CAN interface or serial device is opened. The [local simulator runtime](local-runtime.md) image sets it. Nodes keep their own switches, so a node with `"simulate": false` stays absent, as on any simulated network. Only the exact value `1` forces; anything else (`0`, `true`, empty) changes nothing, and a value other than `1` or empty logs a warning that it is ignored. The plugin logs `simulation forced by the runtime environment (CANWORKS_FORCE_SIMULATE=1)` for each network at every PLC start, the diagnostics status carries `simulation_forced`, and `canworks-diag status` and the configurator's online view say so.

#### Several networks

In a config with several networks ([version 2](config.md)), each network has its own switches: one network can be simulated while another runs on its real interface, and the simulated devices of each network are reached by its name (`--network NAME` on `canworks-diag sim`, the network picker in the configurator). The [simulation file](#the-simulation-file) has a section per network in version 2; a version 1 file serves a config with one network only (with several networks the plugin and the deploy tool's check say it is not used, and the simulated devices run with their [default behaviour](#default-behaviour)).

A simulated master network and a simulated [slave network](slave.md#simulated-bus) with the same `interface` name share one simulated bus: the plugin's master then reaches the plugin's own slave. A simulated bus takes one master network and one slave network.

#### Simulated devices on a real network

Before a simulated device starts on a real interface, the plugin listens for 1 second. A node ID that sends heartbeats, boot-up messages, EMCY or SDO answers there belongs to a real device: its simulated device is not started, the log names the conflict, the node's boot error says so, and the master goes on with the real device. Extra devices of the simulation file go through the same check. While a simulated device runs, a heartbeat, boot-up or EMCY with its node ID that it did not send makes it power off at once, with a log line. Such a device is taken for the rest of the session (until the PLC starts again): a power on, a `clear`, a fault or a scenario step for it is refused with "node N is taken by a real device", so it never boots next to the real one. A real device that stays silent during that first second and never sends a heartbeat can still go unnoticed; give real devices a heartbeat.

The simulated devices run in the plugin's bus thread on their own sockets on the same interface. The kernel's local loopback hands their frames to the master and puts them on the wire, so the bus trace shows them too.

### Default behaviour

Without any setting, each device chooses its behaviour from its device profile (the low 16 bits of object 0x1000):

| Profile | Behaviour |
|---|---|
| CiA 401 (generic I/O) | Outputs loop back to inputs at the same subindex: 0x6200 to 0x6000, 0x6220 to 0x6020, 0x6250 to 0x6050 (digital), 0x6411 to 0x6401 (analogue), where both objects exist. |
| CiA 404 (measuring) | Every object the EDS maps by default into a TPDO moves slowly: a sine with a 60 s period between 25 % and 75 % of its EDS limits (or of its data type's range). |
| CiA 402 (drives) | The [drive model](#cia-402-drive-model). |
| anything else | Nothing moves by itself; only the master and you change values. |

`"default_behaviour": false` on a node in the simulation file switches this off.

### `canworks-sim`

The standalone simulator runs devices on a SocketCAN interface: for a plugin on the same host, for another CANopen master, or on a second adapter on a test bench. It is installed with the plugin (see [install-stock.md](install-stock.md)).

```sh
canworks-sim canworks/canworks.json             # every node of the config on vcan0
canworks-sim canworks/canworks.json --nodes 5,7 # only nodes 5 and 7
canworks-sim --eds drive.eds --node 4         # one device
canworks-sim canworks/canworks.json --iface vcan1 --sim my-sim.json
sudo canworks-sim --setup-vcan canworks/canworks.json   # creates vcan0 if missing
```

With a config, `simulation.json` next to it is used when it exists (`--sim FILE` names another; `--no-sim-file` ignores it). Options:

| Option | Meaning |
|---|---|
| `--iface NAME` | The SocketCAN interface, default `vcan0`. |
| `--setup-vcan` | Create and bring up a missing vcan interface (needs root). |
| `--real-bus` | Allow an interface that is not vcan. The free node ID check and the conflict guard above apply. |
| `--nodes LIST` | Only these nodes of the config (comma separated). |
| `--eds FILE --node ID` | A device that is not in a config (may repeat; `--name NAME` names it). `--node 0` starts it without a node ID, waiting for LSS. |
| `--sim FILE`, `--no-sim-file` | The simulation file. Given alone, without a config or `--eds`, it runs the file's [plain CAN devices](#plain-can-devices). |
| `--no-defaults` | No default behaviour for any device. |
| `--state-dir DIR` | Keep stored parameters (0x1010) and LSS-stored node IDs in DIR, so they survive a restart of the simulator. Without it they live as long as the process. |
| `--scenario NAME` | Start this scenario once the devices are up (may repeat). |
| `--port N`, `--bind ADDR` | The control channel, default `127.0.0.1:7532`. Any address other than loopback needs a token. |
| `--token T`, `--token-file F` | The control channel's token. With a token the channel is encrypted (TLS, the token never sent). |
| `--quiet` | Only errors and scenario results. |

Without `--real-bus`, an interface that is not vcan is refused, because simulated devices on a real bus can collide with real ones. The simulator prints a line per device at start, and one for every NMT state change, power change, fault and scenario result. SIGINT or SIGTERM stop every device.

#### Control subcommands

While a simulator runs, these talk to it over its control channel (default `127.0.0.1:7532`; `--sim HOST[:PORT]` and `--token`/`--token-file` for another one). `canworks-diag sim ...` has the same subcommands for the plugin's simulated devices (`--runtime HOST`, with `--network NAME` when the runtime runs several networks) and for a standalone simulator (`--sim HOST[:PORT]`).

```sh
canworks-sim status
canworks-sim get 5 0x7130:1
canworks-sim set 5 0x7130:1 450                 # once; a source moves it again
canworks-sim override 5 0x7130:1 1500           # held until released
canworks-sim release 5 0x7130:1                 # or: release 5 (all of node 5)
canworks-sim source 5 0x7130:2 '{"sine": {"min": 200, "max": 260, "period_s": 10}}'
canworks-sim source 5 0x7130:2 none
canworks-sim fault 5 emcy 0x5000 --register 1 --msef 0100000000
canworks-sim fault 5 power off                  # power on | power cycle --off-ms 2000
canworks-sim fault 5 sdo-abort 0x2000:1 0x08000020 --on write --count 1
canworks-sim clear 5 emcy                       # or: clear 5 all
canworks-sim scenario list
canworks-sim scenario start sensor-break
canworks-sim scenario stop sensor-break
```

The `fault` kinds are those of [Faults](#faults), written with dashes (`heartbeat-stop`, `sdo-delay`, `refuse-write-operational`, `tpdo-stop`, `forget-node-id`, ...); `fault 5 json '{...}'` takes the JSON form. Their fields are arguments or options as above (`emcy CODE --period-ms MS`, `sdo-delay MS --object OBJ`, `identity --serial-number N`, `drive-input --blocked`, ...; `canworks-sim --help` lists them). `get 5` without objects prints every object in node 5's PDOs. A command exits 1 when the simulator answers with an error, 2 when it cannot reach it.

#### Test mode

`canworks-sim test` runs scenarios as tests of a PLC program:

```sh
canworks-sim test canworks/canworks.json --scenario alarm --junit results.xml
canworks-sim test --runtime plc.local --token-file token --scenario alarm
```

With a config it starts the devices as the run mode does, waits until every simulated node is OPERATIONAL (or `--start-timeout` seconds, default 30; then it runs the scenarios anyway, with a warning), runs the named scenarios (default: every scenario with `"test": true`) one after another (`--parallel` runs them together), and stops after the last one or after `--timeout` seconds (default 300; scenarios still running then fail). With `--runtime HOST[:PORT]` (default port 7531) it runs the scenarios in the plugin's simulated devices through the diagnostics channel instead; with the port of a standalone simulator's control channel (`--runtime 127.0.0.1:7532`) it runs them there. It prints one line per scenario, writes a JUnit XML report with `--junit FILE`, and exits 0 only when every scenario passed (1: a scenario failed, 2: usage or start-up error).

### The simulation file

Behaviour is set in `canworks/simulation.json`, next to `canworks.json`. It travels with the project like the config: the editor's Build and upload and the deploy tool carry it to the runtime. The file is optional. [`schema/canworks-sim.v1.schema.json`](../schema/canworks-sim.v1.schema.json) describes it; unknown keys are errors.

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
| `schema_version` | 1 (default) or 2 ([below](#version-2-a-section-per-network)). A higher version is refused with both versions named. |
| `tick_ms` | How often value sources and models run, 1-60000 ms, default 10. A node or a source can set its own. |
| `nodes` | Behaviour per node ID (as a string key, `"5"`). Entries for nodes that are not simulated in this config are kept and do nothing, so a node can be switched between real and simulated without editing the file. An entry for a node ID that is neither in the config nor an extra device is an error. |
| `extra_devices` | Devices that are simulated without being in the config: to try a bus scan, LSS commissioning or an identity check. Each has `node` (1-127, or 0: no node ID, waits for LSS; not the node ID of a config node, simulated or not, nor the master's), `eds` (an EDS or DCF, relative to this file), and optionally `name` (required with node 0; a device is addressed by its name then), `identity` and the node fields below. |
| `scenarios` | Named [scenarios](#scenarios). |

#### Version 2: a section per network

A config with several networks takes a version 2 file ([`schema/canworks-sim.v2.schema.json`](../schema/canworks-sim.v2.schema.json)). `tick_ms` stays at the top; `nodes`, `extra_devices` and `scenarios` go in the section of their network under `networks`, keyed by the network's name (its interface for a version 1 config):

```json
{
  "schema_version": 2,
  "tick_ms": 10,
  "networks": {
    "io": {
      "nodes": { "5": { "sources": { "0x7130:1": { "sine": { "min": 200, "max": 260, "period_s": 30 } } } } },
      "extra_devices": [ { "node": 0, "name": "spare_io", "eds": "dio16.eds", "identity": { "serial_number": 7099 } } ],
      "scenarios": { "alarm": { "test": true, "steps": [ { "node": 5, "override": { "0x7130:1": 300 } } ] } }
    },
    "motion": { "nodes": { "4": { "drive": { "max_velocity": 50000 } } } }
  }
}
```

A section works as a version 1 file does for its own network: node keys, expressions (`[5/0x7130:1]`) and scenario steps refer to the devices of that network only. A section for a network that is not in the config is an error naming the networks there are; a network without a section runs with default behaviour, and `networks` may be left out (a file of `raw_devices` only, for example). A version 1 file stays valid for a config with one network. The configurator's Simulation view edits the section of the network picked at the top and writes version 2 when the config has several networks ([configurator.md](configurator.md#simulation-view)). [`examples/virtual-plant`](../examples/virtual-plant/README.md) has a complete one.

A section can also name a machine file, `"machine": "machine.json"`: a gantry, conveyor, sensors and pallet on top of the network's simulated drives and I/O, stepped with the devices ([Simulated machine](#simulated-machine)). Machine faults and machine conditions then work in that section's scenarios.

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

Paths in the file (EDS, DCF, CSV, the machine file) are relative to the file. The deploy tool copies them into the upload with it.

A CSV file must lie in the folder of the simulation file or of the config (or below it; links are followed first), be a regular file of at most 16 MB, and have lines of at most 4096 bytes. CSV files are read once, when the simulation file loads; a source given later (a control request or a scenario step) can only use a CSV file the simulation file already uses.

### Value sources

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

Time counts from when the source was given, or from the device's power-on for sources in the file. Values are converted to the object's data type: rounded for integer types, clamped to the type's range, BOOLEAN is `value != 0`. A value given with `set` or `override` that does not fit the data type (text for a number, a number for text, or a number outside the type's range) is refused with a message naming the type, also while the device is powered off. A source on an object the master writes (an RPDO entry, or an object the configuration or an SDO variable writes) is refused, naming the RPDO or the writer; use an override to make a device ignore its master.

Who wins, per object and tick: an override; else a value set once (`set`) until the next change of the source; else the value source; else the drive model; else the default behaviour. Writes from the master always land in the object dictionary (and are then overwritten by whichever of those is active). A change of an object mapped into an event-driven TPDO makes the device send that PDO, within its inhibit time, as device firmware does.

### Expressions

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
| `delay(x, s)` | `x` as it was `s` seconds ago (dead time, at most 600 s; a delay that is not a finite number counts as 0). It keeps at most 10,000 samples, so at a short tick a long delay gets shorter, and it starts over when time goes back. |
| `rate_limit(x, r)` | Follows `x`, changing by at most `r` per second. |
| `integrate(x)` | The integral of `x` over time since power-on. |
| `hold(x, c)` | Takes `x` when `c` rises, keeps it otherwise. |
| `edge(c)` | 1 in the tick `c` rises, else 0. |

An expression is checked when it is loaded: an unknown name, function, object or device, a wrong number of arguments, text longer than 4096 characters, nesting deeper than 128 levels (parentheses, calls, operators), or a reference cycle through objects whose sources are expressions without `lag`, `delay` or `integrate` on the way is refused with its position in the text. While running, a division by zero or a result that is not a finite number keeps the object's previous value; the device reports it once.

```text
20 + lag(if(bit([7/0x6200:1], 0), 80, 0), 30)    heater on node 7's output bit 0, 30 s time constant
[0x6411:1] * 0.5 + noise(2)                        analogue loopback, halved, with noise
if([4/0x6041] & 0x0400, 1, 0)                      1 once drive 4 reports target reached
integrate([0x6200:1] * 10)                         a tank filled by an output
```

### CiA 402 drive model

A device whose profile is CiA 402 runs a drive model on the objects its EDS has:

- the power drive state machine on the controlword 0x6040 and statusword 0x6041 (not ready to switch on, switch on disabled, ready to switch on, switched on, operation enabled, quick stop active, fault reaction active, fault), with fault reset, quick stop, "set-point acknowledge", "target reached", "following error" and "warning" bits;
- the modes in 0x6060 (shown in 0x6061) that 0x6502 lists, or all of these when the EDS has no 0x6502: profile position (1), profile velocity (3), homing (6), cyclic synchronous position (8), cyclic synchronous velocity (9) and cyclic synchronous torque (10);
- profile position: trapezoidal moves with the profile velocity 0x6081 and accelerations 0x6083/0x6084, absolute or relative (controlword bit 6), the set-point handshake with "change set immediately" (bit 5);
- profile velocity: ramps to the target velocity 0x60FF;
- cyclic synchronous modes: follow the target position 0x607A or velocity 0x60FF at every SYNC (or every tick when there is no SYNC); in torque mode the target torque 0x6071 (per mille) accelerates the axis by `torque_accel` per per mille, up to `max_velocity`, and 0x6077 shows it;
- SYNC watchdog: once a SYNC has come in a cyclic synchronous mode with operation enabled, the drive faults with EMCY 0x8700 when no SYNC comes for three interpolation periods (0x60C2, or 10 ms when the EDS has none), as a real drive does when the PLC stops; `"sync_watchdog": false` switches it off;
- set-point step counter: CSP set-points that move more than `max_velocity` times the interpolation period from one SYNC to the next are counted in `oversized_steps` of `sim_status`, so a test can show that a program's motion is smooth;
- homing methods 17, 18 (limit switches), 19 to 22 (home switch: 19 and 20 search in the positive direction, 21 and 22 in the negative), 33, 34, 35 and 37 (current position), with the homing speeds 0x6099 and offset 0x607C; any other method ends with the homing error bit;
- the actual position 0x6064 and velocity 0x606C follow the demand through a first-order lag, limited by `max_velocity` and `max_acceleration`;
- the software position limits 0x607D stop a move at the limit and set the warning bit; the following error window 0x6065 (and time 0x6066) faults the drive with EMCY 0x8611 when exceeded.

`drive` settings in the simulation file: `max_velocity` (counts/s, default 100000), `max_acceleration` (counts/s², default 1000000), `lag_ms` (default 5), `start_position` (0), `torque_accel` (counts/s² per per mille of target torque, default 10000), `sync_watchdog` (default true). Inputs, set as faults: `drive_input` with `blocked` (the axis does not move, which provokes a following error), `positive_limit`, `negative_limit` and `home_switch`.

### Faults

Faults are given in the simulation file (`faults`, in force from the start), by a scenario step, from the configurator's Simulation view, or with `fault`/`clear` on the command line. Each fault is an object with one key:

| Fault | Fields | Effect | `clear` |
|---|---|---|---|
| `emcy` | `code`, `register` (0), `msef` (5 bytes as hex, `"0000000000"`), `period_ms` (once) | Sends the EMCY, again every `period_ms` when given. Refused for a device whose EDS has no 0x1014 (COB-ID EMCY): it has no EMCY producer. | `emcy`: stops a periodic EMCY and sends the error reset (code 0x0000). |
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

### Stored parameters

A device whose EDS has 0x1010 keeps what is saved with "save" (0x65766173) across power off/on, a reset and an NMT reset, per subindex range as CiA 301 defines (1: all, 2: communication, 3: application, 4 and up: manufacturer). "load" (0x64616F6C) to 0x1011 forgets them at the next reset. The configuration date and time in 0x1020 are kept with them, so the plugin's [configuration check](config.md#configuration-check) works. LSS "store configuration" keeps an LSS-assigned node ID the same way. As CiA 305 has it, LSS Fastscan finds only devices without a node ID: a device that has one does not answer it, so a search on a busy bus finds the new device. The plugin keeps stored values as long as the runtime runs (across PLC stop and start); the standalone simulator as long as it runs, or in `--state-dir`.

### Scenarios

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
| `repeat` | `count` (0: forever), `steps` | Runs the steps again and again. A pass in which no step waited ends the scenario's steps for that tick, so a repeat of instant steps runs one pass per tick. |

A condition is `{"node": 7, "object": "0x6200:1", "eq": 5}` with one of `eq`, `ne`, `lt`, `le`, `gt`, `ge` and optionally `bit` (compares that bit), or `{"expr": "[7/0x6200:1] > 5 && [5/0x7130:1] < 300"}`.

A scenario with `"autostart": true` starts with the simulation; one with `"test": true` is run by `canworks-sim test` by default. Several scenarios can run at the same time, and a running scenario can be stopped. A failed `expect` or a `wait` that times out ends the scenario as failed, naming the step, the condition and the value seen; the simulation goes on.

### Plain CAN devices

Devices that speak neither CANopen nor J1939, such as a joystick or a display that sends and takes plain CAN frames ([raw-can.md](raw-can.md)), go in the simulation file's top-level `raw_devices`. They run on a simulated network of any protocol, a [plain CAN network](raw-can.md#plain-can-networks) included, inside the plugin, and with `canworks-sim` on an interface (a file of `raw_devices` only needs no `--eds`; on a real bus they need no free node ID).

```json
"raw_devices": [
  { "name": "joystick",
    "send": [ { "id": 385, "dlc": 5, "period_ms": 20, "signals": [
      { "name": "X", "start_bit": 0, "length": 16, "signed": true,
        "source": { "sine": { "min": -1000, "max": 1000, "period_s": 4 } } } ] } ],
    "replies": [ { "on": { "id": 2016, "data": [2, 1, 12] }, "send": { "id": 2024, "data": [4, 65, 12] } } ] }
]
```

| Field | Meaning |
|---|---|
| `name` | The device's name in scenarios, logs and the status. Unique in the file. |
| `network` | The network's name; required with several networks. |
| `send[]` | Frames the device sends every `period_ms`: `id` (`extended` for 29 bits), `dlc`, fixed `data` bytes, and `signals` numbered as in DBC files (`start_bit`, `length`, `byte_order`, `signed`, `scale`, `offset`) whose value comes from a [value source](#value-sources). Expression sources here cannot read objects. |
| `send[].signals[]` multiplexing | A send may be multiplexed as in the config ([raw-can.md](raw-can.md#multiplexed-messages)): a switch signal has `"multiplexer": true` and no `source` (the simulator sets it per page), dependent signals have `mux`. `pages` is `all` (default: every page each period, one frame per page) or `rotate` (one page per period, in turn). At most 64 pages. |
| `replies[]` | Answers: a frame matching `on` (`id`, and the first bytes `data`, with an optional bit `mask` per byte) makes the device send `send` after `delay_ms`. |

A scenario step with `"device": NAME` acts on a plain CAN device: `"fault": {"stop": true}` stops its frames and replies, `"fault": {"wrong_dlc": N}` sends its frames with N data bytes, and `"clear"` takes `"stop"`, `"wrong_dlc"` or `"all"`. On a plain CAN network these steps, `log` and `repeat` are the only ones, since there are no nodes. [`examples/raw-can/cab.sim.json`](../examples/raw-can/cab.sim.json) has a joystick, a pedal, a multiplexed sensor sending two pages and a scenario that stops the joystick. The configurator's **Simulation** view lists the devices on its **File** tab.

### Control protocol

The plugin's diagnostics channel ([diagnostics.md](diagnostics.md#protocol)) and the standalone simulator's control channel take the same requests: one JSON object per line each way, answers `{"id": ..., "ok": true, "result": {...}}` or `{"id": ..., "ok": false, "error": "..."}`. The standalone simulator listens on `127.0.0.1:7532` by default. With a token it is encrypted and wants the same TLS and login as the diagnostics channel ([diagnostics.md](diagnostics.md#protocol)), computing the verifier from its token at start; its login answer carries `protocol` (2), `version` and `simulator: true`, and it refuses plain connections. Without a token (loopback only) it speaks plain lines; the first line must be `{"op": "hello"}`, answered with `protocol` (1), `version` and `simulator: true`. Any other first line closes the connection, at once and without an answer when it starts with an HTTP method, so a web page cannot send it requests.

Objects are `"0xIIII:S"`; `node` is a node ID or the name of an extra device. Values are JSON numbers, or strings for VISIBLE_STRING objects.

| `op` | Fields | Result |
|---|---|---|
| `sim_status` | | `simulated_network`, `interface`, `devices` (each: `node`, `name`, `eds`, `profile`, `power` on/off, `nmt` (bootup, stopped, operational, preop), `conflict`, `drive` (whether the drive model runs), `oversized_steps` (drive model only), `faults` (the fault objects in force), `sources` (object → source), `overrides` (object → value)), `scenarios` (each: `name`, `state` idle/running/passed/failed/stopped, `step`, `message`) |
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

## Simulated machine

A simulated network can carry a made-up machine on top of its simulated devices: an XYZ gantry with a gripper, belt conveyors with feeders, presence sensors and a pallet with slots. The machine reads the drives' actual positions and the master's output bits, and writes the drives' inputs (home switch, limit switches, blocked), their load torque and the input bits its sensors report. The PLC program does not know it is not a real machine: it sees CiA 402 drives and a CiA 401 I/O module on the bus, as the [simulated devices](#simulated-devices) give them, and its outputs move parts.

The **Machine** tab of the configurator's **Simulation** view draws the machine in 3D from the same file and the runtime's state ([The Machine tab](#the-machine-tab)). [`examples/gantry-cell`](../examples/gantry-cell/README.md) is a complete project, and the [tour](tour.md#15-simulated-machine) walks through it.

A machine only runs on a simulated network (`adapter.simulate`). On a network with real devices the plugin logs that it is not used.

### What the model does, and does not

It is kinematic: joints follow their drives, and parts go through a small set of states (on a belt, held, falling, placed, misplaced, on the table). Contacts are axis-aligned boxes. Only gravity acts on a falling part.

- **Joints** take their position from the drive's actual position 0x6064 (`counts_per_mm`, `offset_mm`, `direction`). The home flag sets the drive's home switch input at and below its position; the limit switches set the positive and negative limit inputs at and beyond theirs; at a hard stop, or when the tool or the part in hand would hit the table, the conveyor, the pallet or another part, the joint is blocked in that direction and the drive's following error does the rest, as on a real axis.
- **Load**: each joint gives its drive a load in per mille of rated torque, `hold_permille` plus `per_kg_permille` for the part in hand plus `per_m_s2_permille` for the joint's acceleration. 0x6077 shows it while operation is enabled, and in cyclic synchronous torque mode the drive accelerates by the target torque less the load.
- **Gripper**: its fingers take `stroke_ms` to close or open between `open_mm` and `closed_mm` along `axis`. Closing on a part within `pick_tolerance_mm` of the tool point picks it, and "gripped" comes on. Opening drops it: on a free slot within `place_tolerance_mm` it is placed, elsewhere it falls and lands where it lands.
- **Conveyors** run while their run bit is on, at `speed_mm_s`, and stop each part at the end, the next one `gap_mm` behind it. A feeder puts a part at the start every `every_s` seconds (a random time between the two values, from the machine's `seed`), when there is room.
- **Sensors** are boxes: on while a part (or the tool, `"detects": "tool"`) is in the box.
- **Fixtures** have `count` slots at `pitch` from `origin`. With `change`, a rising request bit takes the pallet away along `move` in `time_s` and brings an empty one back; the ready bit is off while it changes.

Not modelled: friction, part orientation beyond a yaw, stacking on top of parts, more than one gripper, robot arms, and any other kind of machine than `gantry_xyz`. At most 50 parts are on the machine at a time; the feeder waits while there are 50.

The model steps every `tick_ms` (default 2 ms) on the simulator's loop, after the devices, in sub-steps of at most 5 ms when the loop is late. It is deterministic: the same program on the same file places the same parts in the same slots.

### The machine file

The simulation file (version 2) names it per network, relative to itself:

```json
{
  "schema_version": 2,
  "networks": {
    "motion": { "machine": "machine.json", "nodes": { "4": { "tick_ms": 1 } } }
  }
}
```

The deploy tool carries it into the upload with the simulation file. Its JSON Schema is [`schema/canworks-sim-machine.v1.schema.json`](../schema/canworks-sim-machine.v1.schema.json). Units are millimetres: x and y on the table, heights above the table top. An I/O binding is always `{ "node": 10, "object": "0x6200:1", "bit": 1 }`. Outputs (conveyor run, gripper close, change request) must be objects the master writes, inputs (sensors, gripped, change ready) objects it does not write.

| Key | What it is |
|---|---|
| `schema_version` | 1. |
| `name`, `kind` | A name for messages and the view; `kind` is `gantry_xyz`. |
| `units` | `mm` (the only unit). |
| `tick_ms`, `seed` | Model step (1 to 100 ms, default 2) and the feeder's random seed (default 1). |
| `joints` | `x`, `y` and `z`: `node` (a simulated CiA 402 node with an `axis` in the config), `travel` [min, max], `counts_per_mm` (default 1000), `offset_mm`, `direction` (1 or −1), `down` (z: a positive position lowers the tool), `home_flag`, `limits` [negative, positive], `hard_stops` [negative, positive], `load` (`hold_permille`, `per_kg_permille`, `per_m_s2_permille`). |
| `tool` | `type` `gripper`, `close` (output), `gripped` (input), `stroke_ms`, `open_mm`, `closed_mm`, `axis` (`x` or `y`), `offset` [x, y, height] of the tool point at joint positions 0, `pick_tolerance_mm`, `finger` [thickness, width, height]. |
| `parts` | Part kinds by name: `size` [x, y, height], `mass_kg`. |
| `conveyors` | `name`, `from` and `to` [x, y] of the belt's centre line, `width`, `height` (belt top), `speed_mm_s`, `gap_mm`, `run` (output), `feed` (`part`, `every_s` [min, max]). |
| `sensors` | `name`, `at` [x, y, height] and `size` of the box, `detects` (`part` or `tool`), `output` (input bit). |
| `fixtures` | `name`, `slots` (`origin` [x, y] of the first slot's centre, `pitch`, `count` [columns, rows]), `height` (pallet top), `margin`, `place_tolerance_mm`, `change` (`request` output, `ready` input, `time_s`, `move` [x, y]). |
| `visual` | For the Machine tab only: floor, table, frame, fence, stack light, colours. The simulator does not read it. |

Element names (conveyors, sensors, fixtures) are unique and not `x`, `y`, `z` or `tool`. The deploy tool's check, the configurator's problems and the plugin check what the schema cannot: joints on simulated nodes with an axis, bound objects in the node's EDS with room for the bit, outputs written by the master and inputs not, no input bound twice, travel, limits and hard stops in order, part kinds defined. Each message names the network and the element.

### Faults and conditions

Machine faults go through the same calls as device faults, with `machine` naming the element instead of `node`:

| Fault | Element | Effect | Cleared by |
|---|---|---|---|
| `{"jam": true}` | a joint | The joint does not move; the drive faults on its following error (EMCY 0x8611). | `jam` |
| `{"stuck": "on"}`, `{"stuck": "off"}` | a sensor | The sensor reports on or off whatever is there. | `stuck` |
| `{"slip": true}` | `tool` | The gripper drops what it holds, once. | (nothing to clear) |
| `{"feeder": "stop"}`, `{"feeder": "empty"}` | a conveyor with a feeder | No new parts until cleared (both act the same; the name says why in the log and the view). | `feeder` |
| `{"misaligned_mm": 15}` | a conveyor with a feeder | The next part fed is that far off the belt's centre line. | `misaligned_mm` (before it is fed) |

`all` clears every fault of the element. In a scenario:

```json
{ "machine": "z", "fault": { "jam": true } },
{ "after_ms": 500, "machine": "z", "clear": "jam" },
{ "expect": { "machine": "placed", "ge": 4 }, "within_ms": 40000 }
```

A condition's `machine` names a counter (`fed`, `picked`, `placed`, `misplaced`, `dropped`, `pallets`), a sensor (0 or 1), a fixture (parts in its slots) or a joint (position in mm). The Machine tab has a button for each; on the diagnostics channel they are `sim_fault` and `sim_clear` with `machine` in place of `node` (`{"op": "sim_fault", "machine": "z", "fault": {"jam": true}}`), and `sim_machine` returns the whole state (below). Faults need `allow_changes`, as device faults do.

### State

`sim_machine` (read only) answers with the network, a time stamp `t_us`, a sequence number `seq`, the model's step time (`step_us`, `step_max_us`) and:

- `joints`: per joint `node`, `position` (mm), `velocity`, `demand`, `actual_counts`, the drive's `state`, `mode`, `statusword`, `fault`, `error_code` (0x603F, while it is not 0) and `torque` (0x6077, per mille);
- `tool`: `position` [x, y, height], `opening`, `closed`, `holding`;
- `parts`: `id`, `kind`, `position` [centre x, centre y, bottom height], `yaw`, `state`;
- `sensors`, `conveyors` (`running`, `travel`), `fixtures` (`offset`, `ready`, `changing`, `filled`), `counters` and the `faults` in force.

The snapshot of a machine with 50 parts is about 4 KB. `sim_status` carries the counters and faults too.

### The Machine tab

**Simulation → Machine** in the configurator, the fourth tab after Live values, Simulation file and Scenarios ([configurator.md](configurator.md#machine-tab)); it shows when the network's simulation section names a machine file, and takes the whole content area. It builds the gantry, conveyor, pallet, stack light, fence and floor from the file, and moves them from `sim_machine` answers it polls over the diagnostics connection, interpolating between them so the motion is smooth whatever the poll rate.

- **Quality**: High (soft shadows, ambient occlusion, bloom on lamps, anti-aliasing) or Low; it drops to Low by itself, and says so, when the frame rate stays under 28 per second for 3 s, and remembers your choice on this PC. Without WebGL it shows the side panel with live values and says the 3D view needs WebGL.
- **Labels** on the drives (node, position, mode or EMCY code), sensors and fixtures, the **tool path** (the last few seconds of the tool point) and the current set-point as a marker; an axis in fault turns red, the stack light shows the cell's state and each drive has a lamp.
- **Camera**: **Overview**, **Top** and **Follow tool**; orbit, pan and zoom with mouse or touch. Click a motor or carriage, an axis row of the panel or an axis label to open that node in **Online**.
- **Side panel**: per axis its state, mode, statusword, position in mm and counts, following error against the window (0x6065) and torque; the machine's I/O bits, the counters, the last faults, and buttons for the faults above and **Clear all** (disabled, with the reason, without **Allow changes**).
- Offline, it shows the machine at its home positions as a preview; with no answer for 1 s it holds the last pose and says "no data". It polls only while it is open and the browser tab is visible.

The 3D library, three.js 0.169, ships with the PC tools, so the view needs no internet.
