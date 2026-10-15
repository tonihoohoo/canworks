## Why

The `canworks` library gives the PLC program blocks for CANopen (SDO, NMT, EMCY, CiA 402), raw CAN frames and J1939 trouble codes, but nothing for ordinary J1939 traffic. A program cannot:
- send a PGN when it decides, from the PLC's claimed address: `CAN_SEND` refuses frames from that address (`ERROR_ID` 4), stops at 8 bytes and does not follow an address change
- receive a PGN without a config `rx` entry, nor any PGN longer than 8 bytes (`CAN_RECEIVE` sees single frames, never transport protocol messages)
- ask another ECU for a PGN and get its answer or NACK
- read its own claim state and NAME, or find another ECU's address from its NAME

The library's documentation and naming also still present it as a CANopen SDO library: the page is `docs/plc-sdo.md` ("SDO from the PLC program: the canworks library"), `canworks-deploy library --help` describes SDO blocks only, the deploy guide calls it "The SDO block library", the tools' module is `sdolibrary`, and the library's delivery is a requirement of `canopen-plc-sdo`. It has long held CAN, J1939 and CiA 402 blocks too.

The exploration of 2026-10-15 (project notes `research/j1939-st-library-2026-10-15.md`) recommended dedicated J1939 blocks on the kernel J1939 socket the plugin already uses. Toni asked to propose it and to make the library's documentation and naming general.

## What Changes

- **J1939 function blocks** in the `canworks` library, through version 2 of `canworks_j1939_api` (the plugin keeps offering version 1 for the trouble code blocks):
  - `J1939_SEND`: sends a PGN of up to 1785 bytes from the network's claimed address; the kernel uses the transport protocol (BAM or RTS/CTS) above 8 bytes. PGNs the network itself sends are refused unless the network allows program overrides.
  - `J1939_RECEIVE`: queues received PGNs (reassembled), filtered by PGN and source, in the style of `CAN_RECEIVE`
  - `J1939_REQUEST`: sends a Request (PGN 59904) and returns the answer, or the NACK, of one ECU; to global it ends once sent
  - `J1939_ECU_INFO`: the network's claim state, address and NAME, and how many ECUs it sees
  - `J1939_FIND_ECU`: the address of an ECU found by its NAME (with a mask)
  - ST functions `J1939_GET_BITS`, `J1939_SET_BITS` (signals in messages of any length) and `J1939_NAME_MAKE`, `J1939_NAME_SPLIT`
- **Runtime plugin**: program receivers widen the J1939 receive filter while they are open; program sends, receives and requests run on the network's bus thread as the trouble code jobs do; the status answer counts them.
- **Configurator**: "Copy as ST call" on a J1939 network's `rx` and `tx` entries (a `J1939_RECEIVE` or `J1939_REQUEST`, or a `J1939_SEND`).
- **General naming of the library**:
  - new page `docs/plc-library.md`, "The canworks function block library": what it holds (CANopen, CiA 402, CAN frame and J1939 blocks, ST helpers), installing and enabling it, interface versions; `docs/plc-sdo.md` keeps only the SDO and EMCY block reference; the J1939 blocks are documented in `docs/j1939.md`
  - `canworks-deploy library --help`, the project creation output, `docs/deploy.md` ("The function block library"), `docs/configurator.md` (**Enable the canworks function blocks**, as the dialog already says), `docs/development.md` and README describe the whole library
  - the tools' module `sdolibrary` becomes `plclibrary` (with its tests); a clean cut, since nothing outside the repository imports it
  - the library's delivery moves from `canopen-plc-sdo` into a new capability `plc-library`; the editor project and configurator requirements stop calling the option "SDO blocks"
- **README** and docs updated for the blocks and the naming.

## Capabilities

### New Capabilities
- `j1939-plc-blocks`: the J1939 message blocks and ST functions and the version 2 plugin interface behind them.
- `plc-library`: the `canworks` function block library as a whole: its contents, delivery, interface versions and documentation.

### Modified Capabilities
- `canopen-plc-sdo`: "Library delivery" moves to `plc-library`; the plugin-version log no longer calls the library a CANopen library.
- `canopen-editor-project`: "SDO blocks in a new project" becomes "Function blocks in a new project".
- `canopen-configurator`: the New editor project dialog enables the canworks function blocks, not "CANopen SDO blocks".
- `j1939-pc-tools`: Copy as ST call for J1939 PGNs.
- `canopen-online-diagnostics`: the J1939 network status counts the program's J1939 sends, receivers and requests.

## Impact

- **Plugin**: `plugin/src/j1939/j1939_plc_api.*` (version 2 table), `j1939_plc_jobs.h` (send, request and receiver slots), `j1939_network.*` (serving them, filter update, status), `j1939_socket.*` (filter change on an open socket, send completion). No new dependency.
- **Library**: `library/generate.py` (J1939 message blocks), `library/src/j1939_common.inc`, new `.cpp`/`.st` files under `library/canworks/`, rebuilt `canworks.stlib`.
- **PC tools**: `canworks/plclibrary.py` (renamed), `cli.py` texts, configurator J1939 page (Copy as ST call), `test_plclibrary.py`; minor version bump.
- **Docs**: new `docs/plc-library.md`; `docs/plc-sdo.md`, `docs/j1939.md`, `docs/deploy.md`, `docs/configurator.md`, `docs/development.md`, `docs/raw-can.md`, `docs/plc-nmt.md`, `docs/cia402.md`, README.
- **CI**: the new code is in the j1939 area plus the library build; tests run in the existing unit and vcan J1939 jobs. `.github/ci/tool-test-times.json` keys follow the renamed test module.
- **Hardware**: no real J1939 ECU on the bench; the check uses the PC adapter running `canworks-j1939-sim` beside the PLC on the Pi.
- **Not in this change**: a cyclic J1939 send block (config `tx` entries and a timer with `J1939_SEND` cover it), sending Acknowledgements from the program, the Modbus bridge and the CODESYS export.
