# node-red-canworks

Node-RED nodes for the canworks Modbus TCP bridge (canworks-bridge): the
values of a canworks config by name, and the canworks PLC blocks as nodes
(CANopen NMT, SDO and EMCY, raw CAN send, cyclic send and receive, J1939
send, request, receive, DM1/DM2 and find ECU). All nodes share one Modbus
TCP connection to the bridge.

## Install

The package comes with the canworks PC tools; it is not on npm.

- `canworks-deploy --export-nodered-package .` writes
  `node-red-canworks-<version>.tgz` (also attached to each canworks
  release, and offered by the configurator's Node-RED connection).
- In Node-RED: Manage palette > Install > upload the `.tgz`, or
  `npm install /path/to/node-red-canworks-<version>.tgz` in the Node-RED
  user folder (`~/.node-red`, `/data` in Docker) and restart Node-RED.

It needs Node.js 18 or newer and Node-RED 3 or 4, and has no dependencies.

## Use

Export the flow of your config (`canworks-deploy --config canworks.json
--export-nodered flow.json`, or the configurator's Download) and import it.
Its **canworks bridge** config node carries the config's layout; export it
again after changing the config. Use the version of the package that the
flow names.

Each node's help in the editor lists its fields, outputs and ERROR_IDs. The
canworks documentation (docs/node-red.md) has the details.
