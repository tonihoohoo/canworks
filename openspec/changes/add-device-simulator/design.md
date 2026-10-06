## Context

See proposal.md for why. What exists today:

- The plugin (`plugin/src`) runs a Lely `BasicMaster` (`Network`) on a SocketCAN channel prepared by `can_adapter` (socketcan or slcan), in its own bus thread with one Lely event loop. Diagnostics (`diag.cpp`, `network_diag.cpp`) and trace capture (`trace_capture.cpp`, a second receive-only socket) hang off that loop.
- `test/sim/sim_tests.cpp` already runs the master against Lely slaves on `io::VirtualCanController` in one process, and `test/sensor/sensor_slave.hpp` already builds a slave from any EDS, moves values (triangle waves), sends EMCY and blanks PDO mappings. `test/lss/lss_slave.cpp` shows the LSS and store hooks a simulated device needs.
- The PC tools (`tools/deploy`, Python, Windows/macOS/Linux) reach the bus only through the plugin's diagnostics channel. The configurator already has Online, Object dictionary, Parameters and Trace views on that channel.
- The runtime host is Linux; the managed Docker install gives the plugin no vcan and no extra capabilities.

## Goals / Non-Goals

**Goals:**
- Any mix: one, some or all devices simulated, on the real network or a simulated one, chosen with two switches (network, per device).
- A fully simulated network on any runtime install, with no CAN hardware, kernel module or privileges.
- The same engine as a standalone process on a SocketCAN interface, for a plugin on the same host, another master, or a second adapter on a real bench.
- Advanced behaviour without writing code: value sources, expressions with plant dynamics, device models, fault injection, scenarios and expects, live control from CLI and configurator, a CI test mode.
- Simulated devices that are protocol-correct because they are Lely slaves built from the EDS, not hand-written frame generators.

**Non-Goals:**
- Bit-level CAN effects: error frames, bus-off, arbitration loss, bit-rate mismatch. The virtual bus is perfect; vcan is too.
- A simulator on Windows or macOS (a python-can based one could reuse the simulation file later).
- Simulating a master, MPDO, SRDO/safety, CANopen FD.
- Replaying a recorded trace as a device (a CSV value series covers the common case).
- Physical accuracy of the drive model beyond kinematics with acceleration limits and a lag.
- Moving the existing test slaves onto the engine (possible later, not needed).

## Decisions

### D1. One engine library, two hosts
`plugin/sim/` builds a static library `canopen_sim` with `SimDevice` (a Lely `BasicSlave` subclass), the value-source and expression engine, the device models, the fault layer, the simulation-file loader, the scenario runner and the control-op dispatcher. It is linked into `libcanopen_plugin.so` (in-plugin host) and into the `openplc-canopen-sim` executable (standalone host). Both hosts expose the same control ops, so the CLI, `openplc-canopen-diag sim` and the configurator need one client.
*Alternative:* a separate simulator process that the plugin spawns for `adapter.simulate`. Rejected: process lifecycle across PLC start/stop, a socket or vcan between them (vcan is not available in Docker), and two places to look for logs.

### D2. Where simulated devices run in the plugin
Two independent switches decide it: `adapter.simulate` (the network) and per-node `simulate` (the device), with the per-node default following the network (true on a simulated network, false on a real one). The plugin builds one list of simulated devices (simulated nodes plus extra devices) and places them by network:

| Network | Master channel | Simulated device channels | Nodes not simulated |
|---|---|---|---|
| simulated | `VirtualCanChannel` on an in-process `VirtualCanController` | `VirtualCanChannel` on the same controller | absent (like unplugged) |
| real | SocketCAN socket on the interface, as today | one more SocketCAN socket per device on the same interface | real devices on the wire |

All simulated devices run on the same Lely loop and executor as the master, in the bus thread; nothing new runs in the scan path. On a real interface the kernel's local loopback delivers a device socket's frames to the master's socket (and the master's to the device sockets) and puts them on the wire, so real devices, the master and the simulated devices see each other exactly as on one bus; `CAN_RAW_RECV_OWN_MSGS` stays off, so a device socket never sees its own frames. That works the same for SocketCAN and slcan interfaces (the loopback is in the CAN core).
Value sources and models tick from one per-device timer (default 10 ms; the CiA 402 model 1 ms while enabled). A budget test with 32 devices and 10 sources each at 10 ms must stay under 5 % of one core on the CI runner; a Pi-class host is checked in the hardware task.
*Alternatives:* one thread per device (rejected: locking against Lely's master, no gain at these rates); simulated devices on a real network only through the standalone process (rejected by the "mix of all from the config" requirement; the standalone process still covers other masters and other hosts).

### D2a. Node ID safety on a real network
Before the first simulated device starts on a real interface, the bus thread listens 1 s on its raw socket and records node IDs seen in heartbeat/boot-up (0x700+id), EMCY (0x080+id) and SDO answers (0x580+id). A simulated node whose ID was seen is not started; the node's boot error is reported as a node ID conflict and the master keeps treating that ID as a real device. While running, each device socket watches those COB-IDs for its own node ID: since it never receives its own frames, any such frame comes from another device, and the simulated device powers off (frame layer, D7) and logs the conflict. A real device that stays silent during the listen and only answers later is caught by the same guard at its first heartbeat or boot-up. The listen happens once per PLC start, before the master's NMT reset, and only when the real network has simulated devices.

### D3. Two switches instead of a new adapter type
`adapter.simulate` next to the real adapter keeps `interface`, `bitrate`, `type` and the slcan fields, so a simulated network is reversible with one switch and the rest of the config (bit rate for bus load, DBC export) stays meaningful; the adapter is still validated, so a config does not silently break when switched back. Per-node `simulate` keeps a node's whole configuration, so a device can be swapped between real and simulated without touching its PDOs or locations, and behaviour in `simulation.json` for a real node is kept for when it is switched back.
*Alternative:* `adapter.type: "simulated"`. Rejected: it throws away the real adapter settings, cannot express a mixed network, and every tool that reads `type` would need a third branch.

### D4. A separate `simulation.json`
`canopen.json` stays the description of the real network; simulation behaviour lives in `canopen/simulation.json`, which travels with the project the same way (editor snapshot, deploy bundle `conf/canopen/simulation.json`). It has its own schema `schema/canopen-sim.v1.schema.json`. Sketch:

```json
{
  "schema_version": 1,
  "defaults": { "tick_ms": 10 },
  "nodes": {
    "5": {
      "default_behaviour": true,
      "sources": {
        "0x7130:1": { "sine": { "min": 200, "max": 260, "period_s": 10 } },
        "0x7130:2": { "expr": "20 + lag(if(bit([7/0x6200:1], 0), 80, 0), 30)" },
        "0x7130:3": { "csv": { "file": "data/temp.csv", "interpolate": "linear", "loop": true } }
      },
      "faults": [ { "sdo_abort": { "object": "0x2000:1", "on": "write", "code": "0x08000020", "count": 1 } } ]
    },
    "4": { "drive": { "max_velocity": 50000, "max_acceleration": 200000, "lag_ms": 5, "following_error_window": 2000 } }
  },
  "extra_devices": [
    { "node": 40, "eds": "eds/pingpong.eds" },
    { "node": null, "eds": "eds/lss-slave.eds", "identity": { "serial_number": 1234 } }
  ],
  "scenarios": {
    "sensor-break": { "test": true, "steps": [
      { "node": 5, "set": { "0x7130:1": 900 } },
      { "expect": { "node": 7, "object": "0x6200:1", "bit": 2, "eq": 1, "within_ms": 500 } },
      { "after_ms": 2000, "node": 5, "fault": { "emcy": { "code": "0x5000", "register": 1 } } },
      { "wait": { "node": 7, "object": "0x6200:1", "bit": 3, "eq": 1, "timeout_ms": 1000 } },
      { "node": 5, "clear": "emcy" }
    ] }
  }
}
```

Node keys are strings because JSON object keys are; objects are `"0xIIII:S"` like startup SDOs. Paths are relative to the file.

### D5. Own expression language, compiled once
A small Pratt parser compiles each expression to a tree at load time, with names, functions and object references resolved then (errors carry a position). Stateful functions (`lag`, `delay`, `rate_limit`, `integrate`, `hold`, `edge`, `noise`) keep per-call-site state in the compiled tree. Evaluation is allocation-free. Sources are evaluated in dependency order; a reference cycle is allowed only through a stateful function that uses the previous tick's value (`lag`, `delay`, `integrate`), otherwise it is a load error.
*Alternatives:* Lua or another embedded scripting language. Rejected for now: a new dependency in the plugin, sandboxing and CPU-limit work inside a PLC process, and a language PLC users do not know. The expression set covers plant models (first-order lag, dead time, integrator) that people actually need; a script source can be added later behind the same `sources` key.

### D6. Precedence of value writers
Per object, per tick: an override wins; else a scenario `set` (one-shot, then the source resumes on the next change); else a value source; else a device model; else the profile default; else the value stays. Writes from the master (RPDO, SDO) always land in the object dictionary; a source on a master-written object is refused at load (spec), and an override on one is allowed (it simulates a device that ignores the master) with a warning.
After writing an object that is mapped into an event-driven TPDO, the engine signals the PDO event so Lely sends it, honouring the inhibit time, as device firmware does.

### D7. Faults at two layers
- Object layer, through Lely's `OnRead`/`OnWrite` indications on the slave: SDO abort rules, refusing writes in OPERATIONAL, identity and device type overrides.
- Frame layer, a filtering channel wrapper between the `SimDevice` and its channel: power off (drop everything both ways), heartbeat stop (drop 0x700+id producer frames), TPDO stop (drop that COB-ID), SDO answer delay (hold 0x580+id frames for the given time on a timer). This keeps Lely's state machines intact and makes the faults look exactly like the real thing on the bus.
Power on resets the slave (Lely NMT reset node), reloads values from the file and applies stored values (D9). Forgetting the node ID sets the pending ID to 0xFF and resets communication, using the LSS hooks from `test/lss/lss_slave.cpp`.

### D8. Profile defaults and models
The profile comes from 0x1000 bits 0-15. CiA 401 loopback and CiA 404 slow movement are value sources the engine adds at load (visible and removable in the Simulation view). The CiA 402 model is a state machine plus a kinematic integrator:
- states and transitions per CiA 402 (statusword masks for each state, quick stop option code treated as "slow down on quick stop ramp");
- profile position: trapezoidal profile with 0x6081 velocity, 0x6083/0x6084 accelerations, set-point handshake with "change set immediately" bit;
- profile velocity: ramps to 0x60FF;
- cyclic synchronous position/velocity: follows 0x607A/0x60FF each SYNC through the lag;
- homing: methods 17, 18 (limit switches), 33, 34, 35 and 37 (current position); others end with the homing error bit;
- following error from demand minus actual, with a user-settable "blocked" input to provoke it; limit switches as user-settable inputs that stop the axis and set the warning bit.
Objects the EDS lacks are skipped once with a log line; the model never adds objects.

### D9. Stored values
Each `SimDevice` keeps a store image keyed by node ID and the SHA-256 of its EDS/DCF: written on "save" to 0x1010 (per subindex range as CiA 301 defines), cleared on "load" to 0x1011, applied after every power on or reset node. In the plugin the store lives in a process-wide map, so it survives PLC stop and start for as long as the runtime process runs. The standalone simulator keeps it in memory, or in `--state-dir DIR` (one JSON file per device) to survive simulator restarts. LSS "store configuration" goes to the same image.

### D10. Control protocol
Ops: `sim_status`, `sim_get` (list of `{node, object}`, so the configurator fetches all PDO objects of a node in one request), `sim_set`, `sim_override`, `sim_release`, `sim_source` (set or remove, same JSON as the file), `sim_fault`, `sim_clear`, `sim_scenario_start`, `sim_scenario_stop`, `sim_scenario_list`, `sim_add_device`. In the plugin they go through `diag.cpp` with the existing token and `allow_changes` rules; the standalone simulator serves the same ops with its own listener on 7532 (loopback without token, other addresses only with a token). The Python client lives in `tools/deploy` (`simclient.py`) and backs `openplc-canopen-diag sim`, the configurator and the remote `test --runtime`; the native binary has a minimal C++ client for its own subcommands so a Linux host needs no Python.

### D11. Trace on the virtual bus
`trace_capture` gets a second source: a receive-all `VirtualCanChannel` on the same controller that stamps frames with `CLOCK_REALTIME` on delivery and feeds the same ring. Frames the master sends are seen there too (the virtual controller delivers to every other channel), so the trace is complete. `trace_start` reports `interface: "simulated"`. On a real network nothing changes: the existing receive-only capture socket already gets the simulated devices' frames through the kernel's local loopback.

### D12. Real-bus safety in the standalone simulator
vcan is detected over rtnetlink (`LinkInfo.kind == "vcan"`, existing code). Anything else needs `--real-bus`; then the same listen and conflict guard as D2a apply (shared code in the engine). `--nodes` picks a subset of a config's nodes.

### D13. Configurator
- **Network: Real / Simulated** on Bus and master, a **Simulated** switch per node with a badge in the node list, **Simulate all / none** (D3), and a banner on all pages naming what is simulated.
- **Simulation** view: per device, a table of objects in its PDOs (and any object with a source, override or user pin) with live value (polled with one `sim_get` per refresh), slider or switch, source editor (form per source type, expression field with server-side check through the same parser exposed as a `sim_check_expr` op, or locally in Python with the same grammar for offline editing; the Python checker is tested against the C++ one on a shared corpus), fault buttons, extra devices, scenario list and step editor with live run state.
- Save writes `canopen/simulation.json` with the existing save rules (only the project's `canopen/` folder).

### D14. Deploy and install
Deploy adds `simulation.json` and its referenced EDS/DCF/CSV files to the bundle and to `--into-project`/`--new-project`; check runs the schema and the Python-side semantic checks (objects exist in the EDS, master-written objects, expression syntax). A config with a simulated network or any simulated node needs `--yes` or `--simulated` to upload, after a message naming what is simulated. `install-stock.sh` builds the `openplc-canopen-sim` target with the plugin, installs it to `$PREFIX/bin` with a `/usr/local/bin` link (native) or inside the container (Docker).

## Risks / Trade-offs

- [A config with simulated parts uploaded to a real machine leaves some or all CANopen devices uncontrolled] → banner in the configurator, confirmation in deploy, warning at every PLC start naming what is simulated, simulated flags in status and in the online view. Outputs to a simulated device go nowhere, which is the safe direction.
- [A simulated device on a real network competes with a real device of the same node ID] → free node ID listen before start and the conflict guard while running (D2a); the docs say a silent real device can still be missed until it first sends something.
- [Simulated devices add frames to a real bus] → their traffic is what the real device would send; bus load shows in the trace as usual.
- [CPU load of many simulated devices on a small runtime host] → one loop, 10 ms default tick, per-device tick configurable, budget test in CI and a check on a Pi-class host; the docs give the measured figures.
- [Plugin size and attack surface grow with code that only matters when simulating] → the engine is compiled in but never constructed unless something is simulated; `sim_` ops answer `nothing simulated` otherwise; the expression parser is fuzzed in unit tests.
- [Lely's slave accepts EDS files our lint accepts but behaves differently from a real device] → that is the honest limit of an EDS-driven simulator; docs say a simulated device is "what the EDS promises", and the device-from-backup path lets users start from a real device's values.
- [Two expression checkers (C++ and Python) drift] → one shared test corpus of valid and invalid expressions run against both in CI.
- [Scope is large] → tasks are grouped so each group is shippable on its own branch history and tested by itself; the in-plugin simulated network (the "easy" path) only needs groups 1, 4-partial, 5 and 7.

## Migration Plan

Additive only: no existing field changes meaning, `adapter.simulate` defaults to false and a node's `simulate` to false on a real network, configs without `simulation.json` behave as before. The deploy tool version goes up a minor version. Rollback is switching `adapter.simulate` and the nodes' `simulate` off, or uninstalling the simulator binary; nothing persists outside `--state-dir`.

## Open Questions

- The parallel change for several CAN networks moves `adapter` into each network; `simulate` then sits in each network's adapter and nodes unchanged. Whichever lands second adapts its schema text.


- Default tick on very small hosts (single-core boards): 10 ms is assumed; the hardware task measures it and may change only the documented recommendation.
- Whether the configurator's Simulation view should also open on a standalone simulator started from the same PC through an SSH tunnel; the address field covers it technically, the docs decide how to present it.
