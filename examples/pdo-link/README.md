# PDO link example

A simulated network (no CAN interface) with a PDO link (docs/config.md, PDO links): node 10 (`stick`)
sends two values in its TPDO 1; node 20 (`valves`) receives them directly on its RPDO 2, the first into
0x6411:1, the second skipped with a dummy entry, and echoes 0x6411:1 in its own TPDO 1 so the PLC can
see it arrive (`%IW102` follows `%IW100`). Node 20 watches node 10's heartbeat itself
(`heartbeat_watch`). The link runs on while the PLC is stopped (`"on_plc_stop": "keep"`); node 30 is
in no link and goes PRE-OPERATIONAL on PLC stop.

Open the folder in the configurator (Open standalone config) and look at the PDO links page, or check
it with `canworks-deploy check examples/pdo-link/canworks.json`.
