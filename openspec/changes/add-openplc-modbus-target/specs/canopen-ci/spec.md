## ADDED Requirements

### Requirement: OpenPLC through Modbus integration test
CI SHALL run the pinned runtime release's own Modbus master plugin (`core/src/drivers/plugins/python/modbus_master`, on an in-memory process image) against `canworks-bridge` running the shipped bridge example as an `openplc` config with its simulated CANopen nodes, polling with the `conf/modbus_master.json` the editor's Build makes from the generated remote device. It SHALL check the map hash and status coming in, an output reaching a node and coming back as its input, an SDO read through the SDO registers, that a PLC stop as the runtime does it (outputs zeroed for one more round, then the master stops) with `on_client_loss: "hold"` keeps the last values from before the stop, and that a program with another map hash leaves outputs off. CI SHALL also run the generated `canworks_in` and `canworks_out` programs and the library's blocks on STruC++ against a bridge register model. Both SHALL run in the CI job that builds the bridge, adding under 30 s to it.

#### Scenario: Stop holds the real values
- **WHEN** the program drove an RPDO value to 0x5A and the PLC stops, writing one round of zeroed outputs
- **THEN** the simulated node keeps receiving 0x5A, never 0
