# The `canworks` function block library

`canworks` is one OpenPLC Editor library with the function blocks and functions a PLC program uses to work with the canworks plugin's networks: CANopen, CiA 402, plain CAN and J1939. Every block works on any network the config has, picked with its `NETWORK` input, and never makes the scan wait: the plugin's bus threads do the work. The library's version is the PC tools' version.

## What it holds

| Family | Blocks | Functions | Reference |
|---|---|---|---|
| CANopen SDO and EMCY | `CO_SDO_READ`, `CO_SDO_WRITE` and their `_REAL`, `_STRING` and `_BYTES` variants, `CO_RECV_EMCY` | | [plc-sdo.md](plc-sdo.md) |
| CANopen NMT | `CO_NMT`, `CO_NETWORK_START`, `CO_NETWORK_STOP`, `CO_GET_STATE` | | [plc-nmt.md](plc-nmt.md) |
| CiA 402 cyclic modes | `CO402_CyclicPosition`, `CO402_CyclicVelocity`, `CO402_CyclicTorque`, `CO402_CyclicMoveAbsolute` | | [cia402.md](cia402.md#cyclic-synchronous-modes) |
| CAN frames | `CAN_SEND`, `CAN_SEND_CYCLIC`, `CAN_RECEIVE`, `CAN_BUS_INFO` | `CAN_GET_BITS`, `CAN_SET_BITS`, `CAN_GET_UINT16`, `CAN_SET_UINT16`, `CAN_GET_UINT32`, `CAN_SET_UINT32`, `CAN_J1939_ID`, `CAN_J1939_PGN`, `CAN_J1939_SOURCE` | [raw-can.md](raw-can.md#frame-blocks) |
| J1939 messages | `J1939_SEND`, `J1939_RECEIVE`, `J1939_REQUEST`, `J1939_ECU_INFO`, `J1939_FIND_ECU`, `J1939_NAME_SPLIT` | `J1939_GET_BITS`, `J1939_SET_BITS`, `J1939_NAME_MAKE` | [j1939.md](j1939.md#program-blocks) |
| J1939 trouble codes | `J1939_DM_READ`, `J1939_DM_CLEAR`, `J1939_DTC_SPLIT` | `J1939_DTC_MAKE` | [j1939.md](j1939.md#trouble-code-blocks) |

`canworks-deploy library --list` prints every block and function of the installed tools' library.

## Install and enable

The PC tools carry the library in the version that matches them. On the PC with OpenPLC Editor:

```sh
canworks-deploy library --install
```

installs it into the editor as its Library Manager does; restart the editor if it is open. Or write the file and add it in the editor's Library Manager with "install from file":

```sh
canworks-deploy library --out .      # writes canworks.stlib
```

Each `deploy-v` release also carries `canworks.stlib`. Then enable the library in the project (the editor's Library Manager, or `canworks-deploy library --project <project folder>`). A project made with `--new-project ... --blocks`, or with **Enable the canworks function blocks** in the configurator's New editor project dialog, has it enabled already, and the library is installed into the editor if it is missing or older. A config with a cyclic CiA 402 axis enables it in a new project anyway.

The configurator writes calls for you: **ST** and **Copy as ST call** on a CANopen object ([plc-sdo.md](plc-sdo.md#using-a-block)), **Copy as ST call** on an NMT command, a CAN message and a J1939 PGN.

## Handshakes

Every block that talks to a network has `NETWORK : USINT`, the network's place in the config's `networks` list counting from 0 (leave it unset with one network), and the outputs `ERROR : BOOL` and `ERROR_ID : UINT`. Each family has its own `ERROR_ID` table on its reference page. Two handshakes cover all blocks:

- **`EXECUTE`** (the SDO blocks, `CO_NMT`, `CO_NETWORK_START`, `CO_NETWORK_STOP`, `CAN_SEND`, `J1939_SEND`, `J1939_REQUEST`, `J1939_DM_READ`, `J1939_DM_CLEAR`): a rising edge starts one job with the inputs of that call. `BUSY` is TRUE until it ends; then `DONE` or `ERROR` is TRUE for as long as `EXECUTE` stays TRUE, or for one call if it is already FALSE. Edges and input changes while `BUSY` are ignored. Call the instance every scan while it is busy.
- **`ENABLE`** (`CAN_RECEIVE`, `CAN_SEND_CYCLIC`, `J1939_RECEIVE`, `J1939_ECU_INFO`, `J1939_FIND_ECU`, `CO_RECV_EMCY`, the `CO402_Cyclic*` blocks): the block works while `ENABLE` is TRUE and gives its result in the same call. A receiving block takes one message per call with `NEW` TRUE, so a `WHILE blk.NEW DO ... blk(...); END_WHILE;` loop drains everything waiting in one scan.

`CO_GET_STATE` and `CAN_BUS_INFO` have neither and answer in every call. The functions need no plugin and work in any program.

## Plugin interface versions

The blocks find the plugin the runtime has loaded and ask its entry point for the interface version they were built for. A newer plugin keeps offering every older version, so a program keeps working when the plugin is updated. A block whose version the plugin does not offer ends with its family's "not running" error, and the runtime log says once that the program's canworks library needs a newer plugin, naming both versions; the other families keep working.

| Family | Plugin entry point | Version | On a plugin without it |
|---|---|---|---|
| SDO blocks | `canopen_plc_api` | 1 | `ERROR_ID` 4 |
| `CO_RECV_EMCY` | `canopen_plc_api` | 2 | `ERROR_ID` 4 |
| NMT blocks | `canopen_plc_nmt_api` | 1 | `ERROR_ID` 4 |
| CAN frame blocks | `canworks_can_api` | 1 | `ERROR_ID` 1 |
| J1939 trouble code blocks | `canworks_j1939_api` | 1 | `ERROR_ID` 1 |
| J1939 message blocks | `canworks_j1939_api` | 2 | `ERROR_ID` 1 |

The `CO402_Cyclic*` blocks use the axis and the PDO locations, not an entry point. A plugin built without a protocol (`--without-canopen`, `--without-j1939`) offers no table for it, and its blocks end with the same error.

## Building it

The library's sources are in `library/canworks/`; `library/generate.py` writes the C++ blocks and `library/build.sh` builds `canworks.stlib` into the deploy package ([development.md](development.md)).
