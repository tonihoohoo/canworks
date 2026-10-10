## Why

The PLC program can read and write any object of any node with the `CO_SDO_*` blocks, but its only way to act on NMT is a node's `nmt_command_location` byte: one output byte per configured node, fixed in the config, that holds the node STOPPED or PRE-OPERATIONAL or resets it. CiA 405 gives the program the NMT side as function blocks too: command any node (or all of them), and read the NMT state the master sees. Three things are missing today:

- a program cannot command a node the config does not list, or every node at once, and cannot pick the node at run time;
- a program cannot start or stop the master itself. `master.start: false` is documented as "no PDOs move until something starts it", but nothing in the plugin can start it (see design.md, "What starts a master with `start: false` today"): the master stays PRE-OPERATIONAL until the PLC restarts with another config. A program that wants to bring the network up only when the machine is ready has no way to do it;
- a program reads a node's NMT state only through a configured `state_location` byte, and the master's state only through `master.state_location`.

## What Changes

- Four new function blocks in the `canworks` editor library, on the same request path as the SDO blocks (request slots in the plugin, taken by the network's 10 ms request timer, run on the bus thread) and with the same handshake (`EXECUTE`, `BUSY`, `DONE`, `ERROR`, `ERROR_ID`) and `NETWORK` input:
  - `CO_NMT`: sends a CiA 301 NMT command (START 1, STOP 2, ENTER PRE-OPERATIONAL 128, RESET NODE 129, RESET COMMUNICATION 130, the codes `nmt_command_location` already uses) to node 1-127, configured or not, or to every node with `NODE := 0`. For a configured node, STOP and PRE-OPERATIONAL are holds the master keeps after every boot, as with the command byte.
  - `CO_NETWORK_START`: starts the master (NMT START to itself) and so the PDO exchange; with mandatory nodes missing, it starts the master as soon as they have booted. This makes `master.start: false` an autostart-off pattern: the network comes up configured but idle, and the program starts it.
  - `CO_NETWORK_STOP`: puts the master into PRE-OPERATIONAL (no PDOs, SDO still works) and sends every node that is up the command chosen by its `NODE_COMMAND` input (by default what `master.on_plc_stop` says). The master stays stopped, also across node boots, until `CO_NETWORK_START`.
  - `CO_GET_STATE`: the NMT state the master last saw for a node, the master's own state, whether the node is configured, held, or failed its boot, and whether the network is started; answered in the call that starts it, from a snapshot the bus thread keeps.
- The plugin exports a second versioned C entry point, `canopen_plc_nmt_api`, next to `canopen_plc_api`. The SDO table and its version stay as they are, so the SDO blocks are untouched and a library with these blocks on an older plugin fails only the NMT blocks (`ERROR_ID` 4).
- Defined interplay with what already commands nodes: the command byte, the online view and Modbus control block NMT commands, and these blocks share one hold per node (the last command wins); the gateway's upper-loss hold and a master STOPPED by `stop_all_nodes` are not overridden from the program; a command from the program to a mandatory node is not a loss of that node; `master.on_plc_stop` still applies at PLC stop, and nothing the program set survives a PLC restart.
- The configurator's online view gets "Copy as ST call" for its NMT buttons (a `CO_NMT` call for that node and command), and the master's "Master goes operational" setting says how to start the network from the program and copies a `CO_NETWORK_START` call.
- Docs: a new `docs/plc-nmt.md`; `docs/config.md` (`start`, NMT commands from the program, `on_plc_stop`), `docs/plc-sdo.md`, `docs/configurator.md` and `README.md` point to it.

## Capabilities

### New Capabilities
- `canopen-plc-nmt`: NMT commands, network start and stop, and NMT state reads started by the PLC program through the library's function blocks: block interface and handshake, commands and their effect on holds, master start and stop, state read, error IDs, PLC stop, how the blocks find the plugin and how they are delivered.

### Modified Capabilities
- `canopen-node-supervision`: the NMT command byte shares the node's hold with the program's `CO_NMT` and the operator; a program command to a mandatory node is not a loss.
- `canopen-master-bringup`: `start: false` keeps the master PRE-OPERATIONAL until the program starts it with `CO_NETWORK_START`, and the load warning says so.
- `canopen-configurator`: Copy as ST call for NMT commands in the online view and for `CO_NETWORK_START` next to the master's start setting.

## Impact

- Plugin: new `canopen_plc_nmt_api.h` (C table, version 1), NMT request slots and a state snapshot in `plc_api.cpp/.h`, `Network` takes NMT requests in `ServiceProgram` and runs them next to `OperatorNmt` (`network_diag.cpp`) and `ApplyNmtCommand` (`network.cpp`), a program start flag and a network stop flag gating `StartHeldMaster`, the snapshot written from `SetState`, `SetMasterState` and the hold changes. No config schema change, no change to `canopen_plc_api` v1.
- Library: `library/generate.py` writes the four blocks with shared code in a new `library/src/nmt_common.inc`; `canworks.stlib` rebuilt; deploy package version bump.
- Configurator: `app.js` online view NMT buttons and the master start checkbox hint.
- Tests: plugin unit tests for the NMT slots and snapshot; simulation tests with the real blocks on the in-process virtual bus; a bench check on the Pi with real nodes.
- Parallel change `add-emcy-history` adds `CO_RECV_EMCY` to the same library. The two are independent: this change adds its own entry point and its own shared include, does not change the SDO table or `common.inc` beyond what it reads, and does not edit the library delivery requirement; whichever lands second rebuilds the `.stlib` and adds its blocks to the docs' block list.
