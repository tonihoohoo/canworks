## Why

With several CAN networks (add-several-can-networks) the PLC program's SDO function blocks could only reach the first network in the config. A program that needs a run-time SDO transfer to a node on another network had no way to do it. The block API already carries a network number on every request, so the blocks only need an input for it.

## What Changes

- The eight `CO_SDO_*` blocks get a `NETWORK : USINT` input: the network's place in the config's `networks` list, 0 for the first. Left unset it is 0, so programs for one network keep working unchanged.
- The plugin accepts any network the running config has, and each network runs only its own requests. A network that stops cancels only its own transfers. A `NETWORK` the config does not have ends the block with `ERROR_ID` 6.
- The C API keeps version 1: its request already has the network field.
- The configurator's "Copy as ST call" sets `NETWORK` and puts the network name in the instance name when there are several networks.

## Capabilities

### New Capabilities

### Modified Capabilities
- `canopen-plc-sdo`: blocks get the `NETWORK` input; requests run on the network they name.
- `canopen-configurator`: Copy as ST call fills in `NETWORK` with several networks.

## Impact

- Library sources and `openplc_canopen.stlib` (rebuilt), plugin `plc_api`, `network.cpp`, `network_plc.cpp`, `canopen_plugin.cpp`, configurator `app.js`, docs/plc-sdo.md, docs/config.md, docs/configurator.md, README.md.
- An editor project that already uses the library picks up the new input when the library is installed again; existing calls need no change.
