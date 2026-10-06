# Proposal

## Why

A PLC program can only reach a node's object dictionary through `sdo_variables`, which are fixed in the configuration, numeric only and one object each. A program that has to pick the node or object while it runs (a recipe download, reading a device's name, a parameter page on an HMI, a node it only finds at run time) or move a string or a block of bytes has no way to do it. CODESYS-style CiA 405 blocks (`SDO_READ`/`SDO_WRITE`) are what users expect, and this is the largest gap left on the program side. The NMT half already exists (`nmt_command_location`, state byte).

## What Changes

- New editor library **`openplc_canopen`** (a `.stlib` installed once with the editor's Library Manager) with C++ function blocks the program calls while it runs. Eight blocks, one pin layout, picked by the kind of data:
  - `CO_SDO_READ` / `CO_SDO_WRITE`: integers and bit strings up to 8 bytes, in an `LWORD` (`LWORD_TO_INT(rd.DATA)` and the like convert).
  - `CO_SDO_READ_REAL` / `CO_SDO_WRITE_REAL`: REAL32 and REAL64 objects as `LREAL`.
  - `CO_SDO_READ_STRING` / `CO_SDO_WRITE_STRING`: VISIBLE_STRING objects as `STRING`.
  - `CO_SDO_READ_BYTES` / `CO_SDO_WRITE_BYTES`: OCTET_STRING, DOMAIN and anything else, up to 1024 bytes.
  - Common pins: `EXECUTE`, `NODE`, `INDEX`, `SUBINDEX`, `TIMEOUT` in; `BUSY`, `DONE`, `ERROR`, `ERROR_ID`, `ABORT_CODE` out. PLCopen-style handshake (rising edge starts, inputs latched, result held while `EXECUTE` stays TRUE). Any node ID 1..127, configured or not.
  - A write's size can be left at 0 for a configured node: the size then comes from the node's EDS, so the usual write is just node, object and value.
- The plugin exports one versioned C entry point (`canopen_plc_api`) with a fixed table of request slots. The blocks find the already loaded plugin with `dlopen(..., RTLD_NOLOAD)` and never load a second copy. The Lely loop runs the transfers, sharing each node's SDO channel with SDO variables, the diagnostics channel and boot. The scan only fills and polls slots: no allocation, no CAN wait, no logging.
- Program transfers stop when the PLC stops; an instance that started one in an earlier run gets an error, never a stale answer.
- The configurator's object dictionary view gets **Copy as ST call**: it copies a ready-to-paste block call for the selected entry, with the right block for its EDS type.
- `openplc-canopen-deploy library --out DIR` writes the `.stlib`, and each `deploy-v` release carries it. A project made from a config can enable the library (`--sdo-blocks`, a checkbox in the configurator), so the blocks are in the library tree from the start.
- Docs: `docs/plc-sdo.md` (install the library once, examples for each kind of data, the error IDs).
- First task is a spike on real hardware: one C++ library block, built in OpenPLC Editor 4.3.2, that finds the plugin with `RTLD_NOLOAD` and reads 0x1018. If it fails, the change stops and comes back with the located-variable mailbox (option A in the earlier research) instead.

## Capabilities

### New Capabilities
- `canopen-plc-sdo`: SDO transfers started by the PLC program through the library's function blocks: block interface and handshake, data kinds and sizes, error IDs, availability of nodes, sharing the SDO channel, PLC stop, how the blocks find the plugin, and how the library is delivered.

### Modified Capabilities
- `canopen-configurator`: Copy as ST call in the object dictionary view; SDO blocks option when creating an editor project.
- `canopen-editor-project`: a project made from a config can enable the library.

## Impact

- Plugin: new `plc_api.cpp/.h` (request slots, C entry point), `Network` services program requests next to SDO variables and manual SDOs, the plugin's `.so` gets a SONAME so the blocks can find it under any install prefix. No config schema change.
- New `library/` folder: the editor library project with the C++ block sources and a shared header.
- Deploy package: carries the `.stlib`, `library` subcommand, template option, configurator button. Release workflow attaches the `.stlib`.
- Tests: a host test that compiles the block sources the way the editor does, loads them into a process that loaded the plugin `RTLD_LOCAL` like the runtime, and runs transfers against a Lely slave on vcan (integers, REAL, strings, bytes, aborts, timeout, unconfigured node, PLC stop).
- Overlap with the parallel "several CAN networks" change: a network selector would add a `NETWORK` input (0 = first network). The C table carries a network number from the start (always 0 here), so that change adds the pin without a new API version.
