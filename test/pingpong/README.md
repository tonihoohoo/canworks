# Ping-pong test

The slave from the [Lely C++ tutorial](https://opensource.lely.com/canopen/docs/cpp-tutorial/): it copies every value it receives in object 0x4000 into object 0x4001 and sends it back. With the PLC program `%QD100 := %ID100 + 1`, the value keeps counting up.

## Files

- `config/pingpong/cpp-slave.eds`: the slave's EDS.
- `config/pingpong/canopen_config.json`: the plugin config for it (node 2 on `vcan0`, SYNC every 100 ms, heartbeat 100 ms with a 300 ms timeout).
- `pingpong_slave.hpp`, `slave.cpp`: the slave, built as `build/test/pingpong_slave <iface> <eds> [node-id]`. The virtual-bus tests in `test/sim/` use the same class.
- `run.sh`: the end-to-end test on a SocketCAN interface.

## Objects

| Object | Name | Type | Access | Mapped | PLC address |
|---|---|---|---|---|---|
| 0x4000:00 | UNSIGNED32 received by slave | UNSIGNED32 | rww | RPDO1 (COB-ID 0x202) | `%QD100` |
| 0x4001:00 | UNSIGNED32 sent from slave | UNSIGNED32 | rwr | TPDO1 (COB-ID 0x182) | `%ID100` |
| (node status) | | | | | `%IX10.0` |

The tutorial site (opensource.lely.com) could not be reached from the build container, so the EDS in `config/pingpong/` and the 0x4000/0x4001 indices were reconstructed from the tutorial's description rather than copied from it. The EDS also has object 0x1005 (COB-ID SYNC), which the slave needs to exchange synchronous PDOs. Check both against the tutorial when it is reachable.

## Running it

```sh
sudo scripts/dev-setup.sh          # once: Lely, dcfgen, vcan0
cmake -B build -DOPENPLC_ROOT=../openplc-runtime && cmake --build build -j
test/pingpong/run.sh               # expect PASS and exit 0
test/pingpong/run.sh --no-slave    # expect FAIL and exit 1
```

`run.sh` starts the slave, then loads the real `libcanworks_plugin.so` through `build/test/canopen_host`, which calls the plugin's entry points the way the runtime does and runs the PLC program above every 10 ms. It prints `%ID100` and `%IX10.0` once a second, and a count of SYNC, SDO, PDO and heartbeat frames from `candump`.

Running the same thing inside the runtime itself needs a PLC program compiled by the OpenPLC editor, which cannot be scripted yet.
